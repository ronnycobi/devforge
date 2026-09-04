from django.apps import AppConfig


class RequirementsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.requirements"
    verbose_name = "Requirements"

    def ready(self):
        # Import for the side effect of registering the executable agent runner,
        # so the Orchestrator's default resolver can find it.
        from apps.requirements import agent  # noqa: F401
