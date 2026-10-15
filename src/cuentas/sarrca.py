#!/usr/bin/env python3
"""
SARRCA · Inicio de sesión y cuenta de Administrador al instalar
===============================================================
Todo el código en UN solo archivo. Requiere únicamente:  pip install "Django>=5.2,<5.3"

Cubre: HU-003 (Iniciar sesión), RF-02 / D-88 (sin la recuperación por correo, HU-004),
RT-010 (cuenta de Administrador al instalar), PE-01, SUP-08 y RNF-SEG-07/08/09/10.

USO (todos los comandos son de este mismo archivo):

    python sarrca.py migrate                      # crea las tablas
    python sarrca.py crear_admin --correo doctora@ejemplo.mx --nombre "Nombre"
                                                  # crea la ÚNICA cuenta de Administrador (pide la contraseña)
    python sarrca.py runserver                    # sirve en http://127.0.0.1:8000/acceso/
    python sarrca.py desbloquear doctora@ejemplo.mx [--ip 203.0.113.7]   # levanta una pausa de acceso
    python sarrca.py changepassword doctora@ejemplo.mx                   # contraseña olvidada (MVP)

CONFIGURACIÓN (variables de entorno; nada secreto va en el código):

    DJANGO_SECRET_KEY          obligatoria si SARRCA_PRODUCCION=1
    SARRCA_PRODUCCION=1        HTTPS, cookies seguras, DEBUG apagado
    SARRCA_PROXIES_CONFIABLES  proxies delante de la web (Caddy = 1; se pone solo en producción)
    DJANGO_ALLOWED_HOSTS       "host1,host2"
    SARRCA_DB_HOST             si se define, usa PostgreSQL (SARRCA_DB_NOMBRE, SARRCA_DB_USUARIO_APP,
                               SARRCA_DB_CONTRASENA_APP, SARRCA_DB_PUERTO); si no, SQLite local
    SARRCA_ADMIN_CORREO / SARRCA_ADMIN_NOMBRE / SARRCA_ADMIN_CONTRASENA   para crear_admin sin preguntar
"""
import getpass
import os
import sys
import types
from datetime import timedelta
from functools import wraps
from pathlib import Path

import django
from django.conf import settings

BASE_DIR = Path(__file__).resolve().parent


def _bool(nombre, por_omision=False):
    return os.environ.get(nombre, str(por_omision)).strip().lower() in ("1", "true", "si", "sí")


# ==========================================================================
# 1. PLANTILLAS (en el mismo archivo)
# ==========================================================================
PLANTILLAS = {
    "base.html": """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block titulo %}SARRCA{% endblock %}</title>
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
""",
    "acceso.html": """{% extends "base.html" %}
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
""",
    "panel_admin.html": """{% extends "base.html" %}
{% block titulo %}Panel · SARRCA{% endblock %}
{% block contenido %}
<div class="tarjeta">
  <h1>Panel del Administrador</h1>
  <p>Sesión iniciada como {{ request.user.nombre }}.</p>
  <form method="post" action="{% url 'cuentas:salir' %}">{% csrf_token %}<button type="submit">Cerrar sesión</button></form>
</div>
{% endblock %}
""",
    "inicio.html": """{% extends "base.html" %}
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
""",
}


# ==========================================================================
# 2. CONFIGURACIÓN DE DJANGO
# ==========================================================================
PRODUCCION = _bool("SARRCA_PRODUCCION")
if PRODUCCION and not os.environ.get("DJANGO_SECRET_KEY"):
    raise SystemExit("En producción falta la variable DJANGO_SECRET_KEY.")

# SARRCA_* : valores del ADR «Acceso y sesión» (D-88)
SARRCA_MAX_INTENTOS_FALLIDOS = 5            # intentos fallidos...
SARRCA_VENTANA_INTENTOS_MIN = 15            # ...en estos minutos...
SARRCA_PAUSA_ACCESO_MIN = 15                # ...provocan una pausa de estos minutos
SARRCA_INACTIVIDAD_MAX_SEG = 2 * 60 * 60    # la sesión se cierra tras 2 h sin actividad

if os.environ.get("SARRCA_DB_HOST"):  # PostgreSQL 18 (ADR, pila tecnológica)
    BASE_DE_DATOS = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("SARRCA_DB_NOMBRE", "sarrca"),
        "USER": os.environ.get("SARRCA_DB_USUARIO_APP", "sarrca_app"),
        "PASSWORD": os.environ.get("SARRCA_DB_CONTRASENA_APP", ""),
        "HOST": os.environ["SARRCA_DB_HOST"],
        "PORT": os.environ.get("SARRCA_DB_PUERTO", "5432"),
    }
else:  # para desarrollo y pruebas: SQLite local
    BASE_DE_DATOS = {"ENGINE": "django.db.backends.sqlite3", "NAME": str(BASE_DIR / "sarrca.sqlite3")}

# Las dos «apps» (cuentas y bitácora) viven en este archivo: se registran como módulos
# mínimos para que Django les dé su etiqueta (cuentas.Cuenta, bitacora.EntradaBitacora).
for _etiqueta in ("bitacora", "cuentas"):
    _m = types.ModuleType(_etiqueta)
    _m.__file__ = str(BASE_DIR / f"{_etiqueta}.py")
    _m.__path__ = []
    sys.modules[_etiqueta] = _m

if not settings.configured:
    settings.configure(
        SECRET_KEY=os.environ.get("DJANGO_SECRET_KEY", "clave-solo-para-desarrollo-no-usar-en-produccion"),
        DEBUG=_bool("DJANGO_DEBUG") and not PRODUCCION,
        ALLOWED_HOSTS=[h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h],
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.messages",
            "bitacora",
            "cuentas",
        ],
        MIGRATION_MODULES={"bitacora": None, "cuentas": None},  # tablas con `migrate` (syncdb)
        MIDDLEWARE=[
            "django.middleware.security.SecurityMiddleware",
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.middleware.common.CommonMiddleware",
            "django.middleware.csrf.CsrfViewMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            f"{__name__}.SesionPorInactividad",
            "django.contrib.messages.middleware.MessageMiddleware",
        ],
        ROOT_URLCONF=__name__,
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": False,
                "OPTIONS": {
                    "loaders": [("django.template.loaders.locmem.Loader", PLANTILLAS)],
                    "context_processors": [
                        "django.template.context_processors.request",
                        "django.contrib.auth.context_processors.auth",
                        "django.contrib.messages.context_processors.messages",
                    ],
                },
            }
        ],
        DATABASES={"default": BASE_DE_DATOS},
        # Hora local (ADR «Hora UTC+8 a local», RL-14): sin zona en la base
        USE_TZ=False,
        TIME_ZONE="America/Mexico_City",
        LANGUAGE_CODE="es-mx",
        USE_I18N=True,
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        # Acceso y sesión (AUTH_USER_MODEL se fija justo después de django.setup(); ver abajo)
        AUTHENTICATION_BACKENDS=[f"{__name__}.CuentaBackend"],
        LOGIN_URL="cuentas:acceso",
        AUTH_PASSWORD_VALIDATORS=[
            {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
        ],
        # Las 2 h las decide el middleware (así quedan en la bitácora y HTMX recibe su redirección).
        # La cookie vive más, solo como margen.
        SESSION_COOKIE_AGE=24 * 60 * 60,
        SESSION_SAVE_EVERY_REQUEST=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Proxies de confianza delante de la web (Caddy = 1). Con 0 se usa la IP de la conexión.
        # Sin esto, en producción todas las personas parecerían venir de la IP de Caddy.
        SARRCA_PROXIES_CONFIABLES=int(os.environ.get("SARRCA_PROXIES_CONFIABLES", "1" if PRODUCCION else "0")),
        SARRCA_MAX_INTENTOS_FALLIDOS=SARRCA_MAX_INTENTOS_FALLIDOS,
        SARRCA_VENTANA_INTENTOS_MIN=SARRCA_VENTANA_INTENTOS_MIN,
        SARRCA_PAUSA_ACCESO_MIN=SARRCA_PAUSA_ACCESO_MIN,
        SARRCA_INACTIVIDAD_MAX_SEG=SARRCA_INACTIVIDAD_MAX_SEG,
        # HTTPS siempre en producción (RNF-SEG-06)
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https") if PRODUCCION else None,
        SESSION_COOKIE_SECURE=PRODUCCION,
        CSRF_COOKIE_SECURE=PRODUCCION,
        SECURE_HSTS_SECONDS=31536000 if PRODUCCION else 0,
        LOGGING={
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
            "handlers": {"consola": {"class": "logging.StreamHandler", "formatter": "std"}},
            "root": {"handlers": ["consola"], "level": "INFO"},
        },
    )
    django.setup()
    # En un proyecto de varios archivos, AUTH_USER_MODEL va en settings. Aquí el modelo Cuenta se
    # define más abajo en este mismo archivo, y django.setup() (auth.ready) aún no puede
    # encontrarlo; por eso se fija después. Es válido: el modelo User de Django queda «swapped»
    # (sin tabla) y todo el sistema usa cuentas.Cuenta.
    settings.AUTH_USER_MODEL = "cuentas.Cuenta"
    # Django guarda en caché si User está «swapped»; hay que avisarle que el ajuste cambió.
    from django.core.signals import setting_changed

    setting_changed.send(
        sender=type(settings._wrapped), setting="AUTH_USER_MODEL", value="cuentas.Cuenta", enter=True
    )

# Estos imports van después de configurar Django.
from django.contrib.auth import authenticate, login, logout  # noqa: E402
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager  # noqa: E402
from django.contrib.auth.password_validation import validate_password  # noqa: E402
from django.core.exceptions import ValidationError  # noqa: E402
from django import forms  # noqa: E402
from django.db import models, transaction  # noqa: E402
from django.db.models import Q  # noqa: E402
from django.http import HttpResponse, HttpResponseForbidden  # noqa: E402
from django.shortcuts import redirect, render  # noqa: E402
from django.urls import include, path, reverse  # noqa: E402
from django.utils import timezone  # noqa: E402
from django.utils.http import url_has_allowed_host_and_scheme  # noqa: E402
from django.views.decorators.http import require_http_methods, require_POST  # noqa: E402


# ==========================================================================
# 3. BITÁCORA DE AUDITORÍA (HU-019, RES-03, RL-09, PE-13)
# ==========================================================================
# Solo crece: nadie edita ni borra una entrada, tampoco el Administrador. Aquí se impide desde
# el ORM; la defensa de fondo es el rol de PostgreSQL de la aplicación, sin UPDATE ni DELETE
# sobre esta tabla (ADR «Solo inserción impuesto desde la base», sección 14).
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
        "cuentas.Cuenta", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
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
        app_label = "bitacora"
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


def registrar_bitacora(
    tipo_operacion, resultado, cuenta=None, objeto_afectado="", valor_anterior="", valor_nuevo="", motivo="", detalle=""
):
    """Único punto de escritura de la bitácora (ADR: «servicio común»)."""
    return EntradaBitacora.objects.create(
        cuenta=cuenta, tipo_operacion=tipo_operacion, resultado=resultado, objeto_afectado=objeto_afectado,
        valor_anterior=valor_anterior, valor_nuevo=valor_nuevo, motivo=motivo, detalle=detalle,
    )


# ==========================================================================
# 4. CUENTAS, ROLES Y CONTROL DE INTENTOS (SRS 3.5 y 3.6)
# ==========================================================================
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


# Estados con los que se puede iniciar sesión. Una cuenta por validar entra para consultar las
# alertas de su colonia, pero no puede reportar (PE-10).
ESTADOS_QUE_ENTRAN = (Estado.POR_VALIDAR, Estado.VALIDADA)


class CuentaManager(BaseUserManager):
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
        app_label = "cuentas"
        constraints = [
            # PE-01 / SUP-08 / RNF-SEG-09: nunca puede haber más de una cuenta de Administrador.
            # Lo impide la base, no solo el código.
            models.UniqueConstraint(
                fields=["rol"], condition=Q(rol="administrador"), name="una_sola_cuenta_administrador"
            ),
        ]

    @property
    def is_active(self):  # lo que Django necesita de un modelo de usuario
        return self.estado in ESTADOS_QUE_ENTRAN

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

    Se cuenta el par (correo, IP) y no solo el correo, para que nadie pueda dejar bloqueada a la
    única Administradora desde otra red. El correo es el texto normalizado que se tecleó, exista o
    no la cuenta: así la pausa se comporta igual y no revela qué correos están registrados (IU-11).
    """

    correo = models.CharField(max_length=254)
    ip = models.GenericIPAddressField()
    fecha_hora = models.DateTimeField(default=timezone.now)
    vigente = models.BooleanField(default=True)  # deja de contar al activarse una pausa o al desbloquear

    class Meta:
        app_label = "cuentas"
        indexes = [models.Index(fields=["correo", "ip", "fecha_hora"], name="intento_correo_ip_fecha")]


class PausaAcceso(models.Model):
    correo = models.CharField(max_length=254)
    ip = models.GenericIPAddressField()
    creada = models.DateTimeField(default=timezone.now)
    hasta = models.DateTimeField()

    class Meta:
        app_label = "cuentas"
        indexes = [models.Index(fields=["correo", "ip", "hasta"], name="pausa_correo_ip_hasta")]


# ==========================================================================
# 5. SERVICIOS (único punto de escritura; cada uno deja su entrada en la bitácora)
# ==========================================================================
# Django solo crea las tablas de una app si ésta tiene un «módulo de modelos»; aquí es este archivo.
from django.apps import apps as _apps  # noqa: E402

for _etiqueta in ("bitacora", "cuentas"):
    _apps.get_app_config(_etiqueta).models_module = sys.modules[__name__]

CLAVE_ULTIMA_ACTIVIDAD = "sarrca_ultima_actividad"


class AdministradorYaExiste(Exception):
    """Ya hay una cuenta de Administrador: solo hay una (PE-01)."""


class ResultadoAcceso:
    ENTRO = "entro"
    DATOS_INCORRECTOS = "datos_incorrectos"
    PAUSADO = "pausado"


def normalizar_correo(correo):
    return (correo or "").strip().lower()


def obtener_ip(request):
    """Dirección del cliente.

    Detrás de Caddy, REMOTE_ADDR es la de Caddy: todos parecerían la misma persona. Con
    SARRCA_PROXIES_CONFIABLES = n se toma la n-ésima entrada de X-Forwarded-For contando desde
    la derecha (la que agregó nuestro proxy); lo que el cliente escriba a la izquierda no se usa.
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
    # Estos fallos ya se «gastaron»: al terminar la pausa se empieza de cero.
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
    registrar_bitacora(
        TipoOperacion.PAUSA_LEVANTADA, Resultado.EXITOSO, cuenta=cuenta,
        objeto_afectado="cuenta" if cuenta else "correo sin cuenta",
        detalle=f"pausas levantadas={levantadas}" + (f"; ip={ip}" if ip else ""),
    )
    return levantadas


def iniciar_sesion(request, correo, contrasena):
    """HU-003. Devuelve (ResultadoAcceso, cuenta o None).

    - Mismo resultado y mismo mensaje para correo inexistente, contraseña incorrecta y cuenta que
      no puede entrar (IU-11, HU-003 criterios 2 y 3).
    - Durante una pausa se rechaza incluso la contraseña correcta y esos intentos no alargan la
      pausa (RNF-SEG-10).
    - Todo queda en la bitácora, sin guardar el correo tecleado ni la contraseña.
    """
    correo = normalizar_correo(correo)
    ip = obtener_ip(request)
    existente = Cuenta.objects.filter(correo=correo).first()

    if pausa_activa(correo, ip):
        registrar_bitacora(
            TipoOperacion.ACCESO_PAUSADO, Resultado.NEGADO, cuenta=existente,
            objeto_afectado="inicio de sesión", detalle=f"ip={ip}",
        )
        return ResultadoAcceso.PAUSADO, None

    cuenta = authenticate(request, username=correo, password=contrasena)
    if cuenta is None:
        with transaction.atomic():
            se_pauso = _registrar_fallo(correo, ip)
            registrar_bitacora(
                TipoOperacion.INICIO_SESION_FALLIDO, Resultado.NEGADO, cuenta=existente,
                objeto_afectado="inicio de sesión", detalle=f"ip={ip}",
            )
            if se_pauso:
                registrar_bitacora(
                    TipoOperacion.PAUSA_ACTIVADA, Resultado.EXITOSO, cuenta=existente,
                    objeto_afectado="inicio de sesión",
                    detalle=f"ip={ip}; minutos={settings.SARRCA_PAUSA_ACCESO_MIN}",
                )
        return (ResultadoAcceso.PAUSADO if se_pauso else ResultadoAcceso.DATOS_INCORRECTOS), None

    with transaction.atomic():
        login(request, cuenta)
        request.session[CLAVE_ULTIMA_ACTIVIDAD] = timezone.now().timestamp()
        IntentoFallido.objects.filter(correo=correo, ip=ip, vigente=True).update(vigente=False)
        registrar_bitacora(
            TipoOperacion.INICIO_SESION, Resultado.EXITOSO, cuenta=cuenta,
            objeto_afectado="inicio de sesión", detalle=f"ip={ip}",
        )
    return ResultadoAcceso.ENTRO, cuenta


def cerrar_sesion(request, expirada=False):
    cuenta = request.user if request.user.is_authenticated else None
    ip = obtener_ip(request)
    logout(request)
    registrar_bitacora(
        TipoOperacion.SESION_EXPIRADA if expirada else TipoOperacion.CIERRE_SESION,
        Resultado.EXITOSO, cuenta=cuenta, objeto_afectado="sesión", detalle=f"ip={ip}",
    )


def registrar_acceso_negado(request, objeto):
    """RNF-SEG-08: todo intento negado queda en la bitácora con la cuenta, la operación y la hora."""
    registrar_bitacora(
        TipoOperacion.ACCESO_NEGADO, Resultado.NEGADO,
        cuenta=request.user if request.user.is_authenticated else None,
        objeto_afectado=objeto, detalle=f"ip={obtener_ip(request)}",
    )


@transaction.atomic
def crear_administrador(correo, nombre, contrasena):
    """Crea la única cuenta de Administrador (RT-010). Solo la invoca el comando `crear_admin`.

    No existe ninguna vista ni servicio que registre, asigne o dé de baja ese rol (PE-01, SUP-08,
    RNF-SEG-09). Si ya hay una, lanza AdministradorYaExiste y no cambia nada.
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
    registrar_bitacora(
        TipoOperacion.CUENTA_ADMIN_CREADA, Resultado.EXITOSO, cuenta=cuenta,
        objeto_afectado="cuenta de Administrador", detalle="creada por el comando crear_admin",
    )
    return cuenta


# ==========================================================================
# 6. AUTENTICACIÓN, SESIÓN Y PERMISOS
# ==========================================================================
# Estos dos módulos de Django llaman a get_user_model() al importarse, así que van después de
# definir el modelo Cuenta.
from django.contrib.auth.backends import ModelBackend  # noqa: E402
from django.contrib.auth.views import redirect_to_login  # noqa: E402


class CuentaBackend(ModelBackend):
    """Autentica por correo y contraseña.

    Hereda de ModelBackend, que ya iguala el tiempo de respuesta cuando el correo no existe (así no
    se puede distinguir por la demora) y que rechaza a las cuentas cuyo is_active es falso: dadas
    de baja, bloqueadas, suprimidas o por activar (HU-003, criterio 3).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is not None:
            username = username.strip().lower()
        return super().authenticate(request, username=username, password=password, **kwargs)


CABECERA_AUTOMATICA = "X-Consulta-Automatica"


def es_consulta_automatica(request):
    return request.headers.get(CABECERA_AUTOMATICA) == "1"


class SesionPorInactividad:
    """La sesión se cierra tras 2 h sin actividad (D-88).

    Las consultas automáticas de HTMX (el estado de la verificación del alta, la actualización del
    panel) no cuentan como actividad: de lo contrario, una pestaña abierta mantendría viva la sesión
    para siempre. Esas consultas deben llevar la cabecera `X-Consulta-Automatica: 1`
    (en HTMX: hx-headers='{"X-Consulta-Automatica": "1"}').
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            ahora = timezone.now().timestamp()
            ultima = request.session.get(CLAVE_ULTIMA_ACTIVIDAD)
            # Una sesión sin marca se trata como vencida.
            if ultima is None or ahora - ultima > settings.SARRCA_INACTIVIDAD_MAX_SEG:
                cerrar_sesion(request, expirada=True)
                destino = reverse(settings.LOGIN_URL)
                if request.headers.get("HX-Request"):
                    return HttpResponse(status=401, headers={"HX-Redirect": destino})
                return redirect(destino)
            if not es_consulta_automatica(request):
                request.session[CLAVE_ULTIMA_ACTIVIDAD] = ahora
        return self.get_response(request)


def rol_requerido(*roles):
    """Permiso por rol en cada vista (RNF-SEG-07).

    Sin sesión: lleva al inicio de sesión. Con un rol que no corresponde: se niega (403) y el
    intento queda en la bitácora. La revisión se repite en cada servicio que escribe.
    """

    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), reverse(settings.LOGIN_URL))
            if request.user.rol not in roles:
                registrar_acceso_negado(request, f"vista {request.path}")
                return HttpResponseForbidden("No tiene permiso para ver esta página.")
            return vista(request, *args, **kwargs)

        return envoltura

    return decorador


# ==========================================================================
# 7. FORMULARIO, VISTAS Y RUTAS
# ==========================================================================
class AccesoForm(forms.Form):
    correo = forms.CharField(
        label="Correo electrónico", max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "username", "autofocus": True}),
    )
    contrasena = forms.CharField(
        label="Contraseña", max_length=128, strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


# El mismo mensaje para correo inexistente, contraseña incorrecta y cuenta que no puede entrar:
# no revela si el correo existe (IU-11, HU-003 criterio 2).
MENSAJE_DATOS_INCORRECTOS = "Correo o contraseña incorrectos."
MENSAJE_PAUSA = f"Demasiados intentos. Espere {SARRCA_PAUSA_ACCESO_MIN} minutos para volver a intentar."


@require_http_methods(["GET", "POST"])
def acceso(request):
    """HU-003 · Iniciar sesión."""
    if request.user.is_authenticated:
        return redirect(destino_inicial(request.user))

    mensaje = None
    form = AccesoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        resultado, cuenta = iniciar_sesion(request, form.cleaned_data["correo"], form.cleaned_data["contrasena"])
        if resultado == ResultadoAcceso.ENTRO:
            siguiente = request.POST.get("next") or request.GET.get("next")
            if siguiente and url_has_allowed_host_and_scheme(
                siguiente, allowed_hosts={request.get_host()}, require_https=request.is_secure()
            ):
                return redirect(siguiente)
            return redirect(destino_inicial(cuenta))
        mensaje = MENSAJE_PAUSA if resultado == ResultadoAcceso.PAUSADO else MENSAJE_DATOS_INCORRECTOS
        form = AccesoForm(initial={"correo": form.cleaned_data["correo"]})  # nunca se devuelve la contraseña

    estado = 429 if mensaje == MENSAJE_PAUSA else 200
    return render(
        request, "acceso.html",
        {"form": form, "mensaje": mensaje, "siguiente": request.GET.get("next", "")}, status=estado,
    )


@require_POST
def salir(request):
    if request.user.is_authenticated:
        cerrar_sesion(request)
    return redirect("cuentas:acceso")


# Pantallas iniciales por rol. Son marcadores: las reemplazan el panel del Administrador (HU-079)
# y el portal (EP-06); aquí solo muestran que el inicio de sesión lleva a donde corresponde (D-88).
@rol_requerido(Rol.ADMINISTRADOR)
def panel_admin(request):
    return render(request, "panel_admin.html")


def inicio(request):
    return render(request, "inicio.html")


_rutas_cuentas = [
    path("", inicio, name="inicio"),
    path("acceso/", acceso, name="acceso"),
    path("salir/", salir, name="salir"),
    path("panel/", panel_admin, name="panel_admin"),
]
urlpatterns = [path("", include((_rutas_cuentas, "cuentas")))]


def obtener_wsgi():
    """Para gunicorn:  gunicorn "sarrca:obtener_wsgi()"  (el archivo debe llamarse sarrca.py)."""
    from django.core.wsgi import get_wsgi_application

    return get_wsgi_application()


# ==========================================================================
# 8. COMANDOS DE INSTALACIÓN
# ==========================================================================
class ErrorComando(Exception):
    """Error de uso de un comando; se muestra sin traza."""


def cmd_crear_admin(argv, salida=None):
    """RT-010 · Crea la cuenta de Administrador al instalar el sistema.

    La contraseña nunca va en la línea de comandos (quedaría en el historial del shell y en la
    lista de procesos): se pide por teclado, dos veces, o se toma de SARRCA_ADMIN_CONTRASENA solo
    para esta ejecución. Es seguro repetirlo: si ya hay Administrador, no cambia nada.
    """
    import argparse

    salida = salida or sys.stdout
    p = argparse.ArgumentParser(prog="sarrca.py crear_admin", description=cmd_crear_admin.__doc__.splitlines()[0])
    p.add_argument("--correo", default=os.environ.get("SARRCA_ADMIN_CORREO"))
    p.add_argument("--nombre", default=os.environ.get("SARRCA_ADMIN_NOMBRE", "Administrador"))
    opciones = p.parse_args(argv)

    if not opciones.correo:
        raise ErrorComando("Falta el correo: use --correo o la variable SARRCA_ADMIN_CORREO.")
    contrasena = os.environ.get("SARRCA_ADMIN_CONTRASENA")
    if not contrasena:
        contrasena = getpass.getpass("Contraseña de la cuenta de Administrador: ")
        if contrasena != getpass.getpass("Repita la contraseña: "):
            raise ErrorComando("Las contraseñas no coinciden.")
    try:
        cuenta = crear_administrador(opciones.correo, opciones.nombre, contrasena)
    except AdministradorYaExiste:
        print("Ya existe una cuenta de Administrador; no se cambió nada.", file=salida)
        return
    except ValidationError as error:
        raise ErrorComando("; ".join(error.messages))
    print(f"Cuenta de Administrador creada: {cuenta.correo}", file=salida)


def cmd_desbloquear(argv, salida=None):
    """Levanta una pausa de acceso (sin --ip, desde cualquier dirección). Queda en la bitácora."""
    import argparse

    salida = salida or sys.stdout
    p = argparse.ArgumentParser(prog="sarrca.py desbloquear", description=cmd_desbloquear.__doc__)
    p.add_argument("correo")
    p.add_argument("--ip", default=None)
    opciones = p.parse_args(argv)
    print(f"Pausas levantadas: {desbloquear(opciones.correo, opciones.ip)}", file=salida)


# ==========================================================================
# 9. PUNTO DE ENTRADA
# ==========================================================================
def principal(argv=None):
    from django.core.management import call_command, execute_from_command_line

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "ayuda"):
        print(__doc__)
        return 0
    orden, resto = argv[0], argv[1:]
    try:
        if orden == "migrate":
            call_command("migrate", run_syncdb=True, verbosity=1)
            return 0
        if orden == "crear_admin":
            cmd_crear_admin(resto)
            return 0
        if orden == "desbloquear":
            cmd_desbloquear(resto)
            return 0
        if orden == "runserver":
            call_command("runserver", *(resto or ["127.0.0.1:8000"]), use_reloader=False)
            return 0
    except ErrorComando as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    # changepassword, check, shell, etc.: los comandos normales de Django
    execute_from_command_line([sys.argv[0], *argv])
    return 0


if __name__ == "__main__":
    sys.exit(principal())
