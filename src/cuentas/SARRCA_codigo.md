# SARRCA · Inicio de sesión y cuenta de Administrador al instalar

Todo el código del proyecto en un solo archivo. Cada bloque lleva su ruta: crea el archivo con ese nombre y pega el contenido. Los archivos vacíos (`__init__.py`) también se necesitan.

## 1. Preparar

```bash
mkdir sarrca && cd sarrca
python -m venv .venv && source .venv/bin/activate   # en Windows: .venv\Scripts\activate
# crear los archivos de la sección 3 (o usar el script de la sección 2)
pip install -r requirements.txt
```

## 2. Crear todos los archivos de una vez (opcional)

Guarda este documento como `SARRCA_codigo.md` y, **en la carpeta donde quieres el proyecto**, ejecuta:

```bash
python - <<'PY'
import re, pathlib
texto = pathlib.Path('SARRCA_codigo.md').read_text(encoding='utf-8')
for ruta, cuerpo in re.findall(r'^### `([^`]+)`\n\n````[^\n]*\n(.*?)````\n', texto, re.S | re.M):
    p = pathlib.Path(ruta); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(cuerpo, encoding='utf-8')
PY
```

## 3. Archivos

### `requirements.txt`

````text
Django>=5.2,<5.3
psycopg[binary]>=3.2
gunicorn>=23.0
# Calidad (ADR: pytest, ruff)
pytest>=8
pytest-django>=4.9
ruff>=0.6
````

### `pytest.ini`

````ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings_test
python_files = tests.py test_*.py
````

### `.gitignore`

````text
__pycache__/
*.pyc
.env
.venv/
*.sqlite3
db.sqlite3
.pytest_cache/
.ruff_cache/
````

### `.env.example`

````bash
# Copiar a .env en el servidor. El .env real NUNCA se sube al repositorio.
DJANGO_SECRET_KEY=cambiar-por-una-clave-larga-y-aleatoria
DJANGO_ALLOWED_HOSTS=sarrca.example.org
SARRCA_PRODUCCION=1
# Cuántos proxies hay delante de la web (Caddy = 1)
SARRCA_PROXIES_CONFIABLES=1

SARRCA_DB_NOMBRE=sarrca
SARRCA_DB_USUARIO_APP=sarrca_app
SARRCA_DB_CONTRASENA_APP=cambiar
SARRCA_DB_HOST=db
SARRCA_DB_PUERTO=5432

# La contraseña de la cuenta de Administrador NO va aquí: crear_admin la pide
# por teclado (o por la variable SARRCA_ADMIN_CONTRASENA solo durante ese comando).
````

### `manage.py`

````python
#!/usr/bin/env python
"""Utilidad de línea de comandos de Django para SARRCA."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
````

### `config/__init__.py`

````python
````

### `config/settings.py`

````python
"""Configuración de SARRCA.

Todo lo secreto viene de variables de entorno (ADR, «Responsabilidades
transversales»); nada de eso se guarda en el repositorio.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(nombre, por_omision=False):
    return os.environ.get(nombre, str(por_omision)).strip().lower() in ("1", "true", "si", "sí")


SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]  # sin valor por omisión a propósito
PRODUCCION = _bool("SARRCA_PRODUCCION")
DEBUG = _bool("DJANGO_DEBUG") and not PRODUCCION
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "apps.bitacora",
    "apps.cuentas",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.cuentas.middleware.SesionPorInactividad",
    "django.contrib.messages.middleware.MessageMiddleware",
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
    },
]

# PostgreSQL 18 (ADR, pila tecnológica). Las pruebas usan settings_test.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("SARRCA_DB_NOMBRE", "sarrca"),
        "USER": os.environ.get("SARRCA_DB_USUARIO_APP", "sarrca_app"),
        "PASSWORD": os.environ.get("SARRCA_DB_CONTRASENA_APP", ""),
        "HOST": os.environ.get("SARRCA_DB_HOST", "db"),
        "PORT": os.environ.get("SARRCA_DB_PUERTO", "5432"),
    }
}

# --- Hora local (ADR «Hora UTC+8 a local», RL-14): sin zona en la base ---
USE_TZ = False
TIME_ZONE = "America/Mexico_City"
LANGUAGE_CODE = "es-mx"
USE_I18N = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "static/"

# --- Acceso y sesión (ADR «Acceso y sesión», D-88) ---
AUTH_USER_MODEL = "cuentas.Cuenta"
AUTHENTICATION_BACKENDS = ["apps.cuentas.backends.CuentaBackend"]
LOGIN_URL = "cuentas:acceso"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
]

SARRCA_MAX_INTENTOS_FALLIDOS = 5            # intentos fallidos...
SARRCA_VENTANA_INTENTOS_MIN = 15            # ...en estos minutos...
SARRCA_PAUSA_ACCESO_MIN = 15                # ...provocan una pausa de estos minutos
SARRCA_INACTIVIDAD_MAX_SEG = 2 * 60 * 60    # la sesión se cierra tras 2 h sin actividad
# Las 2 h las decide el middleware SesionPorInactividad (así quedan en la bitácora
# y HTMX recibe su redirección). La cookie vive más, solo como margen: si Django
# la venciera a las 2 h, la sesión desaparecería sin que nadie lo registrara.
SESSION_COOKIE_AGE = 24 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = False          # la renovación la decide el middleware
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# Cuántos proxies de confianza hay delante de la web (en producción, Caddy = 1).
# Con 0 se usa la dirección de la conexión. Sin esto, todas las personas
# parecerían venir de la IP de Caddy y una pausa bloquearía a todos.
SARRCA_PROXIES_CONFIABLES = int(os.environ.get("SARRCA_PROXIES_CONFIABLES", "1" if PRODUCCION else "0"))

if PRODUCCION:  # HTTPS siempre (RNF-SEG-06)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = False  # Caddy ya redirige de 80 a 443
    SECURE_HSTS_SECONDS = 31536000

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"consola": {"class": "logging.StreamHandler", "formatter": "std"}},
    "root": {"handlers": ["consola"], "level": "INFO"},
}
````

### `config/settings_test.py`

````python
"""Configuración para las pruebas: SQLite en memoria y hashing rápido."""
import os

os.environ.setdefault("DJANGO_SECRET_KEY", "clave-solo-para-pruebas")

from .settings import *  # noqa: E402,F401,F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
ALLOWED_HOSTS = ["testserver", "localhost"]
````

### `config/urls.py`

````python
from django.urls import include, path

urlpatterns = [
    path("", include("apps.cuentas.urls")),
]
````

### `config/wsgi.py`

````python
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()
````

### `apps/bitacora/__init__.py`

````python
````

### `apps/bitacora/apps.py`

````python
from django.apps import AppConfig


class BitacoraConfig(AppConfig):
    name = "apps.bitacora"
    label = "bitacora"
    verbose_name = "Bitácora de auditoría"
````

### `apps/bitacora/migrations/0001_initial.py`

````python
# Generated by Django 5.2.19.dev20261009120732 on 2026-10-14 00:24

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EntradaBitacora",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "fecha_hora",
                    models.DateTimeField(
                        default=django.utils.timezone.now, editable=False
                    ),
                ),
                (
                    "tipo_operacion",
                    models.CharField(
                        choices=[
                            ("inicio_sesion", "Inicio de sesión"),
                            ("inicio_sesion_fallido", "Inicio de sesión fallido"),
                            ("acceso_pausado", "Intento durante una pausa de acceso"),
                            ("pausa_activada", "Pausa de acceso activada"),
                            ("pausa_levantada", "Pausa de acceso levantada"),
                            ("cierre_sesion", "Cierre de sesión"),
                            ("sesion_expirada", "Sesión cerrada por inactividad"),
                            ("acceso_negado", "Acceso negado por rol"),
                            (
                                "cuenta_admin_creada",
                                "Cuenta de Administrador creada al instalar",
                            ),
                        ],
                        max_length=40,
                    ),
                ),
                ("objeto_afectado", models.CharField(blank=True, max_length=200)),
                ("valor_anterior", models.TextField(blank=True)),
                ("valor_nuevo", models.TextField(blank=True)),
                ("motivo", models.TextField(blank=True)),
                (
                    "resultado",
                    models.CharField(
                        choices=[
                            ("exitoso", "Exitoso"),
                            ("negado", "Negado"),
                            ("fallido", "Fallido"),
                        ],
                        max_length=10,
                    ),
                ),
                ("detalle", models.TextField(blank=True)),
                (
                    "cuenta",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "entrada de bitácora",
                "verbose_name_plural": "entradas de bitácora",
                "ordering": ["-fecha_hora", "-id"],
            },
        ),
    ]
````

### `apps/bitacora/migrations/__init__.py`

````python
````

### `apps/bitacora/models.py`

````python
"""Bitácora de auditoría (HU-019, RES-03, RL-09, PE-13).

Solo crece: nadie edita ni borra una entrada, tampoco el Administrador. Aquí
se impide desde el ORM; la defensa de fondo es el rol de PostgreSQL de la
aplicación, sin UPDATE ni DELETE sobre esta tabla (ADR «Solo inserción
impuesto desde la base»), que crean las migraciones del ADR sección 14.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class BitacoraInmutable(Exception):
    """Se intentó editar o borrar la bitácora."""


class EntradaQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise BitacoraInmutable("La bitácora no se edita.")

    def delete(self):
        raise BitacoraInmutable("La bitácora no se borra.")

    def bulk_update(self, *args, **kwargs):
        raise BitacoraInmutable("La bitácora no se edita.")


class TipoOperacion(models.TextChoices):
    INICIO_SESION = "inicio_sesion", "Inicio de sesión"
    INICIO_SESION_FALLIDO = "inicio_sesion_fallido", "Inicio de sesión fallido"
    ACCESO_PAUSADO = "acceso_pausado", "Intento durante una pausa de acceso"
    PAUSA_ACTIVADA = "pausa_activada", "Pausa de acceso activada"
    PAUSA_LEVANTADA = "pausa_levantada", "Pausa de acceso levantada"
    CIERRE_SESION = "cierre_sesion", "Cierre de sesión"
    SESION_EXPIRADA = "sesion_expirada", "Sesión cerrada por inactividad"
    ACCESO_NEGADO = "acceso_negado", "Acceso negado por rol"
    CUENTA_ADMIN_CREADA = "cuenta_admin_creada", "Cuenta de Administrador creada al instalar"


class Resultado(models.TextChoices):
    EXITOSO = "exitoso", "Exitoso"
    NEGADO = "negado", "Negado"
    FALLIDO = "fallido", "Fallido"


class EntradaBitacora(models.Model):
    # Nulo cuando lo hizo el sistema o quien intentó entrar no tiene cuenta.
    cuenta = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    fecha_hora = models.DateTimeField(default=timezone.now, editable=False)
    tipo_operacion = models.CharField(max_length=40, choices=TipoOperacion.choices)
    objeto_afectado = models.CharField(max_length=200, blank=True)
    valor_anterior = models.TextField(blank=True)
    valor_nuevo = models.TextField(blank=True)
    motivo = models.TextField(blank=True)
    resultado = models.CharField(max_length=10, choices=Resultado.choices)
    detalle = models.TextField(blank=True)  # p. ej. la dirección IP; nunca contraseñas ni correos tecleados

    objects = EntradaQuerySet.as_manager()

    class Meta:
        ordering = ["-fecha_hora", "-id"]
        verbose_name = "entrada de bitácora"
        verbose_name_plural = "entradas de bitácora"

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise BitacoraInmutable("La bitácora no se edita.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise BitacoraInmutable("La bitácora no se borra.")

    def __str__(self):
        return f"{self.fecha_hora:%d/%m/%Y %H:%M:%S} {self.tipo_operacion} ({self.resultado})"
````

### `apps/bitacora/services.py`

````python
"""Único punto de escritura de la bitácora (ADR: «servicio común»)."""
from .models import EntradaBitacora, Resultado, TipoOperacion

__all__ = ["registrar", "Resultado", "TipoOperacion"]


def registrar(
    tipo_operacion,
    resultado,
    cuenta=None,
    objeto_afectado="",
    valor_anterior="",
    valor_nuevo="",
    motivo="",
    detalle="",
):
    return EntradaBitacora.objects.create(
        cuenta=cuenta,
        tipo_operacion=tipo_operacion,
        resultado=resultado,
        objeto_afectado=objeto_afectado,
        valor_anterior=valor_anterior,
        valor_nuevo=valor_nuevo,
        motivo=motivo,
        detalle=detalle,
    )
````

### `apps/bitacora/tests/__init__.py`

````python
````

### `apps/bitacora/tests/test_bitacora.py`

````python
"""La bitácora solo crece (HU-019, RES-03, RL-09, PE-13)."""
from django.test import TestCase

from apps.bitacora import services
from apps.bitacora.models import BitacoraInmutable, EntradaBitacora, Resultado, TipoOperacion


class BitacoraInmutableTests(TestCase):
    def setUp(self):
        self.entrada = services.registrar(TipoOperacion.INICIO_SESION, Resultado.EXITOSO, objeto_afectado="x")

    def test_registrar_crea_una_entrada(self):
        self.assertEqual(EntradaBitacora.objects.count(), 1)

    def test_no_se_edita_una_entrada(self):
        self.entrada.motivo = "cambiado"
        with self.assertRaises(BitacoraInmutable):
            self.entrada.save()

    def test_no_se_borra_una_entrada(self):
        with self.assertRaises(BitacoraInmutable):
            self.entrada.delete()

    def test_no_se_edita_ni_se_borra_por_consulta(self):
        with self.assertRaises(BitacoraInmutable):
            EntradaBitacora.objects.update(motivo="cambiado")
        with self.assertRaises(BitacoraInmutable):
            EntradaBitacora.objects.all().delete()
        self.assertEqual(EntradaBitacora.objects.get().motivo, "")
````

### `apps/cuentas/__init__.py`

````python
````

### `apps/cuentas/apps.py`

````python
from django.apps import AppConfig


class CuentasConfig(AppConfig):
    name = "apps.cuentas"
    label = "cuentas"
    verbose_name = "Cuentas y acceso"
````

### `apps/cuentas/backends.py`

````python
from django.contrib.auth.backends import ModelBackend


class CuentaBackend(ModelBackend):
    """Autentica por correo y contraseña.

    Hereda de ModelBackend, que ya iguala el tiempo de respuesta cuando el
    correo no existe (así no se puede distinguir por la demora) y que rechaza
    a las cuentas cuyo is_active es falso: dadas de baja, bloqueadas, suprimidas
    o por activar (HU-003, criterio 3).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is not None:
            username = username.strip().lower()
        return super().authenticate(request, username=username, password=password, **kwargs)
````

### `apps/cuentas/decorators.py`

````python
from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden

from . import services


def rol_requerido(*roles):
    """Permiso por rol en cada vista (ADR, RNF-SEG-07).

    Sin sesión: lleva al inicio de sesión. Con un rol que no corresponde: se
    niega (403) y el intento queda en la bitácora. La revisión se repite en
    cada servicio que escribe; esta es la primera de las dos.
    """

    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
            if request.user.rol not in roles:
                services.registrar_acceso_negado(request, f"vista {request.path}")
                return HttpResponseForbidden("No tiene permiso para ver esta página.")
            return vista(request, *args, **kwargs)

        return envoltura

    return decorador
````

### `apps/cuentas/forms.py`

````python
from django import forms


class AccesoForm(forms.Form):
    correo = forms.CharField(label="Correo electrónico", max_length=254, widget=forms.EmailInput(attrs={"autocomplete": "username", "autofocus": True}))
    contrasena = forms.CharField(label="Contraseña", max_length=128, strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
````

### `apps/cuentas/management/__init__.py`

````python
````

### `apps/cuentas/management/commands/__init__.py`

````python
````

### `apps/cuentas/management/commands/crear_admin.py`

````python
"""RT-010 · Crea la cuenta de Administrador al instalar el sistema.

Se corre una vez, después de las migraciones y de cargar los parámetros y el
catálogo de colonias (ADR «Despliegue, operación y respaldo»):

    python manage.py crear_admin --correo doctora@ejemplo.mx --nombre "Nombre Apellido"

La contraseña nunca va en la línea de comandos (quedaría en el historial del
shell y en la lista de procesos): se pide por teclado, dos veces, o se toma de
la variable SARRCA_ADMIN_CONTRASENA solo para esta ejecución.

Es seguro repetirlo: si ya hay una cuenta de Administrador no cambia nada.
"""
import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.cuentas import services


class Command(BaseCommand):
    help = "Crea la única cuenta de Administrador (se ejecuta al instalar)."

    def add_arguments(self, parser):
        parser.add_argument("--correo", default=os.environ.get("SARRCA_ADMIN_CORREO"))
        parser.add_argument("--nombre", default=os.environ.get("SARRCA_ADMIN_NOMBRE", "Administrador"))

    def handle(self, *args, **opciones):
        correo = opciones["correo"]
        if not correo:
            raise CommandError("Falta el correo: use --correo o la variable SARRCA_ADMIN_CORREO.")

        contrasena = os.environ.get("SARRCA_ADMIN_CONTRASENA")
        if not contrasena:
            contrasena = getpass.getpass("Contraseña de la cuenta de Administrador: ")
            if contrasena != getpass.getpass("Repita la contraseña: "):
                raise CommandError("Las contraseñas no coinciden.")

        try:
            validate_password(contrasena)
            cuenta = services.crear_administrador(correo, opciones["nombre"], contrasena)
        except services.AdministradorYaExiste:
            self.stdout.write("Ya existe una cuenta de Administrador; no se cambió nada.")
            return
        except ValidationError as error:
            raise CommandError("; ".join(error.messages))

        self.stdout.write(self.style.SUCCESS(f"Cuenta de Administrador creada: {cuenta.correo}"))
````

### `apps/cuentas/management/commands/desbloquear.py`

````python
"""Levanta una pausa de acceso (ADR «Acceso y sesión»).

    python manage.py desbloquear correo@ejemplo.mx [--ip 203.0.113.7]

Sin --ip levanta las pausas de esa cuenta desde cualquier dirección. Queda en la bitácora.
"""
from django.core.management.base import BaseCommand

from apps.cuentas import services


class Command(BaseCommand):
    help = "Levanta la pausa de acceso de una cuenta."

    def add_arguments(self, parser):
        parser.add_argument("correo")
        parser.add_argument("--ip", default=None)

    def handle(self, *args, **opciones):
        levantadas = services.desbloquear(opciones["correo"], opciones["ip"])
        self.stdout.write(f"Pausas levantadas: {levantadas}")
````

### `apps/cuentas/middleware.py`

````python
"""Sesión por inactividad (D-88, ADR «Acceso y sesión»).

La sesión se cierra tras 2 h sin actividad. Las consultas automáticas de HTMX
(el estado de la verificación del alta, la actualización del panel) no cuentan
como actividad: de lo contrario, una pestaña abierta mantendría viva la sesión
para siempre. Esas consultas deben llevar la cabecera `X-Consulta-Automatica: 1`
(en HTMX: hx-headers='{"X-Consulta-Automatica": "1"}').
"""
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from . import services

CABECERA_AUTOMATICA = "X-Consulta-Automatica"


def es_consulta_automatica(request):
    return request.headers.get(CABECERA_AUTOMATICA) == "1"


class SesionPorInactividad:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            ahora = timezone.now().timestamp()
            ultima = request.session.get(services.CLAVE_ULTIMA_ACTIVIDAD)
            # Una sesión sin marca (p. ej. anterior a este middleware) se trata como vencida.
            if ultima is None or ahora - ultima > settings.SARRCA_INACTIVIDAD_MAX_SEG:
                services.cerrar_sesion(request, expirada=True)
                destino = reverse(settings.LOGIN_URL)
                if request.headers.get("HX-Request"):
                    return HttpResponse(status=401, headers={"HX-Redirect": destino})
                return redirect(destino)
            if not es_consulta_automatica(request):
                request.session[services.CLAVE_ULTIMA_ACTIVIDAD] = ahora
        return self.get_response(request)
````

### `apps/cuentas/migrations/0001_initial.py`

````python
# Generated by Django 5.2.19.dev20261009120732 on 2026-10-14 00:24

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Cuenta",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("password", models.CharField(max_length=128, verbose_name="password")),
                (
                    "last_login",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="last login"
                    ),
                ),
                ("correo", models.EmailField(max_length=254, unique=True)),
                ("nombre", models.CharField(max_length=150)),
                (
                    "rol",
                    models.CharField(
                        choices=[
                            ("administrador", "Administrador"),
                            ("vecino_con_sensor", "Vecino con sensor"),
                            ("vecino_sin_sensor", "Vecino sin sensor"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "estado",
                    models.CharField(
                        choices=[
                            ("por_activar", "Por activar"),
                            ("por_validar", "Por validar"),
                            ("validada", "Validada"),
                            ("dada_de_baja", "Dada de baja"),
                            ("bloqueada", "Bloqueada"),
                            ("suprimida", "Suprimida"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "origen",
                    models.CharField(
                        choices=[
                            ("registro_propio", "Registro propio"),
                            ("creada_por_admin", "Creada por el Administrador"),
                            ("instalacion", "Creada al instalar el sistema"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "fecha_creacion",
                    models.DateTimeField(
                        default=django.utils.timezone.now, editable=False
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("rol", "administrador")),
                        fields=("rol",),
                        name="una_sola_cuenta_administrador",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="IntentoFallido",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("correo", models.CharField(max_length=254)),
                ("ip", models.GenericIPAddressField()),
                ("fecha_hora", models.DateTimeField(default=django.utils.timezone.now)),
                ("vigente", models.BooleanField(default=True)),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["correo", "ip", "fecha_hora"],
                        name="cuentas_int_correo_6bdaf2_idx",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="PausaAcceso",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("correo", models.CharField(max_length=254)),
                ("ip", models.GenericIPAddressField()),
                ("creada", models.DateTimeField(default=django.utils.timezone.now)),
                ("hasta", models.DateTimeField()),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["correo", "ip", "hasta"],
                        name="cuentas_pau_correo_b790ee_idx",
                    )
                ],
            },
        ),
    ]
````

### `apps/cuentas/migrations/__init__.py`

````python
````

### `apps/cuentas/models.py`

````python
"""Cuentas, roles y control de intentos de acceso (SRS 3.5 y 3.6; ADR «Acceso y sesión»)."""
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Rol(models.TextChoices):
    ADMINISTRADOR = "administrador", "Administrador"
    VECINO_CON_SENSOR = "vecino_con_sensor", "Vecino con sensor"
    VECINO_SIN_SENSOR = "vecino_sin_sensor", "Vecino sin sensor"


class Estado(models.TextChoices):
    POR_ACTIVAR = "por_activar", "Por activar"        # invitada, aún no entra (PE-11)
    POR_VALIDAR = "por_validar", "Por validar"        # vecino sin sensor recién registrado (PE-10)
    VALIDADA = "validada", "Validada"
    DADA_DE_BAJA = "dada_de_baja", "Dada de baja"     # PE-12
    BLOQUEADA = "bloqueada", "Bloqueada"              # por cancelación de datos (D-69)
    SUPRIMIDA = "suprimida", "Suprimida"


class Origen(models.TextChoices):
    REGISTRO_PROPIO = "registro_propio", "Registro propio"
    CREADA_POR_ADMIN = "creada_por_admin", "Creada por el Administrador"
    INSTALACION = "instalacion", "Creada al instalar el sistema"


# Estados con los que se puede iniciar sesión. Una cuenta por validar entra para
# consultar las alertas de su colonia, pero no puede reportar (PE-10).
ESTADOS_QUE_ENTRAN = (Estado.POR_VALIDAR, Estado.VALIDADA)


class CuentaManager(BaseUserManager):
    use_in_migrations = False

    def get_by_natural_key(self, correo):
        return self.get(**{self.model.USERNAME_FIELD: (correo or "").strip().lower()})


class Cuenta(AbstractBaseUser):
    correo = models.EmailField(unique=True)
    nombre = models.CharField(max_length=150)
    rol = models.CharField(max_length=20, choices=Rol.choices)
    estado = models.CharField(max_length=20, choices=Estado.choices)
    origen = models.CharField(max_length=20, choices=Origen.choices)
    fecha_creacion = models.DateTimeField(default=timezone.now, editable=False)

    objects = CuentaManager()

    USERNAME_FIELD = "correo"
    REQUIRED_FIELDS = ["nombre"]

    class Meta:
        constraints = [
            # PE-01 / SUP-08 / RNF-SEG-09: nunca puede haber más de una cuenta de
            # Administrador. Lo impide la base, no solo el código.
            models.UniqueConstraint(
                fields=["rol"],
                condition=Q(rol="administrador"),
                name="una_sola_cuenta_administrador",
            ),
        ]

    # --- lo que Django necesita de un modelo de usuario ---
    @property
    def is_active(self):
        return self.estado in ESTADOS_QUE_ENTRAN

    # --- reglas del dominio ---
    @property
    def es_administrador(self):
        return self.rol == Rol.ADMINISTRADOR

    def clean(self):
        super().clean()
        if self.correo:
            self.correo = self.correo.strip().lower()
        if self.es_administrador and self.estado != Estado.VALIDADA:
            raise ValidationError("La cuenta de Administrador siempre está validada y no se da de baja (PE-01).")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.correo} ({self.get_rol_display()})"


class IntentoFallido(models.Model):
    """Un inicio de sesión fallido, contado por cuenta y por dirección IP (D-88, auditoría E-20).

    Se cuenta el par (correo, IP) y no solo el correo, para que nadie pueda
    dejar bloqueada a la única Administradora desde otra red. El correo es el
    texto normalizado que se tecleó, exista o no la cuenta: así la pausa se
    comporta igual y no revela qué correos están registrados (IU-11).
    """

    correo = models.CharField(max_length=254)
    ip = models.GenericIPAddressField()
    fecha_hora = models.DateTimeField(default=timezone.now)
    vigente = models.BooleanField(default=True)  # deja de contar al activarse una pausa o al desbloquear

    class Meta:
        indexes = [models.Index(fields=["correo", "ip", "fecha_hora"])]


class PausaAcceso(models.Model):
    correo = models.CharField(max_length=254)
    ip = models.GenericIPAddressField()
    creada = models.DateTimeField(default=timezone.now)
    hasta = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=["correo", "ip", "hasta"])]
````

### `apps/cuentas/services.py`

````python
"""Servicios de cuentas: único punto de escritura (ADR sección 2).

Cada servicio deja su entrada en la bitácora. Las vistas y los comandos
llaman a estos servicios; no escriben por su cuenta.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.bitacora import services as bitacora
from apps.bitacora.models import Resultado, TipoOperacion

from .models import Cuenta, Estado, IntentoFallido, Origen, PausaAcceso, Rol

CLAVE_ULTIMA_ACTIVIDAD = "sarrca_ultima_actividad"


class AdministradorYaExiste(Exception):
    """Ya hay una cuenta de Administrador: solo hay una (PE-01)."""


class ResultadoAcceso:
    ENTRO = "entro"
    DATOS_INCORRECTOS = "datos_incorrectos"
    PAUSADO = "pausado"


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def normalizar_correo(correo):
    return (correo or "").strip().lower()


def obtener_ip(request):
    """Dirección del cliente.

    Detrás de Caddy, REMOTE_ADDR es la de Caddy: todos parecerían la misma
    persona. Con SARRCA_PROXIES_CONFIABLES = n se toma la n-ésima entrada de
    X-Forwarded-For contando desde la derecha (la que agregó nuestro proxy);
    lo que el cliente escriba a la izquierda no se usa.
    """
    n = settings.SARRCA_PROXIES_CONFIABLES
    if n > 0:
        reenviadas = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
        if len(reenviadas) >= n:
            return reenviadas[-n]
    return request.META.get("REMOTE_ADDR") or "0.0.0.0"


def destino_inicial(cuenta):
    """Pantalla inicial por rol (D-88): Administrador al panel; vecinos al portal."""
    return reverse("cuentas:panel_admin" if cuenta.rol == Rol.ADMINISTRADOR else "cuentas:inicio")


# --------------------------------------------------------------------------
# Pausa por intentos fallidos
# --------------------------------------------------------------------------
def pausa_activa(correo, ip):
    return PausaAcceso.objects.filter(correo=correo, ip=ip, hasta__gt=timezone.now()).order_by("-hasta").first()


def _registrar_fallo(correo, ip):
    """Cuenta el fallo; devuelve True si con él se activa la pausa."""
    ahora = timezone.now()
    IntentoFallido.objects.create(correo=correo, ip=ip, fecha_hora=ahora)
    ventana = ahora - timedelta(minutes=settings.SARRCA_VENTANA_INTENTOS_MIN)
    vigentes = IntentoFallido.objects.filter(correo=correo, ip=ip, vigente=True, fecha_hora__gte=ventana)
    if vigentes.count() < settings.SARRCA_MAX_INTENTOS_FALLIDOS:
        return False
    PausaAcceso.objects.create(
        correo=correo, ip=ip, creada=ahora, hasta=ahora + timedelta(minutes=settings.SARRCA_PAUSA_ACCESO_MIN)
    )
    # Estos fallos ya se "gastaron": al terminar la pausa se empieza de cero.
    IntentoFallido.objects.filter(correo=correo, ip=ip, vigente=True).update(vigente=False)
    return True


@transaction.atomic
def desbloquear(correo, ip=None):
    """Levanta las pausas y reinicia el conteo de una cuenta (comando `desbloquear`)."""
    correo = normalizar_correo(correo)
    ahora = timezone.now()
    pausas = PausaAcceso.objects.filter(correo=correo, hasta__gt=ahora)
    intentos = IntentoFallido.objects.filter(correo=correo, vigente=True)
    if ip:
        pausas, intentos = pausas.filter(ip=ip), intentos.filter(ip=ip)
    levantadas = pausas.update(hasta=ahora)
    intentos.update(vigente=False)
    cuenta = Cuenta.objects.filter(correo=correo).first()
    bitacora.registrar(
        TipoOperacion.PAUSA_LEVANTADA,
        Resultado.EXITOSO,
        cuenta=cuenta,
        objeto_afectado="cuenta" if cuenta else "correo sin cuenta",
        detalle=f"pausas levantadas={levantadas}" + (f"; ip={ip}" if ip else ""),
    )
    return levantadas


# --------------------------------------------------------------------------
# Inicio y cierre de sesión
# --------------------------------------------------------------------------
def iniciar_sesion(request, correo, contrasena):
    """HU-003. Devuelve (ResultadoAcceso, cuenta o None).

    - Mismo resultado y mismo mensaje para correo inexistente, contraseña
      incorrecta y cuenta que no puede entrar (IU-11, HU-003 criterios 2 y 3).
    - Durante una pausa se rechaza incluso la contraseña correcta y esos
      intentos no alargan la pausa (RNF-SEG-10).
    - Todo queda en la bitácora, sin guardar el correo tecleado ni la contraseña.
    """
    correo = normalizar_correo(correo)
    ip = obtener_ip(request)
    existente = Cuenta.objects.filter(correo=correo).first()

    if pausa_activa(correo, ip):
        bitacora.registrar(
            TipoOperacion.ACCESO_PAUSADO, Resultado.NEGADO, cuenta=existente,
            objeto_afectado="inicio de sesión", detalle=f"ip={ip}",
        )
        return ResultadoAcceso.PAUSADO, None

    cuenta = authenticate(request, username=correo, password=contrasena)
    if cuenta is None:
        with transaction.atomic():
            se_pauso = _registrar_fallo(correo, ip)
            bitacora.registrar(
                TipoOperacion.INICIO_SESION_FALLIDO, Resultado.NEGADO, cuenta=existente,
                objeto_afectado="inicio de sesión", detalle=f"ip={ip}",
            )
            if se_pauso:
                bitacora.registrar(
                    TipoOperacion.PAUSA_ACTIVADA, Resultado.EXITOSO, cuenta=existente,
                    objeto_afectado="inicio de sesión",
                    detalle=f"ip={ip}; minutos={settings.SARRCA_PAUSA_ACCESO_MIN}",
                )
        return (ResultadoAcceso.PAUSADO if se_pauso else ResultadoAcceso.DATOS_INCORRECTOS), None

    with transaction.atomic():
        login(request, cuenta)
        request.session[CLAVE_ULTIMA_ACTIVIDAD] = timezone.now().timestamp()
        IntentoFallido.objects.filter(correo=correo, ip=ip, vigente=True).update(vigente=False)
        bitacora.registrar(
            TipoOperacion.INICIO_SESION, Resultado.EXITOSO, cuenta=cuenta,
            objeto_afectado="inicio de sesión", detalle=f"ip={ip}",
        )
    return ResultadoAcceso.ENTRO, cuenta


def cerrar_sesion(request, expirada=False):
    cuenta = request.user if request.user.is_authenticated else None
    logout(request)
    bitacora.registrar(
        TipoOperacion.SESION_EXPIRADA if expirada else TipoOperacion.CIERRE_SESION,
        Resultado.EXITOSO, cuenta=cuenta, objeto_afectado="sesión", detalle=f"ip={obtener_ip(request)}",
    )


def registrar_acceso_negado(request, objeto):
    """RNF-SEG-08: todo intento negado queda en la bitácora con la cuenta, la operación y la hora."""
    bitacora.registrar(
        TipoOperacion.ACCESO_NEGADO, Resultado.NEGADO,
        cuenta=request.user if request.user.is_authenticated else None,
        objeto_afectado=objeto, detalle=f"ip={obtener_ip(request)}",
    )


# --------------------------------------------------------------------------
# Cuenta de Administrador al instalar (RT-010)
# --------------------------------------------------------------------------
@transaction.atomic
def crear_administrador(correo, nombre, contrasena):
    """Crea la única cuenta de Administrador. Solo la invoca el comando `crear_admin`.

    No existe ninguna vista ni servicio que registre, asigne o dé de baja ese
    rol (PE-01, SUP-08, RNF-SEG-09). Si ya hay una, no hace nada y avisa.
    """
    if Cuenta.objects.filter(rol=Rol.ADMINISTRADOR).exists():
        raise AdministradorYaExiste()
    correo = normalizar_correo(correo)
    validate_password(contrasena)  # al menos 8 caracteres (D-88)
    cuenta = Cuenta(
        correo=correo, nombre=nombre.strip(), rol=Rol.ADMINISTRADOR,
        estado=Estado.VALIDADA, origen=Origen.INSTALACION,
    )
    cuenta.set_password(contrasena)
    cuenta.full_clean(exclude=["password"])
    cuenta.save()
    bitacora.registrar(
        TipoOperacion.CUENTA_ADMIN_CREADA, Resultado.EXITOSO, cuenta=cuenta,
        objeto_afectado="cuenta de Administrador", detalle="creada por el comando crear_admin",
    )
    return cuenta
````

### `apps/cuentas/tests/__init__.py`

````python
````

### `apps/cuentas/tests/test_acceso.py`

````python
"""HU-003 · Iniciar sesión; RF-02 (D-88); RNF-SEG-07, -08 y -10."""
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.bitacora.models import EntradaBitacora, TipoOperacion
from apps.cuentas.models import Estado, IntentoFallido, PausaAcceso, Rol
from apps.cuentas.views import MENSAJE_DATOS_INCORRECTOS, MENSAJE_PAUSA

from .utiles import AHORA, CONTRASENA, ahora_es, crear_cuenta, mas

ACCESO = reverse("cuentas:acceso")


def entrar(client, correo, contrasena, **extra):
    return client.post(ACCESO, {"correo": correo, "contrasena": contrasena}, **extra)


class InicioDeSesionTests(TestCase):
    def test_criterio_1_administrador_entra_al_panel(self):
        crear_cuenta("doctora@ejemplo.mx", Rol.ADMINISTRADOR)
        r = entrar(self.client, "doctora@ejemplo.mx", CONTRASENA)
        self.assertRedirects(r, reverse("cuentas:panel_admin"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("cuentas:panel_admin")).status_code, 200)

    def test_vecinos_entran_al_inicio_del_portal(self):
        crear_cuenta("a@ejemplo.mx", Rol.VECINO_SIN_SENSOR)
        crear_cuenta("b@ejemplo.mx", Rol.VECINO_CON_SENSOR)
        for correo in ("a@ejemplo.mx", "b@ejemplo.mx"):
            r = entrar(self.client, correo, CONTRASENA)
            self.assertRedirects(r, reverse("cuentas:inicio"), fetch_redirect_response=False)
            self.client.post(reverse("cuentas:salir"))

    def test_correo_con_mayusculas_y_espacios_entra(self):
        crear_cuenta("doctora@ejemplo.mx", Rol.ADMINISTRADOR)
        r = entrar(self.client, "  Doctora@Ejemplo.MX ", CONTRASENA)
        self.assertEqual(r.status_code, 302)

    def test_criterio_2_mismo_mensaje_con_correo_o_contrasena_incorrectos(self):
        crear_cuenta("vecina@ejemplo.mx")
        malo_contrasena = entrar(self.client, "vecina@ejemplo.mx", "otra-contraseña")
        malo_correo = entrar(self.client, "nadie@ejemplo.mx", CONTRASENA)
        for r in (malo_contrasena, malo_correo):
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, MENSAJE_DATOS_INCORRECTOS)
        self.assertEqual(malo_contrasena.content.decode().count("Correo o contraseña"), 1)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_criterio_3_cuentas_que_no_pueden_entrar_reciben_el_mismo_mensaje(self):
        no_entran = [Estado.DADA_DE_BAJA, Estado.POR_ACTIVAR, Estado.BLOQUEADA, Estado.SUPRIMIDA]
        for i, estado in enumerate(no_entran):
            correo = f"c{i}@ejemplo.mx"
            crear_cuenta(correo, Rol.VECINO_SIN_SENSOR, estado)
            r = entrar(self.client, correo, CONTRASENA)
            self.assertContains(r, MENSAJE_DATOS_INCORRECTOS)
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_cuenta_por_validar_entra_para_consultar_alertas_pe10(self):
        crear_cuenta("p@ejemplo.mx", Rol.VECINO_SIN_SENSOR, Estado.POR_VALIDAR)
        self.assertEqual(entrar(self.client, "p@ejemplo.mx", CONTRASENA).status_code, 302)

    def test_la_contrasena_no_se_devuelve_en_la_pagina(self):
        crear_cuenta("vecina@ejemplo.mx")
        r = entrar(self.client, "vecina@ejemplo.mx", "secreto-que-no-debe-volver")
        self.assertNotContains(r, "secreto-que-no-debe-volver")

    def test_usuario_con_sesion_que_abre_el_acceso_va_a_su_pantalla(self):
        crear_cuenta("doctora@ejemplo.mx", Rol.ADMINISTRADOR)
        entrar(self.client, "doctora@ejemplo.mx", CONTRASENA)
        r = self.client.get(ACCESO)
        self.assertRedirects(r, reverse("cuentas:panel_admin"), fetch_redirect_response=False)

    def test_next_interno_se_respeta_y_externo_se_ignora(self):
        crear_cuenta("doctora@ejemplo.mx", Rol.ADMINISTRADOR)
        r = self.client.post(ACCESO + "?next=/panel/", {"correo": "doctora@ejemplo.mx", "contrasena": CONTRASENA})
        self.assertEqual(r["Location"], "/panel/")
        self.client.post(reverse("cuentas:salir"))
        r = self.client.post(
            ACCESO, {"correo": "doctora@ejemplo.mx", "contrasena": CONTRASENA, "next": "https://malo.example/"}
        )
        self.assertEqual(r["Location"], reverse("cuentas:panel_admin"))

    def test_salir_solo_por_post_y_queda_en_bitacora(self):
        crear_cuenta("vecina@ejemplo.mx")
        entrar(self.client, "vecina@ejemplo.mx", CONTRASENA)
        self.assertEqual(self.client.get(reverse("cuentas:salir")).status_code, 405)
        self.client.post(reverse("cuentas:salir"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(EntradaBitacora.objects.filter(tipo_operacion=TipoOperacion.CIERRE_SESION).exists())


class PausaPorIntentosTests(TestCase):
    def setUp(self):
        crear_cuenta("doctora@ejemplo.mx", Rol.ADMINISTRADOR)

    def fallar(self, veces, correo="doctora@ejemplo.mx", **extra):
        return [entrar(self.client, correo, "mal", **extra) for _ in range(veces)]

    def test_cuarto_fallo_no_pausa_quinto_si(self):
        with ahora_es(AHORA):
            cuatro = self.fallar(4)
            self.assertTrue(all(r.status_code == 200 for r in cuatro))
            quinto = self.fallar(1)[0]
            self.assertEqual(quinto.status_code, 429)
            self.assertContains(quinto, MENSAJE_PAUSA, status_code=429)

    def test_durante_la_pausa_se_rechaza_incluso_la_contrasena_correcta(self):
        with ahora_es(AHORA):
            self.fallar(5)
            r = entrar(self.client, "doctora@ejemplo.mx", CONTRASENA)
            self.assertEqual(r.status_code, 429)
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_intentos_durante_la_pausa_no_la_alargan(self):
        with ahora_es(AHORA):
            self.fallar(5)
        with ahora_es(mas(AHORA, minutes=10)):
            self.fallar(3)  # rechazados por la pausa; no cuentan
        with ahora_es(mas(AHORA, minutes=15, seconds=1)):
            r = entrar(self.client, "doctora@ejemplo.mx", CONTRASENA)
            self.assertEqual(r.status_code, 302)

    def test_la_pausa_dura_15_minutos(self):
        with ahora_es(AHORA):
            self.fallar(5)
        with ahora_es(mas(AHORA, minutes=14, seconds=59)):
            self.assertEqual(entrar(self.client, "doctora@ejemplo.mx", CONTRASENA).status_code, 429)
        with ahora_es(mas(AHORA, minutes=15, seconds=1)):
            self.assertEqual(entrar(self.client, "doctora@ejemplo.mx", CONTRASENA).status_code, 302)

    def test_fallos_fuera_de_la_ventana_de_15_minutos_no_suman(self):
        with ahora_es(AHORA):
            self.fallar(4)
        with ahora_es(mas(AHORA, minutes=16)):
            self.assertEqual(self.fallar(1)[0].status_code, 200)
            self.assertFalse(PausaAcceso.objects.exists())

    def test_tras_la_pausa_se_empieza_de_cero(self):
        with ahora_es(AHORA):
            self.fallar(5)
        with ahora_es(mas(AHORA, minutes=16)):
            self.assertEqual(self.fallar(1)[0].status_code, 200)  # no vuelve a pausar con un solo fallo

    def test_un_acierto_reinicia_el_conteo(self):
        with ahora_es(AHORA):
            self.fallar(4)
            entrar(self.client, "doctora@ejemplo.mx", CONTRASENA)
            self.client.post(reverse("cuentas:salir"))
            self.assertEqual(self.fallar(4)[-1].status_code, 200)
            self.assertFalse(PausaAcceso.objects.exists())

    def test_la_pausa_es_por_cuenta_y_direccion_no_bloquea_a_la_administradora_desde_su_red(self):
        with ahora_es(AHORA):
            self.fallar(5, REMOTE_ADDR="203.0.113.50")  # atacante
            r = entrar(self.client, "doctora@ejemplo.mx", CONTRASENA, REMOTE_ADDR="198.51.100.7")
            self.assertEqual(r.status_code, 302)

    def test_correo_inexistente_se_pausa_igual_sin_revelar_nada(self):
        with ahora_es(AHORA):
            respuestas = self.fallar(5, correo="nadie@ejemplo.mx")
            self.assertEqual([r.status_code for r in respuestas], [200, 200, 200, 200, 429])

    @override_settings(SARRCA_PROXIES_CONFIABLES=1)
    def test_detras_del_proxy_se_usa_la_ip_que_agrego_el_proxy_no_la_del_cliente(self):
        with ahora_es(AHORA):
            for _ in range(5):  # el atacante escribe una IP falsa a la izquierda
                entrar(self.client, "doctora@ejemplo.mx", "mal", HTTP_X_FORWARDED_FOR="9.9.9.9, 203.0.113.50")
            self.assertEqual(PausaAcceso.objects.get().ip, "203.0.113.50")

    def test_desbloquear_levanta_la_pausa(self):
        from apps.cuentas import services

        with ahora_es(AHORA):
            self.fallar(5)
            self.assertEqual(services.desbloquear("Doctora@ejemplo.mx"), 1)
            self.assertEqual(entrar(self.client, "doctora@ejemplo.mx", CONTRASENA).status_code, 302)
            self.assertTrue(EntradaBitacora.objects.filter(tipo_operacion=TipoOperacion.PAUSA_LEVANTADA).exists())


class BitacoraDelAccesoTests(TestCase):
    def test_fallos_pausa_y_exito_quedan_en_bitacora_sin_contrasena_ni_correo_tecleado(self):
        cuenta = crear_cuenta("doctora@ejemplo.mx", Rol.ADMINISTRADOR)
        with ahora_es(AHORA):
            for _ in range(5):
                entrar(self.client, "doctora@ejemplo.mx", "contraseña-mala-xyz")
            entrar(self.client, "nadie-registrado@ejemplo.mx", "contraseña-mala-abc")
        tipos = set(EntradaBitacora.objects.values_list("tipo_operacion", flat=True))
        self.assertIn(TipoOperacion.INICIO_SESION_FALLIDO, tipos)
        self.assertIn(TipoOperacion.PAUSA_ACTIVADA, tipos)
        self.assertTrue(EntradaBitacora.objects.filter(cuenta=cuenta).exists())
        texto = " ".join(
            f"{e.objeto_afectado} {e.valor_anterior} {e.valor_nuevo} {e.motivo} {e.detalle}"
            for e in EntradaBitacora.objects.all()
        )
        for prohibido in ("contraseña-mala-xyz", "contraseña-mala-abc", "nadie-registrado"):
            self.assertNotIn(prohibido, texto)

    def test_acceso_exitoso_queda_en_bitacora(self):
        cuenta = crear_cuenta("vecina@ejemplo.mx")
        entrar(self.client, "vecina@ejemplo.mx", CONTRASENA)
        self.assertTrue(
            EntradaBitacora.objects.filter(cuenta=cuenta, tipo_operacion=TipoOperacion.INICIO_SESION).exists()
        )


class PermisosPorRolTests(TestCase):
    def test_sin_sesion_el_panel_lleva_al_acceso(self):
        r = self.client.get(reverse("cuentas:panel_admin"))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith(ACCESO))

    def test_un_vecino_no_ve_el_panel_se_niega_y_queda_en_bitacora(self):
        vecina = crear_cuenta("vecina@ejemplo.mx", Rol.VECINO_CON_SENSOR)
        entrar(self.client, "vecina@ejemplo.mx", CONTRASENA)
        r = self.client.get(reverse("cuentas:panel_admin"))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(
            EntradaBitacora.objects.filter(cuenta=vecina, tipo_operacion=TipoOperacion.ACCESO_NEGADO).exists()
        )


class IntentosNoGuardanContrasenaTests(TestCase):
    def test_intento_fallido_solo_guarda_correo_normalizado_ip_y_fecha(self):
        crear_cuenta("vecina@ejemplo.mx")
        entrar(self.client, "vecina@ejemplo.mx", "mal")
        intento = IntentoFallido.objects.get()
        self.assertEqual(intento.correo, "vecina@ejemplo.mx")
        self.assertEqual({f.name for f in IntentoFallido._meta.fields}, {"id", "correo", "ip", "fecha_hora", "vigente"})
````

### `apps/cuentas/tests/test_crear_admin.py`

````python
"""RT-010 · Cuenta de Administrador al instalar; PE-01, SUP-08, RNF-SEG-09."""
import os
from io import StringIO
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.bitacora.models import EntradaBitacora, TipoOperacion
from apps.cuentas.models import Cuenta, Estado, Origen, Rol

from .utiles import crear_cuenta

CLAVE = "clave-de-la-doctora-9"


def correr(*args, contrasena=CLAVE):
    salida = StringIO()
    entorno = {"SARRCA_ADMIN_CONTRASENA": contrasena} if contrasena is not None else {}
    with mock.patch.dict(os.environ, entorno):
        call_command("crear_admin", *args, stdout=salida)
    return salida.getvalue()


class CrearAdminTests(TestCase):
    def test_crea_la_cuenta_validada_con_origen_instalacion(self):
        correr("--correo", "Doctora@Ejemplo.mx", "--nombre", "Dra. Ejemplo")
        cuenta = Cuenta.objects.get()
        self.assertEqual(cuenta.correo, "doctora@ejemplo.mx")
        self.assertEqual((cuenta.rol, cuenta.estado, cuenta.origen), (Rol.ADMINISTRADOR, Estado.VALIDADA, Origen.INSTALACION))
        self.assertTrue(cuenta.check_password(CLAVE))
        self.assertNotIn(CLAVE, cuenta.password)  # no se guarda legible (RNF-SEG-04)

    def test_criterio_4_puede_iniciar_sesion_desde_el_primer_arranque(self):
        correr("--correo", "doctora@ejemplo.mx")
        r = self.client.post(reverse("cuentas:acceso"), {"correo": "doctora@ejemplo.mx", "contrasena": CLAVE})
        self.assertRedirects(r, reverse("cuentas:panel_admin"), fetch_redirect_response=False)

    def test_queda_en_bitacora_sin_la_contrasena(self):
        correr("--correo", "doctora@ejemplo.mx")
        entrada = EntradaBitacora.objects.get(tipo_operacion=TipoOperacion.CUENTA_ADMIN_CREADA)
        self.assertEqual(entrada.cuenta, Cuenta.objects.get())
        self.assertNotIn(CLAVE, f"{entrada.detalle}{entrada.valor_nuevo}{entrada.objeto_afectado}")

    def test_repetirlo_no_cambia_nada(self):
        correr("--correo", "doctora@ejemplo.mx")
        antes = Cuenta.objects.get().password
        mensaje = correr("--correo", "otra@ejemplo.mx", contrasena="otra-clave-larga-1")
        self.assertIn("Ya existe", mensaje)
        self.assertEqual(Cuenta.objects.count(), 1)
        self.assertEqual(Cuenta.objects.get().password, antes)
        self.assertEqual(Cuenta.objects.get().correo, "doctora@ejemplo.mx")

    def test_contrasena_de_menos_de_8_caracteres_se_rechaza_y_no_crea_nada(self):
        with self.assertRaises(CommandError):
            correr("--correo", "doctora@ejemplo.mx", contrasena="corta1")
        self.assertFalse(Cuenta.objects.exists())

    def test_sin_correo_falla(self):
        with mock.patch.dict(os.environ, {"SARRCA_ADMIN_CORREO": ""}):
            with self.assertRaises(CommandError):
                correr()

    def test_correo_invalido_falla_y_no_crea_nada(self):
        with self.assertRaises(CommandError):
            correr("--correo", "no-es-un-correo")
        self.assertFalse(Cuenta.objects.exists())


class UnicaCuentaDeAdministradorTests(TestCase):
    def test_la_base_impide_una_segunda_cuenta_de_administrador(self):
        crear_cuenta("uno@ejemplo.mx", Rol.ADMINISTRADOR)
        with self.assertRaises(IntegrityError), transaction.atomic():
            crear_cuenta("dos@ejemplo.mx", Rol.ADMINISTRADOR)

    def test_la_cuenta_de_administrador_no_puede_darse_de_baja(self):
        cuenta = crear_cuenta("uno@ejemplo.mx", Rol.ADMINISTRADOR)
        cuenta.estado = Estado.DADA_DE_BAJA
        with self.assertRaises(ValidationError):
            cuenta.save()

    def test_pueden_existir_muchos_vecinos(self):
        for i in range(3):
            crear_cuenta(f"v{i}@ejemplo.mx", Rol.VECINO_SIN_SENSOR)
        self.assertEqual(Cuenta.objects.count(), 3)

    def test_ninguna_ruta_de_la_plataforma_registra_o_asigna_el_rol(self):
        """No hay vistas de registro: la única forma de crear el rol es el comando (SUP-08)."""
        from apps.cuentas import urls

        nombres = {p.name for p in urls.urlpatterns}
        self.assertEqual(nombres, {"inicio", "acceso", "salir", "panel_admin"})
````

### `apps/cuentas/tests/test_sesion.py`

````python
"""Sesión: se cierra tras 2 h sin actividad; las consultas automáticas de HTMX no cuentan (D-88)."""
from django.test import TestCase
from django.urls import reverse

from apps.bitacora.models import EntradaBitacora, TipoOperacion
from apps.cuentas.models import Rol

from .utiles import AHORA, CONTRASENA, ahora_es, crear_cuenta, mas

PANEL = reverse("cuentas:panel_admin")


class SesionPorInactividadTests(TestCase):
    def setUp(self):
        crear_cuenta("doctora@ejemplo.mx", Rol.ADMINISTRADOR)
        with ahora_es(AHORA):
            self.client.post(reverse("cuentas:acceso"), {"correo": "doctora@ejemplo.mx", "contrasena": CONTRASENA})

    def test_dentro_de_las_2_horas_sigue_activa(self):
        with ahora_es(mas(AHORA, hours=1, minutes=59)):
            self.assertEqual(self.client.get(PANEL).status_code, 200)

    def test_pasadas_2_horas_se_cierra_y_queda_en_bitacora(self):
        with ahora_es(mas(AHORA, hours=2, seconds=1)):
            r = self.client.get(PANEL)
            self.assertRedirects(r, reverse("cuentas:acceso"), fetch_redirect_response=False)
            self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(EntradaBitacora.objects.filter(tipo_operacion=TipoOperacion.SESION_EXPIRADA).exists())

    def test_la_actividad_normal_renueva_el_plazo(self):
        with ahora_es(mas(AHORA, hours=1, minutes=59)):
            self.client.get(PANEL)
        with ahora_es(mas(AHORA, hours=3)):  # 1 h 1 min después de la última actividad
            self.assertEqual(self.client.get(PANEL).status_code, 200)

    def test_las_consultas_automaticas_no_renuevan_el_plazo(self):
        with ahora_es(mas(AHORA, hours=1, minutes=59)):
            r = self.client.get(PANEL, HTTP_X_CONSULTA_AUTOMATICA="1", HTTP_HX_REQUEST="true")
            self.assertEqual(r.status_code, 200)  # sigue dentro del plazo, pero no lo renueva
        with ahora_es(mas(AHORA, hours=2, minutes=1)):
            r = self.client.get(PANEL)
            self.assertEqual(r.status_code, 302)

    def test_una_peticion_htmx_con_sesion_vencida_pide_redirigir_al_acceso(self):
        with ahora_es(mas(AHORA, hours=3)):
            r = self.client.get(PANEL, HTTP_HX_REQUEST="true")
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r["HX-Redirect"], reverse("cuentas:acceso"))
````

### `apps/cuentas/tests/utiles.py`

````python
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest import mock

from apps.cuentas.models import Cuenta, Estado, Origen, Rol

CONTRASENA = "contraseña-correcta-1"


def crear_cuenta(correo="vecina@ejemplo.mx", rol=Rol.VECINO_SIN_SENSOR, estado=Estado.VALIDADA, contrasena=CONTRASENA):
    cuenta = Cuenta(
        correo=correo, nombre="Persona de prueba", rol=rol, estado=estado,
        origen=Origen.INSTALACION if rol == Rol.ADMINISTRADOR else Origen.CREADA_POR_ADMIN,
    )
    cuenta.set_password(contrasena)
    cuenta.save()
    return cuenta


@contextmanager
def ahora_es(instante):
    """Congela timezone.now() en `instante` (hora local sin zona, USE_TZ = False)."""
    with mock.patch("django.utils.timezone.now", return_value=instante):
        yield


def mas(instante, **delta):
    return instante + timedelta(**delta)


AHORA = datetime(2026, 10, 14, 9, 0, 0)
````

### `apps/cuentas/urls.py`

````python
from django.urls import path

from . import views

app_name = "cuentas"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("acceso/", views.acceso, name="acceso"),
    path("salir/", views.salir, name="salir"),
    path("panel/", views.panel_admin, name="panel_admin"),
]
````

### `apps/cuentas/views.py`

````python
from django.conf import settings
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from . import services
from .decorators import rol_requerido
from .forms import AccesoForm
from .models import Rol
from .services import ResultadoAcceso

# El mismo mensaje para correo inexistente, contraseña incorrecta y cuenta que
# no puede entrar: no revela si el correo existe (IU-11, HU-003 criterio 2).
MENSAJE_DATOS_INCORRECTOS = "Correo o contraseña incorrectos."
MENSAJE_PAUSA = (
    f"Demasiados intentos. Espere {settings.SARRCA_PAUSA_ACCESO_MIN} minutos para volver a intentar."
)


@require_http_methods(["GET", "POST"])
def acceso(request):
    """HU-003 · Iniciar sesión."""
    if request.user.is_authenticated:
        return redirect(services.destino_inicial(request.user))

    mensaje = None
    form = AccesoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        resultado, cuenta = services.iniciar_sesion(
            request, form.cleaned_data["correo"], form.cleaned_data["contrasena"]
        )
        if resultado == ResultadoAcceso.ENTRO:
            siguiente = request.POST.get("next") or request.GET.get("next")
            if siguiente and url_has_allowed_host_and_scheme(
                siguiente, allowed_hosts={request.get_host()}, require_https=request.is_secure()
            ):
                return redirect(siguiente)
            return redirect(services.destino_inicial(cuenta))
        mensaje = MENSAJE_PAUSA if resultado == ResultadoAcceso.PAUSADO else MENSAJE_DATOS_INCORRECTOS
        form = AccesoForm(initial={"correo": form.cleaned_data["correo"]})  # nunca se devuelve la contraseña

    estado = 429 if mensaje == MENSAJE_PAUSA else 200
    return render(
        request, "cuentas/acceso.html",
        {"form": form, "mensaje": mensaje, "siguiente": request.GET.get("next", "")}, status=estado,
    )


@require_POST
def salir(request):
    if request.user.is_authenticated:
        services.cerrar_sesion(request)
    return redirect("cuentas:acceso")


# --- Pantallas iniciales por rol. Son marcadores: las reemplazan el panel del
# --- Administrador (HU-079) y el portal (EP-06); aquí solo muestran que el
# --- inicio de sesión lleva a donde corresponde (D-88).
@rol_requerido(Rol.ADMINISTRADOR)
def panel_admin(request):
    return render(request, "cuentas/panel_admin.html")


def inicio(request):
    return render(request, "cuentas/inicio.html")
````

### `templates/base.html`

````html
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block titulo %}SARRCA{% endblock %}</title>
  {# Estilo mínimo propio. Bootstrap 5 y HTMX entran con la tarea de la interfaz. #}
  <style>
    body { font-family: system-ui, sans-serif; margin: 0; background: #f6f7f9; color: #1d2733; }
    main { max-width: 26rem; margin: 3rem auto; padding: 0 16px; }
    .tarjeta { background: #fff; border-radius: 8px; padding: 1.5rem; box-shadow: 0 1px 4px rgba(0,0,0,.12); }
    label { display: block; margin: 1rem 0 .25rem; font-weight: 600; }
    input { width: 100%; box-sizing: border-box; padding: .6rem; font-size: 1rem; }
    button { margin-top: 1.25rem; padding: .6rem 1.2rem; font-size: 1rem; cursor: pointer; }
    .error { color: #b00020; margin: 0 0 1rem; }
  </style>
</head>
<body>
  <main>{% block contenido %}{% endblock %}</main>
</body>
</html>
````

### `templates/cuentas/acceso.html`

````html
{% extends "base.html" %}
{% block titulo %}Iniciar sesión · SARRCA{% endblock %}
{% block contenido %}
<div class="tarjeta">
  <h1>Iniciar sesión</h1>
  {% if mensaje %}<p class="error" role="alert">{{ mensaje }}</p>{% endif %}
  <form method="post" novalidate>
    {% csrf_token %}
    <input type="hidden" name="next" value="{{ siguiente }}">
    <label for="{{ form.correo.id_for_label }}">{{ form.correo.label }}</label>
    {{ form.correo }}
    <label for="{{ form.contrasena.id_for_label }}">{{ form.contrasena.label }}</label>
    {{ form.contrasena }}
    <button type="submit">Entrar</button>
  </form>
</div>
{% endblock %}
````

### `templates/cuentas/inicio.html`

````html
{% extends "base.html" %}
{% block titulo %}Inicio · SARRCA{% endblock %}
{% block contenido %}
<div class="tarjeta">
  <h1>SARRCA</h1>
  {% if request.user.is_authenticated %}
    <p>Sesión iniciada como {{ request.user.nombre }}.</p>
    <form method="post" action="{% url 'cuentas:salir' %}">{% csrf_token %}<button type="submit">Cerrar sesión</button></form>
  {% else %}
    <p><a href="{% url 'cuentas:acceso' %}">Iniciar sesión</a></p>
  {% endif %}
</div>
{% endblock %}
````

### `templates/cuentas/panel_admin.html`

````html
{% extends "base.html" %}
{% block titulo %}Panel · SARRCA{% endblock %}
{% block contenido %}
<div class="tarjeta">
  <h1>Panel del Administrador</h1>
  <p>Sesión iniciada como {{ request.user.nombre }}.</p>
  <form method="post" action="{% url 'cuentas:salir' %}">{% csrf_token %}<button type="submit">Cerrar sesión</button></form>
</div>
{% endblock %}
````

### `apps/__init__.py`

````python
````

## 4. Usar

```bash
export DJANGO_SECRET_KEY="una-clave-larga-y-aleatoria"

# Probar sin PostgreSQL (SQLite en memoria):
pytest                       # 46 pruebas

# Producción (PostgreSQL): llenar las variables de .env.example y luego
python manage.py migrate
python manage.py crear_admin --correo doctora@ejemplo.mx --nombre "Nombre"   # pide la contraseña por teclado
python manage.py desbloquear doctora@ejemplo.mx                                 # levanta una pausa de acceso
python manage.py changepassword doctora@ejemplo.mx                              # contraseña olvidada (MVP)
```

Para probarlo a mano con SQLite, crea un `config/settings_local.py` con `from .settings_test import *` y corre `DJANGO_SETTINGS_MODULE=config.settings_local python manage.py migrate`, luego `runserver`.

## 5. Qué cubre y qué no

- **Cubre:** HU-003 (iniciar sesión), RF-02 sin recuperación por correo, RT-010 (Administrador al instalar), PE-01, SUP-08, RNF-SEG-07/08/09/10.
- **No cubre:** rol de PostgreSQL sin UPDATE/DELETE sobre la bitácora (ADR sección 14), aviso de privacidad y colonia de la cuenta, recuperación por correo (HU-004), pantallas reales (`/panel/` y `/` son marcadores).
- En producción, `SARRCA_PROXIES_CONFIABLES=1` (Caddy); sin eso todas las personas parecerían venir de la misma IP.
