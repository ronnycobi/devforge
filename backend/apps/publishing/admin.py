from django.contrib import admin

from apps.publishing.models import PublishVersion, Website


@admin.register(Website)
class WebsiteAdmin(admin.ModelAdmin):
    list_display = ("subdomain", "project", "site_type", "created_at")


@admin.register(PublishVersion)
class PublishVersionAdmin(admin.ModelAdmin):
    list_display = ("website", "version", "environment", "state", "health", "is_current", "created_at")
    list_filter = ("state", "health", "environment", "host")
