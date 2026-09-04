from django.test import TestCase
from django.urls import reverse


class HealthEndpointTests(TestCase):
    def test_health_returns_ok(self):
        resp = self.client.get(reverse("core:health"))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["service"], "devforge")
        self.assertEqual(body["status"], "ok")
        self.assertIn("django", body)

    def test_health_is_public(self):
        # No authentication set up; the probe must still be reachable.
        resp = self.client.get("/api/v1/health/")
        self.assertEqual(resp.status_code, 200)
