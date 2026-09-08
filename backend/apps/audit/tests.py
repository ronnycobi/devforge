"""Audit log: record() writes events, key actions log, staff can view."""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.audit.service import record
from apps.changes import service as changes_service
from apps.organizations.models import Organization, Role
from apps.projects.models import Project


class RecordTests(TestCase):
    def test_record_creates_event(self):
        org = Organization.objects.create(name="Acme")
        ev = record("test.action", organization=org, target="x:1", summary="hi")
        self.assertIsNotNone(ev)
        self.assertEqual(AuditEvent.objects.count(), 1)
        self.assertEqual(ev.action, "test.action")

    def test_long_summary_is_truncated_not_raised(self):
        ev = record("x.long", summary="z" * 1000, metadata={"k": "v"})
        self.assertIsNotNone(ev)
        self.assertLessEqual(len(ev.summary), 500)


class ActionLoggingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="a@x.com", password="x")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.user, role=Role.OWNER)
        self.project = Project.objects.create(organization=self.org, name="App", created_by=self.user)

    def test_change_approval_is_audited(self):
        change = changes_service.create_change(self.project, "Add search", self.user)
        change.requires_approval = True
        change.save(update_fields=["requires_approval"])
        changes_service.approve(change, self.user)
        self.assertTrue(
            AuditEvent.objects.filter(action="change.approved",
                                      target=f"change:{change.id}").exists()
        )


class ConsoleAuditPageTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(email="s@devforge.local", password="x", is_staff=True)
        self.customer = User.objects.create_user(email="c@x.com", password="x")
        record("change.approved", organization=Organization.objects.create(name="Acme"),
               target="change:1", summary="seed")

    def test_staff_sees_audit(self):
        self.client.force_login(self.staff)
        r = self.client.get(reverse("console:audit"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "change.approved")

    def test_customer_forbidden(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse("console:audit")).status_code, 403)
