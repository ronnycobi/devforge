import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from apps.repositories.service import GitError, ProjectRepo


class ProjectRepoTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = ProjectRepo(Path(self._tmp.name) / "repo").init()

    def tearDown(self):
        self._tmp.cleanup()

    def test_init_creates_repo_on_main(self):
        self.assertTrue(self.repo.is_initialized)
        self.repo.write_files({"README.md": "# App"})
        self.repo.commit("initial")
        self.assertEqual(self.repo.current_branch(), "main")

    def test_write_and_commit_tracks_files(self):
        self.repo.write_files({"src/app.py": "print(1)", "README.md": "hi"})
        sha = self.repo.commit("add app")
        self.assertTrue(sha)
        self.assertIn("src/app.py", self.repo.list_files())
        log = self.repo.log()
        self.assertEqual(log[0]["subject"], "add app")

    def test_commit_with_nothing_staged_raises(self):
        with self.assertRaises(GitError):
            self.repo.commit("empty")

    def test_branch_create_and_checkout(self):
        self.repo.write_files({"a.txt": "1"})
        self.repo.commit("first")
        self.repo.create_branch("feature")
        self.assertEqual(self.repo.current_branch(), "feature")
        self.repo.checkout("main")
        self.assertEqual(self.repo.current_branch(), "main")

    def test_diff_shows_uncommitted_changes(self):
        self.repo.write_files({"a.txt": "1\n"})
        self.repo.commit("first")
        self.repo.write_files({"a.txt": "2\n"})
        diff = self.repo.diff()
        self.assertIn("+2", diff)

    def test_path_traversal_rejected(self):
        with self.assertRaises(GitError):
            self.repo.write_files({"../escape.txt": "x"})
