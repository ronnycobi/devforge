"""The prove_build harness runs end-to-end and cleans up (stub provider)."""
import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.organizations.models import Organization
from apps.projects.models import Project


class ProveBuildCommandTests(TestCase):
    def test_runs_full_pipeline_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                out = StringIO()
                call_command(
                    "prove_build", brief="A notes API", stack="python-stdlib",
                    stdout=out, stderr=StringIO(),
                )
        text = out.getvalue()
        self.assertIn("end-to-end build", text)
        self.assertIn("requirements", text)
        self.assertIn("security", text)
        # Default cleanup removes the proof org/project.
        self.assertFalse(Organization.objects.filter(name="Proof Org").exists())
        self.assertFalse(Project.objects.filter(name="Proof Build").exists())

    def test_keep_retains_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                call_command(
                    "prove_build", brief="A todo API", stack="python-stdlib",
                    keep=True, stdout=StringIO(), stderr=StringIO(),
                )
        self.assertTrue(Project.objects.filter(name="Proof Build").exists())
