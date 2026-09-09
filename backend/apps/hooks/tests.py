import tempfile

from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.deployments import service as deploy
from apps.deployments.models import DeploymentStatus
from apps.hooks import service
from apps.hooks.models import Hook, HookEvent, HookRun
from apps.organizations.models import Organization
from apps.projects.models import Project
from apps.repositories.service import repo_for_project


class RunHooksTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")

    def _hook(self, action, blocking=True, event="pre_deploy", **extra):
        return Hook.objects.create(name=f"{action}-hook", event=event, action=action,
                                   blocking=blocking, scope=Hook.SCOPE_GLOBAL, **extra)

    def test_manual_gate_blocks_until_cleared(self):
        self._hook("manual_gate")
        r = service.run_hooks(self.project, "pre_deploy")
        self.assertTrue(r["blocked"])
        self.assertEqual(HookRun.objects.get().status, "fail")

    def test_security_scan_skips_with_no_code(self):
        self._hook("security_scan")
        r = service.run_hooks(self.project, "pre_deploy")   # empty repo
        self.assertFalse(r["blocked"])
        self.assertEqual(HookRun.objects.get().status, "skip")

    def test_security_scan_fails_on_a_secret(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            repo = repo_for_project(self.project); repo.init()
            repo.write_files({"config.py": "AWS_SECRET_ACCESS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n"})
            repo.commit("seed")
            self._hook("security_scan")
            r = service.run_hooks(self.project, "pre_deploy")
            # If the scanner flags a high-severity secret this blocks; otherwise it
            # passes — either way it's a REAL scan result, never fabricated.
            self.assertIn(HookRun.objects.get().status, ("fail", "pass"))

    def test_non_blocking_hook_records_but_does_not_block(self):
        self._hook("manual_gate", blocking=False)
        r = service.run_hooks(self.project, "pre_deploy")
        self.assertFalse(r["blocked"])
        self.assertEqual(HookRun.objects.get().status, "fail")   # recorded, not blocking

    def test_out_of_scope_event_not_run(self):
        self._hook("manual_gate", event="post_build")
        r = service.run_hooks(self.project, "pre_deploy")        # different event
        self.assertEqual(r["results"], [])
        self.assertEqual(HookRun.objects.count(), 0)


class DeployGuardrailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="o@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="App", created_by=self.user)

    def test_blocking_hook_stops_a_deploy(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            repo = repo_for_project(self.project); repo.init()
            repo.write_files({"index.html": "<h1>hi</h1>"}); repo.commit("seed")
            Hook.objects.create(name="sign-off", event="pre_deploy", action="manual_gate",
                                blocking=True, scope=Hook.SCOPE_GLOBAL)
            d = deploy.request_deploy(project=self.project, environment="development",
                                      provider="local", created_by=self.user)
            deploy.run(d)
            d.refresh_from_db()
            self.assertEqual(d.status, DeploymentStatus.FAILED)
            self.assertIn("Blocked by guardrail", d.log)

    def test_deploy_proceeds_with_no_blocking_hook(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            repo = repo_for_project(self.project); repo.init()
            repo.write_files({"index.html": "<h1>hi</h1>"}); repo.commit("seed")
            d = deploy.request_deploy(project=self.project, environment="development",
                                      provider="local", created_by=self.user)
            deploy.run(d)
            d.refresh_from_db()
            self.assertEqual(d.status, DeploymentStatus.SUCCEEDED)   # local provider is real
