from django.apps import AppConfig


class DatabaseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.database"
    label = "database_agent"
    verbose_name = "Database Agent"

    def ready(self):
        from apps.database import agent  # noqa: F401
