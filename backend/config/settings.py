"""
Django settings for DevForge.

Configuration is driven entirely by environment variables so the same code runs
locally, in CI, and in production without edits. See `.env.example` for the full
list. Secrets NEVER live in this file or in version control.
"""
import os
import sys
from pathlib import Path

# backend/ directory (this file is backend/config/settings.py).
BASE_DIR = Path(__file__).resolve().parent.parent


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def env_list(key: str, default: str = "") -> list[str]:
    raw = os.environ.get(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# --- Core -------------------------------------------------------------------

SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    # DevForge apps (modular monolith; add phased apps here — see docs/PRODUCT.md)
    "apps.core",
    "apps.accounts",
    "apps.organizations",
    "apps.projects",
    "apps.workspaces",
    "apps.technology",
    "apps.capabilities",
    "apps.agents",
    "apps.tools",
    "apps.orchestrator",
    "apps.ai_providers",
    "apps.model_router",
    "apps.project_context",
    "apps.requirements",
    "apps.architecture",
    "apps.backend",
    "apps.frontend",
    "apps.database",
    "apps.testing",
    "apps.code_review",
    "apps.security",
    "apps.mobile",
    "apps.devops",
    "apps.build_sandbox",
    "apps.preview_runner",
    "apps.repositories",
    "apps.codegen",
    "apps.exporter",
    "apps.credits",
    "apps.costs",
    "apps.deployments",
    "apps.changes",
    "apps.backups",
    "apps.ingest",
    "apps.dashboard",
    "apps.console",
    "apps.audit",
    "apps.release",
    "apps.publishing",
    "apps.marketing",
    "apps.notifications",
]

# --- Auth redirects (server-rendered dashboard UI) --------------------------
LOGIN_URL = "dashboard:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "dashboard:login"

# Email is the identity across DevForge; set before any migrations reference it.
AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    # Serve verified custom domains by Host header (real virtual hosting). Outermost
    # so a customer domain is served from our controlled allowlist before host
    # validation rejects it as an unknown ALLOWED_HOST.
    "apps.publishing.middleware.CustomDomainMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --- Database ---------------------------------------------------------------
# Production target is PostgreSQL (set DB_ENGINE=postgres + DB_* vars). When
# unset the project falls back to SQLite so the app stays runnable and testable
# without a database server — see docs/PRODUCT.md, Phase 1.

if env("DB_ENGINE", "sqlite") == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME", "devforge"),
            "USER": env("DB_USER", "devforge"),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "127.0.0.1"),
            "PORT": env("DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# --- Auth / passwords -------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- i18n / tz --------------------------------------------------------------
# DevForge builds software for customers worldwide — do not assume one locale.

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("DJANGO_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

# --- Static -----------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Project static assets (logo, etc.). Served by runserver in DEBUG; collectstatic
# gathers them for production.
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Speed up the test suite: real password hashing dominates test setup time and
# adds no coverage. Only applied when running tests.
if "test" in sys.argv:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# --- DRF --------------------------------------------------------------------

# --- AI providers (Phase 6) -------------------------------------------------
# Which provider the gateway uses when none is named. Defaults to the offline
# "stub" so a fresh checkout runs with no API keys. Set to "anthropic" (and
# export ANTHROPIC_API_KEY) for real completions. Provider API keys are read
# from the environment by each provider — never stored here.
AI_DEFAULT_PROVIDER = env("AI_DEFAULT_PROVIDER", "stub")

# --- Generated-project storage ----------------------------------------------
# Where per-project git working trees live (apps.repositories). Defaults to a
# gitignored dir beside the backend; set DEVFORGE_WORKSPACES_ROOT in production.
DEVFORGE_WORKSPACES_ROOT = env(
    "DEVFORGE_WORKSPACES_ROOT", str(BASE_DIR / "workspaces")
)

# --- Credits & plans (Phase 19) ---------------------------------------------
# Credits are a platform abstraction over cost. These are config, never
# hard-coded into billing logic — tune freely.
DEVFORGE_CREDITS_PER_USD = env("DEVFORGE_CREDITS_PER_USD", "100")
DEVFORGE_PLANS = {"free": 1000, "pro": 5000, "business": 25000}
# Platform-wide hard cap on AI spend per org per day (USD). Blank/unset = no
# global cap (each org may still set its own on its CreditAccount). This is the
# safety rail that lets you hand out access without risking a runaway bill.
DEVFORGE_ORG_DAILY_USD_CAP = env("DEVFORGE_ORG_DAILY_USD_CAP", "") or None

# Model-selection posture. True (default) = pick the most capable model that fits
# each task (best product); False = cheapest-sufficient. A task can still opt the
# other way per request, or set a hard max_cost_per_mtok ceiling.
DEVFORGE_PREFER_QUALITY = env("DEVFORGE_PREFER_QUALITY", "true").lower() in ("1", "true", "yes", "on")

# Website publishing domains. BASE_DOMAIN is the DevForge subdomain zone; TARGET is
# the hostname a customer points their custom domain at (CNAME target). These are
# the correct DNS instructions to give; routing/SSL only complete once DevForge
# hosting actually serves the domain (a later, infra-gated phase).
DEVFORGE_BASE_DOMAIN = env("DEVFORGE_BASE_DOMAIN", "devforge.app")
DEVFORGE_DOMAIN_TARGET = env("DEVFORGE_DOMAIN_TARGET", "hosting.devforge.app")

# Email. Real delivery when EMAIL_BACKEND points at SMTP and the host is set;
# dev defaults to the console backend (prints emails) so nothing is faked and no
# server is required. Tests capture via the locmem backend automatically.
EMAIL_BACKEND = env(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "DevForge <no-reply@devforge.local>")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# --- Security (tightened automatically when DEBUG is off) -------------------

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
