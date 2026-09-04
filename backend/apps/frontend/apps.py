from django.apps import AppConfig


class FrontendConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.frontend"
    verbose_name = "Frontend Agent"

    def ready(self):
        from apps.frontend import agent  # noqa: F401
