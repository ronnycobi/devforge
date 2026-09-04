from django.apps import AppConfig


class CodeReviewConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.code_review"
    verbose_name = "Code Review Agent"

    def ready(self):
        from apps.code_review import agent  # noqa: F401
