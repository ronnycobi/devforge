"""Tests for the deterministic security scanner and the Security Agent."""
import tempfile

from django.test import SimpleTestCase, TestCase, override_settings

from apps.agents.runners import resolve_agent
from apps.organizations.models import Organization
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project
from apps.repositories.service import repo_for_project
from apps.security.agent import SecurityAgent
from apps.security.scanner import Severity, scan_files, summarize


class ScannerTests(SimpleTestCase):
    def test_detects_hardcoded_secret(self):
        f = scan_files({"config.py": "API_KEY = 'sk-live-abcdef123456'\n"})
        self.assertTrue(any(x.category == "secret" and x.severity == Severity.HIGH for x in f))

    def test_detects_python_injection_sinks(self):
        code = "import os\nos.system(cmd)\nx = eval(data)\n"
        cats = {x.category for x in scan_files({"h.py": code})}
        self.assertIn("command-injection", cats)
        self.assertIn("code-injection", cats)

    def test_detects_subprocess_shell_true(self):
        f = scan_files({"r.py": "subprocess.run(cmd, shell=True)\n"})
        self.assertTrue(any(x.category == "command-injection" for x in f))

    def test_detects_js_xss_and_eval(self):
        cats = {x.category for x in scan_files({
            "a.jsx": "el.innerHTML = userInput;\neval(x);\n"
        })}
        self.assertIn("xss", cats)
        self.assertIn("code-injection", cats)

    def test_env_example_placeholder_is_not_flagged(self):
        # A template file's placeholder secret should not be a HIGH leak.
        f = scan_files({".env.example": "PASSWORD='changeme123'\n"})
        self.assertFalse(any(x.category == "secret" for x in f))

    def test_clean_code_has_no_findings(self):
        clean = "def add(a, b):\n    return a + b\n"
        self.assertEqual(scan_files({"calc.py": clean}), [])

    def test_env_lookup_is_not_a_secret(self):
        # Reading a secret from the environment is correct, not a finding.
        f = scan_files({"s.py": "SECRET_KEY = os.environ['SECRET_KEY']\n"})
        self.assertFalse(any(x.category == "secret" for x in f))

    def test_summary_counts_by_severity(self):
        f = scan_files({"c.py": "API_KEY = 'sk-live-xyz12345'\nDEBUG = True\n"})
        s = summarize(f)
        self.assertGreaterEqual(s["high"], 1)
        self.assertGreaterEqual(s["medium"], 1)
        self.assertEqual(s["total"], s["high"] + s["medium"] + s["low"])


class SecurityAgentTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")

    def test_registered(self):
        self.assertIsInstance(resolve_agent("security"), SecurityAgent)

    def _run(self):
        orch = Orchestrator()
        task = orch.create_task(project=self.project, agent_key="security", input={})
        orch.run_task(task)
        task.refresh_from_db()
        return task

    def test_no_code_is_not_a_failure(self):
        task = self._run()  # no repo yet
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.output["scanned"], 0)

    def test_scans_repo_and_records_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                repo = repo_for_project(self.project)
                repo.init()
                repo.write_files({"app.py": "API_KEY = 'sk-live-abc123456'\nx = eval(v)\n"})
                repo.commit("seed")
                task = self._run()
                task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertGreaterEqual(task.output["findings"]["high"], 1)
        self.assertGreaterEqual(task.output["blocking"], 1)
        # Findings recorded in the twin.
        self.assertTrue(
            ProjectContext(self.project).by_kind(ContextKind.SECURITY).exists()
        )
