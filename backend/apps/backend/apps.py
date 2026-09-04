from django.apps import AppConfig


class BackendConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.backend"
    label = "backend_agent"
    verbose_name = "Backend Agent"

    def ready(self):
        from apps.backend import agent  # noqa: F401
