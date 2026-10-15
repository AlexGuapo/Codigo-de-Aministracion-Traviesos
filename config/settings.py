"""Configuración de SARRCA.

Todo lo que cambia entre máquinas viene de variables de entorno (`.env`, ver `.env.example`).
Los límites de la norma NO van aquí: están en la tabla `parametro`, con su vigencia.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _cargar_env(archivo: Path) -> None:
    """Lee el `.env` si existe, sin pisar lo que ya venga en el entorno (Docker gana)."""
    if not archivo.exists():
        return
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        nombre, valor = linea.split("=", 1)
        os.environ.setdefault(nombre.strip(), valor.strip())


_cargar_env(BASE_DIR / ".env")


def _bool(nombre: str, por_omision: bool = False) -> bool:
    valor = os.environ.get(nombre)
    if valor is None:
        return por_omision
    return valor.strip().lower() in ("1", "true", "si", "sí")


def _lista(nombre: str, por_omision: str) -> list[str]:
    return [v.strip() for v in os.environ.get(nombre, por_omision).split(",") if v.strip()]


PRODUCCION = _bool("SARRCA_PRODUCCION")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if PRODUCCION:
        raise RuntimeError("Falta la variable DJANGO_SECRET_KEY.")
    SECRET_KEY = "solo-para-desarrollo-no-usar-en-produccion"

DEBUG = _bool("DJANGO_DEBUG") and not PRODUCCION
ALLOWED_HOSTS = _lista("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "cuentas",
    "sensores",
    "recepcion",
    "lecturas",
    "calculo",
    "reportes",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "cuentas.middleware.SesionPorInactividad",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

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
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("SARRCA_DB_NOMBRE", "sarrca"),
        "USER": os.environ.get("SARRCA_DB_USUARIO", "sarrca"),
        "PASSWORD": os.environ.get("SARRCA_DB_CONTRASENA", ""),
        "HOST": os.environ.get("SARRCA_DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("SARRCA_DB_PUERTO", "5432"),
        "OPTIONS": {"connect_timeout": 10},
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Todo en hora local. Con USE_TZ = False, Django abre cada conexión con la zona de TIME_ZONE y el
# código trabaja con fechas sin zona. La única conversión desde UTC+8 está en el adaptador de
# EzData.
USE_TZ = False
TIME_ZONE = "America/Mexico_City"
LANGUAGE_CODE = "es-mx"
USE_I18N = True

# Cuentas y acceso
AUTH_USER_MODEL = "cuentas.Cuenta"
AUTHENTICATION_BACKENDS = ["cuentas.backends.CuentaBackend"]
LOGIN_URL = "/cuentas/entrar/"
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
]
SARRCA_MAX_INTENTOS_FALLIDOS = 5
SARRCA_VENTANA_INTENTOS_MIN = 15
SARRCA_PAUSA_ACCESO_MIN = 15
SARRCA_INACTIVIDAD_MAX_SEG = 2 * 60 * 60
# Proxies de confianza delante de la web (Caddy = 1). Con 0 se usa la IP de la conexión.
SARRCA_PROXIES_CONFIABLES = int(os.environ.get("SARRCA_PROXIES_CONFIABLES", "0"))

# Las 2 h las decide el middleware; la cookie vive más, solo como margen.
SESSION_COOKIE_AGE = 24 * 60 * 60
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = PRODUCCION
CSRF_COOKIE_SECURE = PRODUCCION
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if PRODUCCION else None
SECURE_HSTS_SECONDS = 31536000 if PRODUCCION else 0

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Logs a la salida estándar. Nunca deben llevar la MAC, el token ni la dirección consultada a
# EzData.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "estandar": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "consola": {"class": "logging.StreamHandler", "formatter": "estandar"},
    },
    "root": {"handlers": ["consola"], "level": os.environ.get("SARRCA_NIVEL_LOG", "INFO")},
}
