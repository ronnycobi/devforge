from django.contrib import admin

from apps.backups.models import ProjectBackup


@admin.register(ProjectBackup)
class ProjectBackupAdmin(admin.ModelAdmin):
    list_display = ["label", "project", "commit_sha", "created_by", "created_at"]
    search_fields = ["label", "project__name"]
    readonly_fields = ["created_at"]
