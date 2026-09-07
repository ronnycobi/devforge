from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.marketing.models import ContactMessage
from apps.organizations.models import Membership, Organization

User = get_user_model()


class PublicPagesTests(TestCase):
    PAGES = ["home", "platform", "how_it_works", "capabilities", "pricing", "about", "contact", "signup"]

    def test_all_public_pages_render_without_login(self):
        for name in self.PAGES:
            resp = self.client.get(reverse("marketing:" + name))
            self.assertEqual(resp.status_code, 200, name)

    def test_home_mentions_the_tagline(self):
        resp = self.client.get(reverse("marketing:home"))
        self.assertContains(resp, "Build.")
        self.assertContains(resp, "Deploy.")

    def test_public_pages_never_leak_internal_machinery(self):
        # The internal agent topology / orchestration is proprietary and must not
        # appear on the public marketing site (show outcomes, hide the machinery).
        forbidden = [
            "Requirements Agent", "Architect Agent", "Backend Agent",
            "Database Agent", "Testing Agent", "Code Review Agent",
            "orchestrator", "model router", "least-privilege",
            "write_backend", "review_code",
        ]
        for name in self.PAGES:
            body = self.client.get(reverse("marketing:" + name)).content.decode().lower()
            for term in forbidden:
                self.assertNotIn(term.lower(), body, f"{term!r} leaked on marketing:{name}")


class ContactTests(TestCase):
    def test_contact_stores_message(self):
        resp = self.client.post(
            reverse("marketing:contact"),
            {"name": "Ada", "email": "ada@x.com", "message": "Hi there"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(ContactMessage.objects.filter(email="ada@x.com").exists())

    def test_contact_requires_fields(self):
        self.client.post(reverse("marketing:contact"), {"name": "Ada"})
        self.assertEqual(ContactMessage.objects.count(), 0)


class SignupTests(TestCase):
    def test_signup_creates_user_org_and_logs_in(self):
        resp = self.client.post(
            reverse("marketing:signup"),
            {"email": "new@x.com", "password": "supersecret1", "org_name": "Acme"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        user = User.objects.get(email="new@x.com")
        org = Organization.objects.get(name="Acme")
        self.assertTrue(Membership.objects.filter(organization=org, user=user, role="owner").exists())
        # Logged in -> the followed redirect lands on the dashboard.
        self.assertEqual(resp.request["PATH_INFO"], reverse("dashboard:home"))

    def test_signup_rejects_short_password(self):
        self.client.post(reverse("marketing:signup"), {"email": "x@x.com", "password": "short"})
        self.assertFalse(User.objects.filter(email="x@x.com").exists())

    def test_signup_rejects_duplicate_email(self):
        User.objects.create_user(email="dup@x.com", password="pw12345678")
        self.client.post(reverse("marketing:signup"), {"email": "dup@x.com", "password": "anotherpw1"})
        self.assertEqual(User.objects.filter(email="dup@x.com").count(), 1)
