from django.contrib import admin

from apps.database.models import DatabaseMigration


@admin.register(DatabaseMigration)
class DatabaseMigrationAdmin(admin.ModelAdmin):
    list_display = [
        "version", "project", "database_id", "operation", "status",
        "risk_level", "requires_approval", "applied_at",
    ]
    list_filter = ["status", "risk_level", "operation", "database_id", "requires_approval"]
    search_fields = ["version", "description", "project__name"]
    readonly_fields = ["created_at", "applied_at", "execution_ms"]
