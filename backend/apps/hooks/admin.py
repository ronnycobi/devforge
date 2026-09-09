from django.contrib import admin

from apps.hooks.models import Hook, HookRun


@admin.register(Hook)
class HookAdmin(admin.ModelAdmin):
    list_display = ("name", "event", "action", "blocking", "scope", "enabled")
    list_filter = ("event", "action", "blocking", "enabled")


@admin.register(HookRun)
class HookRunAdmin(admin.ModelAdmin):
    list_display = ("hook", "project", "event", "status", "blocked", "created_at")
    list_filter = ("status", "blocked", "event")
