from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.credits.models import UsageRecord
from apps.credits.services import get_account
from apps.organizations.access import organizations_for
from apps.organizations.models import Organization


def _member_org(user, org_pk):
    return get_object_or_404(organizations_for(user), pk=org_pk)


class CreditBalanceView(APIView):
    """The org's credit balance. No account => unlimited (development default)."""

    def get(self, request, org_pk):
        org = _member_org(request.user, org_pk)
        account = get_account(org)
        if account is None:
            return Response(
                {"organization": org.id, "unlimited": True, "plan": None, "balance": None}
            )
        return Response(
            {
                "organization": org.id,
                "unlimited": False,
                "plan": account.plan,
                "balance": str(account.balance),
            }
        )


class UsageListView(APIView):
    """Recent usage records for the org (most recent first)."""

    def get(self, request, org_pk):
        org = _member_org(request.user, org_pk)
        records = UsageRecord.objects.filter(organization=org)[:100]
        return Response(
            [
                {
                    "id": r.id,
                    "created_at": r.created_at.isoformat(),
                    "agent_key": r.agent_key,
                    "provider": r.provider,
                    "model": r.model,
                    "total_tokens": r.total_tokens,
                    "cost_usd": str(r.cost_usd),
                    "credits_charged": str(r.credits_charged),
                    "project": r.project_id,
                    "task": r.task_id,
                }
                for r in records
            ]
        )
