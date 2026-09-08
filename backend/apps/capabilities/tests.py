"""Capability registry honesty + inference from a brief."""
from django.test import SimpleTestCase

from apps.capabilities.infer import infer_capabilities
from apps.capabilities.registry import AVAILABLE, PLANNED, all_capabilities, by_group, get


class RegistryTests(SimpleTestCase):
    def test_every_capability_has_an_honest_status(self):
        for c in all_capabilities():
            self.assertIn(c.status, (AVAILABLE, PLANNED), c.id)

    def test_planned_capabilities_are_not_marked_available(self):
        # The guardrail: things we don't offer yet must be PLANNED.
        for cid in ("payments", "subscriptions", "monitoring", "domains", "sms"):
            self.assertEqual(get(cid).status, PLANNED, cid)

    def test_real_capabilities_are_available(self):
        for cid in ("auth", "database", "email", "security", "audit", "export", "git"):
            self.assertEqual(get(cid).status, AVAILABLE, cid)

    def test_grouped(self):
        groups = dict(by_group())
        self.assertIn("Application", groups)
        self.assertIn("Business", groups)


class InferenceTests(SimpleTestCase):
    def _ids(self, brief):
        return {c.id for c in infer_capabilities(brief)}

    def test_baseline_always_present(self):
        ids = self._ids("something")
        self.assertLessEqual({"users", "auth", "database", "dashboard", "hosting"}, ids)

    def test_crm_brief_infers_crm_and_email(self):
        ids = self._ids("Build a CRM for my construction company with customers, leads and email reminders.")
        self.assertIn("crm", ids)
        self.assertIn("email", ids)

    def test_payments_and_subscriptions_inferred(self):
        ids = self._ids("A SaaS with a monthly subscription and card checkout.")
        self.assertIn("payments", ids)
        self.assertIn("subscriptions", ids)

    def test_uploads_infer_file_storage(self):
        self.assertIn("files", self._ids("Customers upload documents and photos."))
