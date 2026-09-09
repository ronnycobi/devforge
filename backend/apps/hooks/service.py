"""Run the hooks registered for a pipeline event.

run_hooks(project, event) finds every enabled in-scope hook for that event, runs its
action, records a HookRun, and returns whether promotion is BLOCKED (a blocking hook
that failed). Callers (e.g. the deploy pipeline) stop when blocked.
"""
from __future__ import annotations

from django.db.models import Q

from apps.audit.service import record as audit
from apps.hooks.actions import ACTIONS
from apps.hooks.models import Hook, HookRun


def _in_scope(event, project):
    q = Q(scope=Hook.SCOPE_GLOBAL)
    q |= Q(scope=Hook.SCOPE_ORG, organization=project.organization)
    q |= Q(scope=Hook.SCOPE_PROJECT, project=project)
    return Hook.objects.filter(enabled=True, event=event).filter(q)


def run_hooks(project, event) -> dict:
    results, blocked, reason = [], False, ""
    for hook in _in_scope(event, project):
        handler = ACTIONS.get(hook.action)
        if handler is None:
            continue
        try:
            status, detail = handler(project, hook.config or {})
        except Exception as exc:   # a broken hook must not crash the pipeline
            status, detail = "fail", f"hook error: {exc}"[:500]
        is_block = hook.blocking and status == "fail"
        HookRun.objects.create(hook=hook, project=project, event=event,
                               status=status, blocked=is_block, detail=detail[:500])
        results.append({"hook": hook.name, "action": hook.action, "status": status,
                        "blocking": hook.blocking, "detail": detail})
        if is_block and not blocked:
            blocked, reason = True, f"{hook.name}: {detail}"
    if blocked:
        audit("hooks.blocked", organization=project.organization,
              target=f"project:{project.id}", summary=f"{event} · {reason}")
    return {"blocked": blocked, "reason": reason, "results": results}
