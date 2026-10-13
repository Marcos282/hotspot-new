import os
import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "development-only-change-me")
if not DEBUG and (
    SECRET_KEY == "development-only-change-me" or len(SECRET_KEY) < 50
):
    raise RuntimeError(
        "Set DJANGO_SECRET_KEY to a random value of at least 50 characters "
        "when DJANGO_DEBUG is false."
    )

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,testserver,.localhost,novainfo.com.br,.novainfo.com.br",
    ).split(",")
    if host.strip()
]
TENANT_ROOT_DOMAIN = os.environ.get("TENANT_ROOT_DOMAIN", "novainfo.com.br").lower()

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tenants",
    "website",
    "operations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "tenants.middleware.TenantMiddleware",
]

ROOT_URLCONF = "novainfo.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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
WSGI_APPLICATION = "novainfo.wsgi.application"
ASGI_APPLICATION = "novainfo.asgi.application"

# Only local development can load the private project-local database descriptor.
local_database = {}
local_database_file = BASE_DIR / '.local' / 'database.json'
if DEBUG and local_database_file.is_file():
    local_database = json.loads(local_database_file.read_text())


def database_env(name, default):
    return os.environ.get(name, local_database.get(name, default))


if database_env("DB_ENGINE", "sqlite").lower() == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": database_env("DB_NAME", "novainfo"),
            "USER": database_env("DB_USER", "novainfo"),
            "PASSWORD": database_env("DB_PASSWORD", ""),
            "HOST": database_env("DB_HOST", "localhost"),
            "PORT": database_env("DB_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/painel/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# Runtime credentials must not bypass PostgreSQL row policies.
if not DEBUG and DATABASES['default']['ENGINE'] != 'django.db.backends.postgresql':
    raise RuntimeError('Multi-tenant production requires PostgreSQL with RLS.')
DATA_UPLOAD_MAX_MEMORY_SIZE = 3 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

ROUTEROS_CREDENTIAL_KEY = os.environ.get('ROUTEROS_CREDENTIAL_KEY', '')
local_credential_key = BASE_DIR / '.local' / 'routeros.key'
if DEBUG and not ROUTEROS_CREDENTIAL_KEY and local_credential_key.is_file():
    ROUTEROS_CREDENTIAL_KEY = local_credential_key.read_text().strip()
WG_EXECUTABLE = os.environ.get('WG_EXECUTABLE', '/usr/bin/wg')
WG_MONITOR_USER_ID = os.environ.get('WG_MONITOR_USER_ID', '')
MONITOR_MAX_GAP_SECONDS = int(os.environ.get('MONITOR_MAX_GAP_SECONDS', '300'))

WG_STATUS_FILE = os.environ.get('WG_STATUS_FILE', '/var/lib/novainfo/wireguard-status.json')

# Authentication emails: credentials belong in the service environment.
EMAIL_BACKEND = 'tenants.email_backend.EmailBackend'
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
DEFAULT_FROM_EMAIL = os.environ.get('RESEND_FROM_EMAIL', '')
PASSWORD_RESET_TIMEOUT = 3600
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_DOMAIN = None
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 3600
