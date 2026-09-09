from django.contrib import admin

from apps.support.models import SupportTicket, TicketMessage


class TicketMessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "organization", "category", "priority", "status", "assigned_to", "updated_at")
    list_filter = ("status", "category", "priority")
    inlines = [TicketMessageInline]
