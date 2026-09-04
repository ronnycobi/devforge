from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.access import (
    manageable_organizations_for,
    organizations_for,
)
from apps.orchestrator.models import AgentTask
from apps.orchestrator.serializers import AgentTaskSerializer
from apps.orchestrator.service import Orchestrator
from apps.projects.models import Project


def _project_for_read(user, project_pk):
    # 404 for projects outside the user's organizations (no existence leak).
    return get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(user)),
        pk=project_pk,
    )


def _require_manageable_project(user, project_pk):
    project = _project_for_read(user, project_pk)
    if project.organization not in manageable_organizations_for(user):
        raise PermissionDenied("You must be an owner or admin to run agent work.")
    return project


class TaskListCreateView(generics.ListCreateAPIView):
    serializer_class = AgentTaskSerializer

    def get_queryset(self):
        project = _project_for_read(self.request.user, self.kwargs["project_pk"])
        return project.agent_tasks.all()

    def perform_create(self, serializer):
        project = _require_manageable_project(
            self.request.user, self.kwargs["project_pk"]
        )
        data = serializer.validated_data
        self._assert_same_project(project, data)
        orchestrator = Orchestrator()
        task = orchestrator.create_task(
            project=project,
            agent_key=data["agent_key"],
            input=data.get("input") or {},
            workspace=data.get("workspace"),
            parent_task=data.get("parent_task"),
            priority=data.get("priority", 0),
            approval_required=data.get("approval_required", False),
            max_attempts=data.get("max_attempts", 1),
            created_by=self.request.user,
            depends_on=data.get("depends_on"),
        )
        serializer.instance = task

    @staticmethod
    def _assert_same_project(project, data):
        # Never let a task reference another project's workspace/tasks.
        workspace = data.get("workspace")
        if workspace and workspace.project_id != project.id:
            raise ValidationError({"workspace": "Must belong to this project."})
        parent = data.get("parent_task")
        if parent and parent.project_id != project.id:
            raise ValidationError({"parent_task": "Must belong to this project."})
        for dep in data.get("depends_on") or []:
            if dep.project_id != project.id:
                raise ValidationError(
                    {"depends_on": "Dependencies must belong to this project."}
                )


class TaskDetailView(generics.RetrieveAPIView):
    serializer_class = AgentTaskSerializer

    def get_queryset(self):
        return AgentTask.objects.filter(
            project__organization__in=organizations_for(self.request.user)
        )


class _TaskActionView(APIView):
    """Base for manage-only actions on a single task."""

    def get_task(self):
        task = get_object_or_404(AgentTask, pk=self.kwargs["pk"])
        if task.project.organization not in organizations_for(self.request.user):
            # Hide existence from non-members.
            from django.http import Http404

            raise Http404
        if task.project.organization not in manageable_organizations_for(
            self.request.user
        ):
            raise PermissionDenied("Owner or admin required.")
        return task


class TaskApproveView(_TaskActionView):
    def post(self, request, pk):
        task = self.get_task()
        Orchestrator().approve(task, request.user)
        return Response(AgentTaskSerializer(task).data, status=status.HTTP_200_OK)


class TaskCancelView(_TaskActionView):
    def post(self, request, pk):
        task = self.get_task()
        Orchestrator().cancel(task)
        return Response(AgentTaskSerializer(task).data, status=status.HTTP_200_OK)
