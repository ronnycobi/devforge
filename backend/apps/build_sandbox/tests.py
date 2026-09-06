import os
import sys

from django.test import SimpleTestCase

from apps.build_sandbox.base import SandboxError, SandboxLimits
from apps.build_sandbox.service import get_sandbox
from apps.build_sandbox.subprocess_sandbox import SubprocessSandbox


class SubprocessSandboxTests(SimpleTestCase):
    def setUp(self):
        self.sbx = SubprocessSandbox()

    def test_captures_stdout_and_exit_zero(self):
        result = self.sbx.run_python("print('hello sandbox')")
        self.assertTrue(result.ok)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("hello sandbox", result.stdout)

    def test_nonzero_exit_is_reported(self):
        result = self.sbx.run_python("import sys; sys.exit(3)")
        self.assertEqual(result.exit_code, 3)
        self.assertFalse(result.ok)

    def test_wall_timeout_kills_process(self):
        result = self.sbx.run_python(
            "import time; time.sleep(30)",
            limits=SandboxLimits(wall_timeout_seconds=1.0, cpu_seconds=30),
        )
        self.assertTrue(result.timed_out)
        self.assertLess(result.duration_seconds, 5.0)  # killed, didn't sleep 30s

    def test_files_are_written_into_the_workdir(self):
        result = self.sbx.run(
            [sys.executable, "-c", "print(open('data.txt').read())"],
            files={"data.txt": "payload-123"},
        )
        self.assertIn("payload-123", result.stdout)

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(SandboxError):
            self.sbx.run([sys.executable, "-c", "pass"], files={"../escape.txt": "x"})

    def test_environment_is_scrubbed(self):
        os.environ["DEVFORGE_SECRET_XYZ"] = "leaked"
        try:
            result = self.sbx.run_python(
                "import os; print(os.environ.get('DEVFORGE_SECRET_XYZ'))"
            )
        finally:
            del os.environ["DEVFORGE_SECRET_XYZ"]
        self.assertIn("None", result.stdout)  # secret not inherited

    def test_output_is_bounded(self):
        result = self.sbx.run_python(
            "print('A' * 100000)",
            limits=SandboxLimits(max_output_bytes=1000),
        )
        self.assertTrue(result.output_truncated)
        self.assertLess(len(result.stdout.encode()), 1200)

    def test_runs_in_a_fresh_workdir_each_time(self):
        self.sbx.run_python("open('x.txt','w').write('1')")
        result = self.sbx.run_python(
            "import os; print(os.path.exists('x.txt'))"
        )
        self.assertIn("False", result.stdout)  # previous run's files are gone


class ServiceTests(SimpleTestCase):
    def test_default_backend_is_subprocess(self):
        self.assertIsInstance(get_sandbox(), SubprocessSandbox)
