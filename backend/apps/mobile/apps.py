from django.apps import AppConfig


class MobileConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.mobile"
    verbose_name = "Mobile Agent"

    def ready(self):
        from apps.mobile import agent  # noqa: F401
