from django.apps import AppConfig


class ToolsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tools"
    verbose_name = "Tool Registry"

    def ready(self):
        from apps.tools import builtin  # noqa: F401  (registers built-in tools)
        from apps.tools import connectors  # noqa: F401  (registers external connectors)
