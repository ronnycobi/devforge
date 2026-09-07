"""Access control for the internal staff console.

The console is DevForge's own operations cockpit — it spans every tenant and
exposes internal machinery (orchestrator, model routing, economics). It is
strictly staff-only: anonymous users are sent to log in, authenticated
non-staff get a hard 403. Never widen this to customers.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse


def staff_required(view):
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect(f"{reverse('dashboard:login')}?next={request.path}")
        if not user.is_staff:
            raise PermissionDenied("The staff console is restricted to DevForge staff.")
        return view(request, *args, **kwargs)

    return _wrapped
