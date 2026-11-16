"""Django settings for ZARVON Marketplace & Multi-Bank Nasiya Platform."""
import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "zarvon-dev-only-secret-key-change-in-production-9f4e2a8c1d7b",
)
ZARVON_FIELD_SECRET = os.environ.get("ZARVON_FIELD_SECRET", SECRET_KEY)
DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() == "true"
ZARVON_SANDBOX_MODE = os.environ.get("ZARVON_SANDBOX_MODE", "True").lower() == "true"

# Payment Gateways & External Bureau Adapters (Sandbox fallback when ZARVON_SANDBOX_MODE=True)
CLICK_SERVICE_ID = os.environ.get("CLICK_SERVICE_ID", "38491" if ZARVON_SANDBOX_MODE else "")
CLICK_MERCHANT_ID = os.environ.get("CLICK_MERCHANT_ID", "24810" if ZARVON_SANDBOX_MODE else "")
CLICK_MERCHANT_USER_ID = os.environ.get("CLICK_MERCHANT_USER_ID", "10042" if ZARVON_SANDBOX_MODE else "")
CLICK_SECRET_KEY = os.environ.get("CLICK_SECRET_KEY", "zarvon-click-sandbox-secret" if ZARVON_SANDBOX_MODE else "")
PAYME_MERCHANT_ID = os.environ.get("PAYME_MERCHANT_ID", "65f9a8e10000000000000001" if ZARVON_SANDBOX_MODE else "")
PAYME_CASHBOX_KEY = (
    os.environ.get("PAYME_CASHBOX_KEY")
    or os.environ.get("PAYME_SECRET_KEY")
    or ("zarvon-payme-sandbox-key" if ZARVON_SANDBOX_MODE else "")
)
PAYME_SECRET_KEY = PAYME_CASHBOX_KEY
PAYNET_SERVICE_ID = os.environ.get("PAYNET_SERVICE_ID", "55012" if ZARVON_SANDBOX_MODE else "")
PAYNET_USERNAME = os.environ.get("PAYNET_USERNAME", "zarvon_paynet" if ZARVON_SANDBOX_MODE else "")
PAYNET_PASSWORD = os.environ.get("PAYNET_PASSWORD", "zarvon-paynet-sandbox-pass" if ZARVON_SANDBOX_MODE else "")
PAYNET_ALLOWED_IPS = os.environ.get("PAYNET_ALLOWED_IPS", "")
UZUM_SERVICE_ID = os.environ.get("UZUM_SERVICE_ID", "49210" if ZARVON_SANDBOX_MODE else "")
UZUM_SECRET_KEY = os.environ.get("UZUM_SECRET_KEY", "zarvon-uzum-sandbox-secret" if ZARVON_SANDBOX_MODE else "")
ESKIZ_EMAIL = os.environ.get("ESKIZ_EMAIL", "")
ESKIZ_PASSWORD = os.environ.get("ESKIZ_PASSWORD", "")
ESKIZ_FROM = os.environ.get("ESKIZ_FROM", "4546")
PLAYMOBILE_URL = os.environ.get("PLAYMOBILE_URL", "")
PLAYMOBILE_USERNAME = os.environ.get("PLAYMOBILE_USERNAME", "")
PLAYMOBILE_PASSWORD = os.environ.get("PLAYMOBILE_PASSWORD", "")
KATM_API_URL = os.environ.get("KATM_API_URL", "")
MIB_API_URL = os.environ.get("MIB_API_URL", "")

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,*").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.accounts",
    "apps.governance",
    "apps.sellers",
    "apps.catalog",
    "apps.imports",
    "apps.inventory",
    "apps.commerce",
    "apps.finance",
    "apps.risk_collections",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.middleware.CorrelationAndSecurityMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# PostgreSQL in staging/production via DATABASE_URL; SQLite zero-config fallback for local dev
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

AUTH_USER_MODEL = "accounts.User"

# Strong password hashing (BCrypt installed; PBKDF2 fallback)
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "uz"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Separate public product media from private KYC/contracts storage (Section 12 & 31.2)
MEDIA_URL = "/media-public/"
MEDIA_ROOT = BASE_DIR / "media_public"
PRIVATE_MEDIA_ROOT = BASE_DIR / "media_private"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 8  # 8 hours

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000,https://*.onrender.com",
    ).split(",")
    if o.strip()
]
_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
if _render_host:
    CSRF_TRUSTED_ORIGINS.append(f"https://{_render_host}")

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 24,
    "EXCEPTION_HANDLER": "config.exceptions.zarvon_exception_handler",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

# External catalog API SSRF allowlist (Section 6.2)
EXTERNAL_CATALOG_ALLOWLIST = [
    "api.sandbox-erp.uz",
    "catalog-demo.zarvon.uz",
    "localhost",
    "127.0.0.1",
]
