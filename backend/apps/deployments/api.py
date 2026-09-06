from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.deployments.models import Deployment
from apps.deployments.service import DeploymentError, approve, request_deploy, run
from apps.organizations.access import manageable_organizations_for, organizations_for
from apps.projects.access import project_for_read, require_manageable_project


class DeploymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Deployment
        fields = [
            "id", "project", "workspace", "environment", "provider", "status",
            "url", "log", "approved", "approved_by", "created_by",
            "created_at", "completed_at",
        ]
        read_only_fields = fields


class DeploymentListCreateView(generics.ListCreateAPIView):
    serializer_class = DeploymentSerializer

    def get_queryset(self):
        project = project_for_read(self.request.user, self.kwargs["project_pk"])
        return project.deployments.all()

    def create(self, request, *args, **kwargs):
        project = require_manageable_project(request.user, self.kwargs["project_pk"])
        try:
            deployment = request_deploy(
                project=project,
                environment=request.data.get("environment", ""),
                provider=request.data.get("provider", "local"),
                created_by=request.user,
            )
        except DeploymentError as exc:
            raise ValidationError(str(exc))
        data = DeploymentSerializer(deployment).data
        return Response(data, status=201)


class _DeploymentActionView(APIView):
    def get_deployment(self):
        deployment = get_object_or_404(Deployment, pk=self.kwargs["pk"])
        org = deployment.project.organization
        if org not in organizations_for(self.request.user):
            from django.http import Http404

            raise Http404
        if org not in manageable_organizations_for(self.request.user):
            raise PermissionDenied("Owner or admin required.")
        return deployment


class DeploymentApproveView(_DeploymentActionView):
    def post(self, request, pk):
        deployment = self.get_deployment()
        approve(deployment, request.user)
        return Response(DeploymentSerializer(deployment).data)


class DeploymentRunView(_DeploymentActionView):
    def post(self, request, pk):
        deployment = self.get_deployment()
        run(deployment)
        return Response(DeploymentSerializer(deployment).data)
