"""The preview runner really serves a project's files over a localhost port."""
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.organizations.models import Organization, Role
from apps.preview_runner.runner import PreviewError, runner
from apps.projects.models import Project
from apps.repositories.service import repo_for_project


class PreviewRunnerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="pr@x.com", password="pw12345!")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.user, role=Role.OWNER)
        self.project = Project.objects.create(organization=self.org, name="Site", created_by=self.user)

    def _seed(self, tmp):
        repo = repo_for_project(self.project)
        repo.init()
        repo.write_files({"index.html": "<h1>Hello from DevForge</h1>"})
        repo.commit("seed")

    def test_start_serves_files_then_stop(self):
        import urllib.request
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                self._seed(tmp)
                pv = runner.start_static(self.project)
                try:
                    self.assertTrue(pv.alive)
                    body = urllib.request.urlopen(f"http://127.0.0.1:{pv.port}/", timeout=5).read()
                    self.assertIn(b"Hello from DevForge", body)
                finally:
                    runner.stop(self.project.id)
                self.assertIsNone(runner.get(self.project.id))  # stopped

    def test_start_without_files_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                with self.assertRaises(PreviewError):
                    runner.start_static(self.project)  # no repo/files yet

    def test_proxy_serves_running_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                self._seed(tmp)
                runner.start_static(self.project)
                try:
                    self.client.force_login(self.user)
                    r = self.client.get(reverse("dashboard:preview_live", args=[self.project.id]))
                    self.assertEqual(r.status_code, 200)
                    self.assertIn(b"Hello from DevForge", r.content)
                finally:
                    runner.stop(self.project.id)

    def test_proxy_404_when_not_running(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("dashboard:preview_live", args=[self.project.id]))
        self.assertEqual(r.status_code, 404)


class ServerPreviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="srv@x.com", password="pw12345!")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.user, role=Role.OWNER)
        self.project = Project.objects.create(organization=self.org, name="NodeApp", created_by=self.user)

    def _seed_node(self):
        from apps.codegen.node_scaffold import scaffold_node_project
        app_js = (
            "const http = require('http');\n"
            "module.exports.makeServer = () => http.createServer((req,res)=>"
            "{res.writeHead(200,{'Content-Type':'text/plain'});res.end('Hello from Node preview');});\n"
        )
        files = scaffold_node_project("app", {"app.js": app_js})
        repo = repo_for_project(self.project)
        repo.init()
        repo.write_files(files)
        repo.commit("seed node app")

    def test_scaffold_declares_a_run_block(self):
        import json
        from apps.codegen.node_scaffold import scaffold_node_project
        manifest = json.loads(scaffold_node_project("app", {"app.js": "x"})["devforge.json"])
        self.assertIn("run", manifest)
        self.assertEqual(manifest["run"]["command"], ["node", "server.js"])

    def test_runs_the_customer_server_and_proxies_it(self):
        import shutil
        import urllib.request
        if shutil.which("node") is None:
            self.skipTest("node not available")
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                self._seed_node()
                pv = runner.start(self.project)   # declares run → runs the server
                try:
                    body = urllib.request.urlopen(f"http://127.0.0.1:{pv.port}/", timeout=5).read()
                    self.assertIn(b"Hello from Node preview", body)
                    # ...and through the Django proxy the browser iframe uses:
                    self.client.force_login(self.user)
                    r = self.client.get(reverse("dashboard:preview_live", args=[self.project.id]))
                    self.assertEqual(r.status_code, 200)
                    self.assertIn(b"Hello from Node preview", r.content)
                finally:
                    runner.stop(self.project.id)
                self.assertIsNone(runner.get(self.project.id))


class GoAndStdlibPreviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="gs@x.com", password="pw12345!")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.user, role=Role.OWNER)
        self.project = Project.objects.create(organization=self.org, name="App", created_by=self.user)

    def _seed(self, files):
        repo = repo_for_project(self.project)
        repo.init()
        repo.write_files(files)
        repo.commit("seed")

    def test_go_scaffold_declares_run_and_entrypoint(self):
        import json
        from apps.codegen.go_scaffold import scaffold_go_project
        out = scaffold_go_project("app", {"app.go": "package app\n"})
        self.assertIn("cmd/server/main.go", out)
        self.assertEqual(json.loads(out["devforge.json"])["run"]["command"], ["go", "run", "./cmd/server"])

    def test_stdlib_scaffold_only_serves_a_wsgi_app(self):
        from apps.codegen.stdlib_scaffold import scaffold_stdlib_project
        plain = scaffold_stdlib_project("app", {"calc.py": "def add(a,b): return a+b\n"})
        self.assertNotIn("devforge.json", plain)          # non-web: untouched
        web = scaffold_stdlib_project("app", {"app.py": "def application(environ, start_response):\n    pass\n"})
        self.assertIn("server.py", web)
        self.assertIn("devforge.json", web)

    def test_runs_stdlib_wsgi_server(self):
        import urllib.request
        from apps.codegen.stdlib_scaffold import scaffold_stdlib_project
        app_py = (
            "def application(environ, start_response):\n"
            "    start_response('200 OK', [('Content-Type', 'text/plain')])\n"
            "    return [b'Hello from WSGI preview']\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                self._seed(scaffold_stdlib_project("app", {"app.py": app_py}))
                pv = runner.start(self.project)
                try:
                    body = urllib.request.urlopen(f"http://127.0.0.1:{pv.port}/", timeout=5).read()
                    self.assertIn(b"Hello from WSGI preview", body)
                finally:
                    runner.stop(self.project.id)

    def test_runs_go_server(self):
        import shutil
        import urllib.request
        if shutil.which("go") is None:
            self.skipTest("go not available")
        from apps.codegen.go_scaffold import scaffold_go_project
        app_go = (
            "package app\n\nimport \"net/http\"\n\n"
            "func Handler() http.Handler {\n"
            "\tmux := http.NewServeMux()\n"
            "\tmux.HandleFunc(\"/\", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte(\"Hello from Go preview\")) })\n"
            "\treturn mux\n}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                self._seed(scaffold_go_project("app", {"app.go": app_go}))
                pv = runner.start(self.project)
                try:
                    body = urllib.request.urlopen(f"http://127.0.0.1:{pv.port}/", timeout=8).read()
                    self.assertIn(b"Hello from Go preview", body)
                finally:
                    runner.stop(self.project.id)
