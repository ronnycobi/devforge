"""Website forms → CRM leads (spec §23).

Website form → validation → stored submission → email notification → CRM lead. The
submission pipeline is real: it validates required fields, rejects honeypot spam,
stores the submission, emails a notification (best-effort — recorded only if it
actually sent), and creates a Lead in the CRM inbox. Nothing about delivery is faked
(spec §50): if email isn't configured, the lead is still captured and the submission
records that no notification went out.
"""
from __future__ import annotations

import html as html_lib
import re

from django.utils.text import slugify

from apps.audit.service import record as audit
from apps.publishing.models import Form, FormSubmission, Lead


# Default fields per form kind — the customer can edit these.
DEFAULT_FIELDS = {
    "contact": [
        {"name": "name", "label": "Name", "type": "text", "required": True},
        {"name": "email", "label": "Email", "type": "email", "required": True},
        {"name": "message", "label": "Message", "type": "textarea", "required": True},
    ],
    "quote": [
        {"name": "name", "label": "Name", "type": "text", "required": True},
        {"name": "email", "label": "Email", "type": "email", "required": True},
        {"name": "phone", "label": "Phone", "type": "text", "required": False},
        {"name": "message", "label": "What do you need a quote for?", "type": "textarea", "required": True},
    ],
    "newsletter": [
        {"name": "email", "label": "Email", "type": "email", "required": True},
    ],
    "booking": [
        {"name": "name", "label": "Name", "type": "text", "required": True},
        {"name": "email", "label": "Email", "type": "email", "required": True},
        {"name": "date", "label": "Preferred date", "type": "date", "required": True},
    ],
}


class FormError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(errors))


def default_notify_email(website) -> str:
    owner = website.project.created_by
    return getattr(owner, "email", "") or ""


def create_form(website, *, kind="contact", name=None, notify_email=None, fields=None, user=None) -> Form:
    base = slugify(name or kind) or "form"
    slug, n = base, 1
    while website.forms.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    form = Form.objects.create(
        website=website, slug=slug, name=name or dict(Form.KINDS).get(kind, "Form"),
        kind=kind, fields=fields or DEFAULT_FIELDS.get(kind, DEFAULT_FIELDS["contact"]),
        notify_email=notify_email or default_notify_email(website),
    )
    audit("form.create", actor=user, organization=website.project.organization,
          target=f"form:{form.id}", summary=form.name)
    return form


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate(form: Form, data: dict) -> dict:
    """Return cleaned data or raise FormError with per-issue messages."""
    errors, cleaned = [], {}
    for f in form.fields:
        name, required = f.get("name"), f.get("required")
        value = (data.get(name) or "").strip()
        if required and not value:
            errors.append(f"{f.get('label', name)} is required.")
        if value and f.get("type") == "email" and not _EMAIL_RE.match(value):
            errors.append(f"{f.get('label', name)} must be a valid email.")
        cleaned[name] = value
    if errors:
        raise FormError(errors)
    return cleaned


def submit(form: Form, data: dict) -> tuple[FormSubmission, Lead]:
    """Validate → store → email → lead. Honeypot `_gotcha` must be empty."""
    if (data.get("_gotcha") or "").strip():
        # Silently accept and drop obvious bots — store as spam, no lead/email.
        sub = FormSubmission.objects.create(form=form, data={}, is_spam=True)
        return sub, None

    cleaned = validate(form, data)
    submission = FormSubmission.objects.create(form=form, data=cleaned)

    lead = Lead.objects.create(
        website=form.website, source_form=form, submission=submission,
        name=cleaned.get("name", ""), email=cleaned.get("email", ""),
        phone=cleaned.get("phone", ""),
        message=cleaned.get("message") or cleaned.get("date") or "",
    )
    submission.email_notified = _notify(form, cleaned)
    submission.save(update_fields=["email_notified"])
    audit("form.submission", organization=form.website.project.organization,
          target=f"form:{form.id}", summary=f"lead {lead.id}")
    return submission, lead


def _notify(form: Form, cleaned: dict) -> bool:
    if not form.notify_email:
        return False
    try:
        from apps.notifications.email import send_email
        lines = "\n".join(f"{k}: {v}" for k, v in cleaned.items() if v)
        sent = send_email(
            subject=f"New {form.name} submission — {form.website.project.name}",
            to=form.notify_email,
            text=f"You received a new submission on {form.website.subdomain}:\n\n{lines}\n",
        )
        return bool(sent)
    except Exception:
        return False   # never let a delivery failure lose the lead


def embed_html(form: Form, *, action_base="") -> str:
    """A copy-paste HTML snippet for the customer's site. Posts to the DevForge form
    endpoint; includes a honeypot field for spam."""
    action = f"{action_base}/sites/{form.website.subdomain}/f/{form.slug}"
    rows = []
    for f in form.fields:
        label = html_lib.escape(f.get("label", f.get("name", "")))
        name = html_lib.escape(f.get("name", ""))
        req = " required" if f.get("required") else ""
        if f.get("type") == "textarea":
            field = f'<textarea name="{name}"{req}></textarea>'
        else:
            ftype = html_lib.escape(f.get("type", "text"))
            field = f'<input type="{ftype}" name="{name}"{req}>'
        rows.append(f'  <label>{label}<br>{field}</label>')
    body = "\n".join(rows)
    return (
        f'<form method="post" action="{html_lib.escape(action)}">\n'
        f'  <input type="text" name="_gotcha" style="display:none" tabindex="-1" autocomplete="off">\n'
        f'{body}\n'
        f'  <button type="submit">Send</button>\n'
        f'</form>'
    )
