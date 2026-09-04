from django.apps import AppConfig


class TestingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.testing"
    verbose_name = "Testing Agent"

    def ready(self):
        from apps.testing import agent  # noqa: F401
