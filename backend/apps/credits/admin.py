from django.contrib import admin

from apps.credits.models import CreditAccount, UsageRecord


@admin.register(CreditAccount)
class CreditAccountAdmin(admin.ModelAdmin):
    list_display = ["organization", "plan", "balance", "daily_usd_cap", "updated_at"]
    list_editable = ["daily_usd_cap"]
    search_fields = ["organization__name"]
    autocomplete_fields = ["organization"]


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = [
        "created_at",
        "organization",
        "agent_key",
        "model",
        "total_tokens",
        "credits_charged",
    ]
    list_filter = ["provider", "model", "agent_key"]
    search_fields = ["organization__name", "model"]
    readonly_fields = [f.name for f in UsageRecord._meta.fields]
