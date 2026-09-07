from django.contrib import admin

from apps.marketing.models import ContactMessage


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "company", "created_at"]
    search_fields = ["name", "email", "company", "message"]
    readonly_fields = [f.name for f in ContactMessage._meta.fields]
