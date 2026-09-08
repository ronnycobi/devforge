"""Backups: a snapshot captures the repo; restore rolls it back — for real."""
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.backups.models import ProjectBackup
from apps.backups.service import BackupError, create_backup, restore_backup
from apps.organizations.models import Organization, Role
from apps.projects.models import Project
from apps.repositories.service import repo_for_project


class BackupServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="b@x.com", password="pw12345!")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.user, role=Role.OWNER)
        self.project = Project.objects.create(organization=self.org, name="App", created_by=self.user)

    def test_backup_without_repo_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                with self.assertRaises(BackupError):
                    create_backup(self.project, label="x", created_by=self.user)

    def test_create_and_restore_rolls_the_repo_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                repo = repo_for_project(self.project)
                repo.init()
                repo.write_files({"a.py": "x = 1\n"})
                repo.commit("v1")
                backup = create_backup(self.project, label="v1", created_by=self.user)
                self.assertTrue(backup.commit_sha)

                repo.write_files({"b.py": "y = 2\n"})
                repo.commit("v2")
                self.assertIn("b.py", repo.list_files())

                restore_backup(backup, actor=self.user)
                self.assertNotIn("b.py", repo.list_files())   # rolled back for real
                self.assertIn("a.py", repo.list_files())


class BackupUITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="o@x.com", password="pw12345!")
        self.member = User.objects.create_user(email="m@x.com", password="pw12345!")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.owner, role=Role.OWNER)
        self.org.add_member(self.member, role=Role.MEMBER)
        self.project = Project.objects.create(organization=self.org, name="App", created_by=self.owner)

    def _seed(self):
        repo = repo_for_project(self.project)
        repo.init()
        repo.write_files({"a.py": "x = 1\n"})
        repo.commit("v1")

    def test_owner_creates_backup_via_ui(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                self._seed()
                self.client.force_login(self.owner)
                self.client.post(reverse("dashboard:project", args=[self.project.id]),
                                 {"action": "create_backup", "label": "Before changes"})
        self.assertTrue(ProjectBackup.objects.filter(project=self.project, label="Before changes").exists())

    def test_member_cannot_create_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                self._seed()
                self.client.force_login(self.member)
                self.client.post(reverse("dashboard:project", args=[self.project.id]),
                                 {"action": "create_backup", "label": "Nope"})
        self.assertFalse(ProjectBackup.objects.filter(project=self.project).exists())
