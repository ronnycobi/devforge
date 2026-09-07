from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class UserModelTests(TestCase):
    def test_create_user_normalizes_email_domain(self):
        user = User.objects.create_user(email="Ada@Example.COM", password="pw12345!")
        self.assertEqual(user.email, "Ada@example.com")
        self.assertTrue(user.check_password("pw12345!"))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_user_requires_email(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password="pw12345!")

    def test_create_superuser(self):
        admin = User.objects.create_superuser(
            email="root@example.com", password="pw12345!"
        )
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_email_is_the_username_field(self):
        self.assertEqual(User.USERNAME_FIELD, "email")
        self.assertEqual(User.REQUIRED_FIELDS, [])

    def test_get_by_natural_key_enables_authentication(self):
        from django.contrib.auth import authenticate

        User.objects.create_user(email="log@example.com", password="pw12345!")
        # Exercises ModelBackend -> manager.get_by_natural_key (admin login path).
        self.assertEqual(User.objects.get_by_natural_key("log@example.com").email, "log@example.com")
        self.assertIsNotNone(authenticate(username="log@example.com", password="pw12345!"))
        self.assertIsNone(authenticate(username="log@example.com", password="wrong"))

    def test_short_name(self):
        user = User.objects.create_user(
            email="grace@example.com", password="pw12345!", full_name="Grace Hopper"
        )
        self.assertEqual(user.short_name, "Grace")


class MeEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="dev@example.com", password="pw12345!", full_name="Dev User"
        )

    def test_me_requires_authentication(self):
        resp = self.client.get(reverse("accounts:me"))
        self.assertEqual(resp.status_code, 403)

    def test_me_returns_user_and_organizations(self):
        from apps.organizations.models import Organization, Role

        org = Organization.objects.create(name="Acme")
        org.add_member(self.user, role=Role.OWNER)

        self.client.force_login(self.user)
        resp = self.client.get(reverse("accounts:me"))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["email"], "dev@example.com")
        self.assertEqual(len(body["organizations"]), 1)
        self.assertEqual(body["organizations"][0]["slug"], "acme")
        self.assertEqual(body["organizations"][0]["role"], "owner")
