"""Deterministic Django project scaffold.

DevForge owns the project scaffolding — settings, manage.py, a migration-free test
database — so a generated Django *app* (models.py, tests.py, …) becomes a complete
project that runs `manage.py test <app>` against a real (in-memory sqlite) test DB.
The model only has to produce correct app code; the scaffold guarantees it runs.

Migrations are disabled (MIGRATION_MODULES → None) so the test runner creates
tables directly from the models — no generated migration files required.
"""
from __future__ import annotations

import re

_MANAGE_PY = (
    "import os\n"
    "import sys\n\n"
    'os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")\n\n'
    "if __name__ == '__main__':\n"
    "    from django.core.management import execute_from_command_line\n"
    "    execute_from_command_line(sys.argv)\n"
)

_SETTINGS_PY = '''\
SECRET_KEY = "insecure-test-key"
DEBUG = True
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "{app}",
]
DATABASES = {{
    "default": {{"ENGINE": "django.db.backends.sqlite3", "NAME": "db.sqlite3"}}
}}


class _DisableMigrations:
    # Create tables straight from the models; no migration files needed.
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = _DisableMigrations()
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
'''

_APPS_PY = (
    "from django.apps import AppConfig\n\n\n"
    "class {cls}Config(AppConfig):\n"
    '    name = "{app}"\n'
    '    default_auto_field = "django.db.models.BigAutoField"\n'
)


def normalize_app_label(label: str) -> str:
    label = re.sub(r"[^0-9a-zA-Z_]", "_", (label or "").strip().lower())
    if not label or not label[0].isalpha():
        label = "app_" + label
    return label[:40]


def scaffold_django_project(app_label: str, app_files: dict[str, str]) -> dict[str, str]:
    """Wrap app files (relative to the app package) into a runnable project.

    Returns a full path->content map, plus a devforge.json manifest naming the
    test command so the runner knows to use `manage.py test <app>`.
    """
    app = normalize_app_label(app_label)
    cls = "".join(part.capitalize() for part in app.split("_")) or "App"

    files: dict[str, str] = {
        "manage.py": _MANAGE_PY,
        "settings.py": _SETTINGS_PY.format(app=app),
        f"{app}/__init__.py": "",
        f"{app}/apps.py": _APPS_PY.format(cls=cls, app=app),
        "devforge.json": (
            '{\n'
            '  "stack": "django",\n'
            f'  "app": "{app}",\n'
            f'  "test_command": ["python", "manage.py", "test", "{app}", "-v", "2"]\n'
            '}\n'
        ),
    }
    for rel, content in app_files.items():
        files[f"{app}/{rel}"] = content
    return files
