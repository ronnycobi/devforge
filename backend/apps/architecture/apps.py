from django.apps import AppConfig


class ArchitectureConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.architecture"
    verbose_name = "Architecture"

    def ready(self):
        # Register the executable agent runner.
        from apps.architecture import agent  # noqa: F401
