"""Tests for the email layer (captured via Django's locmem test backend)."""
from django.core import mail
from django.test import TestCase

from apps.notifications.email import send_email, send_invitation_email
from apps.organizations import invitations
from apps.organizations.models import Organization, Role


class SendEmailTests(TestCase):
    def test_send_plain_and_html(self):
        n = send_email(subject="Hi", to="a@x.com", text="hello",
                       html="<p>hello</p>")
        self.assertEqual(n, 1)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["a@x.com"])
        self.assertEqual(msg.subject, "Hi")
        self.assertEqual(msg.alternatives[0][1], "text/html")

    def test_no_recipient_is_noop(self):
        self.assertEqual(send_email(subject="x", to="", text="y"), 0)
        self.assertEqual(len(mail.outbox), 0)


class InvitationEmailTests(TestCase):
    def test_invitation_email_contains_accept_link(self):
        org = Organization.objects.create(name="Acme")
        inv = invitations.create_invitation(org, "new@x.com", role=Role.ADMIN)
        url = "https://devforge.example/app/invite/TOKEN123/"
        send_invitation_email(inv, url)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["new@x.com"])
        self.assertIn("Acme", msg.subject)
        self.assertIn(url, msg.body)  # plain-text body carries the link
