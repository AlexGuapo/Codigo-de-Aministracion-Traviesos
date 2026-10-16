"""Inicio y cierre de sesión, pausa por intentos fallidos y la cuenta de Administrador.

Es el único lugar de `cuentas` que escribe en la base.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from enum import StrEnum

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from cuentas.models import Cuenta, Estado, IntentoAcceso, Origen, Rol

logger = logging.getLogger("cuentas")

CLAVE_ULTIMA_ACTIVIDAD = "sarrca_ultima_actividad"


class ResultadoAcceso(StrEnum):
    ENTRO = "entro"
    DATOS_INCORRECTOS = "datos_incorrectos"
    PAUSADO = "pausado"


class AdministradorYaExiste(Exception):
    """Ya hay una cuenta de Administrador vigente; solo puede haber una."""


def normalizar_correo(correo: str | None) -> str:
    return (correo or "").strip().lower()


def obtener_ip(request) -> str:
    """Dirección del cliente.

    Detrás de un proxy, REMOTE_ADDR es la del proxy y todas las personas parecerían la misma.
    Con `SARRCA_PROXIES_CONFIABLES = n` se toma la n-ésima entrada de X-Forwarded-For contando
    desde la derecha (la que agregó nuestro proxy); lo que el cliente escriba a la izquierda no
    se usa.
    """
    n = settings.SARRCA_PROXIES_CONFIABLES
    if n > 0:
        reenviadas = [
            parte.strip()
            for parte in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")
            if parte.strip()
        ]
        if len(reenviadas) >= n:
            return reenviadas[-n]
    return request.META.get("REMOTE_ADDR") or "0.0.0.0"


def destino_inicial(cuenta: Cuenta) -> str:
    """El Administrador entra al panel de la red; los vecinos, a su página de inicio."""
    if cuenta.rol == Rol.ADMINISTRADOR:
        return reverse("reportes:panel_red")
    return reverse("cuentas:inicio")


def pausa_hasta(correo: str, ip: str, ahora: datetime | None = None) -> datetime | None:
    """Hasta cuándo está en pausa el par (correo, IP), o None si no lo está.

    La pausa empieza cuando se juntan `SARRCA_MAX_INTENTOS_FALLIDOS` fallos dentro de una ventana
    de `SARRCA_VENTANA_INTENTOS_MIN` minutos y dura `SARRCA_PAUSA_ACCESO_MIN`. Los intentos hechos
    durante la pausa quedan registrados pero no la alargan, y al terminar la pausa el conteo
    empieza de cero. Un inicio de sesión correcto también reinicia el conteo.
    """
    ahora = ahora or timezone.now()
    ventana = timedelta(minutes=settings.SARRCA_VENTANA_INTENTOS_MIN)
    duracion = timedelta(minutes=settings.SARRCA_PAUSA_ACCESO_MIN)

    intentos = IntentoAcceso.objects.filter(
        correo_intentado=correo, ip=ip, ocurrido_en__gte=ahora - ventana - duracion
    )
    ultimo_exito = intentos.filter(exito=True).order_by("-ocurrido_en").first()
    fallos = intentos.filter(exito=False)
    if ultimo_exito is not None:
        fallos = fallos.filter(ocurrido_en__gt=ultimo_exito.ocurrido_en)

    hasta = None
    en_ventana: list[datetime] = []
    for momento in fallos.order_by("ocurrido_en").values_list("ocurrido_en", flat=True):
        if hasta is not None and momento < hasta:
            continue
        en_ventana = [anterior for anterior in en_ventana if anterior > momento - ventana]
        en_ventana.append(momento)
        if len(en_ventana) >= settings.SARRCA_MAX_INTENTOS_FALLIDOS:
            hasta = momento + duracion
            en_ventana = []
    if hasta is not None and hasta > ahora:
        return hasta
    return None


def iniciar_sesion(request, correo: str, contrasena: str) -> tuple[ResultadoAcceso, Cuenta | None]:
    """Intenta entrar con correo y contraseña.

    El resultado es el mismo para un correo que no existe, una contraseña mala o una cuenta que
    no puede entrar, para no revelar qué correos están registrados. Durante una pausa se rechaza
    incluso la contraseña correcta.
    """
    correo = normalizar_correo(correo)
    ip = obtener_ip(request)
    existente = Cuenta.objects.filter(correo=correo).first()

    if pausa_hasta(correo, ip) is not None:
        IntentoAcceso.objects.create(correo_intentado=correo, cuenta=existente, ip=ip, exito=False)
        logger.warning("Intento de acceso durante una pausa desde %s", ip)
        return ResultadoAcceso.PAUSADO, None

    cuenta = authenticate(request, username=correo, password=contrasena)
    if cuenta is None:
        IntentoAcceso.objects.create(correo_intentado=correo, cuenta=existente, ip=ip, exito=False)
        if pausa_hasta(correo, ip) is not None:
            logger.warning("Pausa de acceso activada desde %s", ip)
            return ResultadoAcceso.PAUSADO, None
        return ResultadoAcceso.DATOS_INCORRECTOS, None

    with transaction.atomic():
        login(request, cuenta)
        request.session[CLAVE_ULTIMA_ACTIVIDAD] = time.time()
        IntentoAcceso.objects.create(correo_intentado=correo, cuenta=cuenta, ip=ip, exito=True)
    logger.info("Inicio de sesión de la cuenta %s desde %s", cuenta.pk, ip)
    return ResultadoAcceso.ENTRO, cuenta


def cerrar_sesion(request, expirada: bool = False) -> None:
    cuenta_id = request.user.pk if request.user.is_authenticated else None
    logout(request)
    if expirada:
        logger.info("Sesión de la cuenta %s cerrada por inactividad", cuenta_id)
    else:
        logger.info("Cierre de sesión de la cuenta %s", cuenta_id)


def desbloquear(correo: str, ip: str | None = None) -> int:
    """Borra los intentos fallidos de un correo (de una IP, si se indica) y con ellos su pausa.

    Devuelve cuántos intentos se borraron.
    """
    fallos = IntentoAcceso.objects.filter(correo_intentado=normalizar_correo(correo), exito=False)
    if ip:
        fallos = fallos.filter(ip=ip)
    borrados, _ = fallos.delete()
    logger.info("Desbloqueo de un correo: %s intentos fallidos borrados", borrados)
    return borrados


@transaction.atomic
def crear_administrador(correo: str, nombre: str, contrasena: str) -> Cuenta:
    """Crea la única cuenta de Administrador al instalar el sistema.

    No hay ninguna pantalla que cree, asigne o dé de baja este rol. Si ya hay una cuenta de
    Administrador vigente, lanza `AdministradorYaExiste` y no cambia nada.
    """
    vigentes = Cuenta.objects.filter(rol=Rol.ADMINISTRADOR).exclude(
        estado__in=[Estado.DADA_DE_BAJA, Estado.SUPRIMIDA]
    )
    if vigentes.exists():
        raise AdministradorYaExiste()
    validate_password(contrasena)
    cuenta = Cuenta(
        correo=normalizar_correo(correo),
        nombre=nombre.strip(),
        rol=Rol.ADMINISTRADOR,
        estado=Estado.VALIDADA,
        origen=Origen.INSTALACION,
    )
    cuenta.set_password(contrasena)
    cuenta.full_clean(exclude=["password", "creada_en", "actualizada_en"])
    cuenta.save()
    logger.info("Cuenta de Administrador creada (cuenta %s)", cuenta.pk)
    return cuenta
