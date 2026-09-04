from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.project_context.models import ContextEntry
from apps.project_context.serializers import ContextEntrySerializer
from apps.project_context.services import ProjectContext
from apps.projects.access import project_for_read, require_manageable_project


class ContextListCreateView(generics.ListCreateAPIView):
    serializer_class = ContextEntrySerializer

    def get_queryset(self):
        project = project_for_read(self.request.user, self.kwargs["project_pk"])
        qs = project.context_entries.all()
        kind = self.request.query_params.get("kind")
        return qs.filter(kind=kind) if kind else qs

    def perform_create(self, serializer):
        project = require_manageable_project(
            self.request.user, self.kwargs["project_pk"]
        )
        data = serializer.validated_data
        ctx = ProjectContext(project)
        kind = data["kind"]
        key = data.get("key")
        common = {
            "title": data.get("title", ""),
            "content": data.get("content", ""),
            "data": data.get("data") or {},
            "source": data.get("source", ""),
            "created_by": self.request.user,
        }
        if key:
            if ctx.get(kind, key):
                raise ValidationError(
                    {"key": "An entry with this kind+key exists; PATCH it instead."}
                )
            entry = ctx.set(kind, key, **common)
        else:
            if not common["title"]:
                raise ValidationError({"title": "title is required when key is omitted."})
            entry = ctx.add(kind, **common)
        serializer.instance = entry


class ContextDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ContextEntrySerializer

    def _base_qs(self):
        return ContextEntry.objects.filter(project__in=self._readable_projects())

    def _readable_projects(self):
        from apps.organizations.access import organizations_for
        from apps.projects.models import Project

        return Project.objects.filter(
            organization__in=organizations_for(self.request.user)
        )

    def get_queryset(self):
        # Reads: any member. Writes/deletes: managers only (checked below).
        return self._base_qs()

    def _assert_can_write(self, obj):
        require_manageable_project(self.request.user, obj.project_id)

    def perform_update(self, serializer):
        self._assert_can_write(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._assert_can_write(instance)
        instance.delete()


class ContextDigestView(APIView):
    """Return the compact digest agents inject into prompts."""

    def get(self, request, project_pk):
        project = project_for_read(request.user, project_pk)
        kinds = request.query_params.getlist("kind") or None
        digest = ProjectContext(project).digest(kinds=kinds)
        return Response({"project": project.id, "digest": digest})
