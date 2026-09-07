from django.apps import AppConfig


class DevopsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.devops"
    verbose_name = "DevOps Agent"

    def ready(self):
        from apps.devops import agent  # noqa: F401
