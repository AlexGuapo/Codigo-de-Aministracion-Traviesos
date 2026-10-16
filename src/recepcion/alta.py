"""Lado del proceso de fondo en el alta de un sensor.

La web nunca habla con la nube: deja una verificación pendiente y, al confirmar el alta, una
solicitud de relleno. Aquí se atienden las dos. Cada una se toma con `SKIP LOCKED`, así dos hilos
nunca atienden la misma.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from recepcion.models import EstadoRelleno, SolicitudRelleno
from recepcion.ports import (
    FuenteDeLecturas,
    FuenteNoDisponible,
    LecturaNormalizada,
    SensorConsultado,
)
from recepcion.services import (
    PAGINAS_RECORRIDO_COMPLETO,
    TAMANO_HISTORIAL,
    Lector,
    anotar_recorrido_completo,
    cifrado,
    secreto,
)
from sensores.cifrado import Cifrador
from sensores.models import EstadoVerificacion, VerificacionSensor

logger = logging.getLogger("recepcion.alta")

VIGENCIA_VERIFICACION = timedelta(minutes=15)
CAMPOS_RESUMEN = ("pm1_0", "pm2_5", "pm4_0", "pm10_0", "co2", "intervalo_s")


def _tomar_verificacion() -> VerificacionSensor | None:
    with transaction.atomic():
        verificacion = (
            VerificacionSensor.objects.select_for_update(skip_locked=True)
            .filter(estado=EstadoVerificacion.PENDIENTE)
            .order_by("solicitada_en", "pk")
            .first()
        )
        if verificacion is None:
            return None
        verificacion.estado = EstadoVerificacion.EN_CURSO
        verificacion.tomada_en = timezone.now()
        verificacion.save(update_fields=["estado", "tomada_en"])
    return verificacion


def resumen_de(lectura: LecturaNormalizada) -> dict:
    return {campo: getattr(lectura, campo) for campo in CAMPOS_RESUMEN}


def _lectura_mas_antigua(fuente: FuenteDeLecturas, consultado: SensorConsultado) -> datetime | None:
    """Hora de la lectura más antigua que conserva la nube, o None si no se pudo saber.

    Recorre el historial por páginas hasta la última incompleta. No es parte de la
    verificación: si falla, el alta sigue sin ese dato.
    """
    mas_antigua = None
    try:
        for pagina in range(1, PAGINAS_RECORRIDO_COMPLETO + 1):
            lecturas = fuente.historial(consultado, pagina, TAMANO_HISTORIAL)
            if lecturas:
                mas_antigua = min(lectura.hora_local for lectura in lecturas)
            if len(lecturas) < TAMANO_HISTORIAL:
                break
    except FuenteNoDisponible:
        return None
    return mas_antigua


def atender_verificacion(
    verificacion: VerificacionSensor, fuente: FuenteDeLecturas, cifrador: Cifrador
) -> None:
    """Pide el token con la MAC y deja el resultado para la pantalla del alta."""
    mac = secreto(cifrador, verificacion.mac_cifrada)
    try:
        resultado = fuente.obtener_token(mac)
    except FuenteNoDisponible as falla:
        verificacion.estado = (
            EstadoVerificacion.SIN_DATOS if falla.respondio else EstadoVerificacion.NUBE_NO_RESPONDE
        )
        verificacion.terminada_en = timezone.now()
        verificacion.save(update_fields=["estado", "terminada_en"])
        logger.info("Verificación %s: %s", verificacion.pk, falla.motivo)
        return

    consultado = SensorConsultado(id=0, mac=mac, token=resultado.token)
    verificacion.token_cifrado = cifrado(cifrador, resultado.token)
    verificacion.apodo_cifrado = cifrado(cifrador, resultado.apodo) if resultado.apodo else None
    if resultado.ultima is not None:
        verificacion.ultima_lectura_en = resultado.ultima.hora_local
        verificacion.ultima_lectura_resumen = resumen_de(resultado.ultima)
    verificacion.nube_conserva_desde = _lectura_mas_antigua(fuente, consultado)
    verificacion.estado = EstadoVerificacion.LISTA
    verificacion.terminada_en = timezone.now()
    verificacion.save(
        update_fields=[
            "token_cifrado",
            "apodo_cifrado",
            "ultima_lectura_en",
            "ultima_lectura_resumen",
            "nube_conserva_desde",
            "estado",
            "terminada_en",
        ]
    )
    logger.info("Verificación %s lista", verificacion.pk)


def vencer_verificaciones() -> int:
    """Las listas que nadie confirmó en 15 minutos ya no sirven para confirmar."""
    return VerificacionSensor.objects.filter(
        estado=EstadoVerificacion.LISTA,
        terminada_en__lt=timezone.now() - VIGENCIA_VERIFICACION,
    ).update(estado=EstadoVerificacion.VENCIDA)


def atender_verificaciones(fuente: FuenteDeLecturas, cifrador: Cifrador | None = None) -> int:
    cifrador = cifrador or Cifrador.desde_entorno()
    vencer_verificaciones()
    atendidas = 0
    while (verificacion := _tomar_verificacion()) is not None:
        atender_verificacion(verificacion, fuente, cifrador)
        atendidas += 1
    return atendidas


def _tomar_relleno() -> SolicitudRelleno | None:
    with transaction.atomic():
        solicitud = (
            SolicitudRelleno.objects.select_for_update(skip_locked=True)
            .select_related("sensor")
            .filter(estado=EstadoRelleno.PENDIENTE)
            .order_by("solicitada_en", "pk")
            .first()
        )
        if solicitud is None:
            return None
        solicitud.estado = EstadoRelleno.EN_CURSO
        solicitud.tomada_en = timezone.now()
        solicitud.save(update_fields=["estado", "tomada_en"])
    return solicitud


def atender_relleno(solicitud: SolicitudRelleno, lector: Lector) -> None:
    """Trae el historial del sensor hasta la fecha pedida (o hasta donde conserve la nube)."""
    resumen = lector.leer(
        solicitud.sensor,
        paginas=PAGINAS_RECORRIDO_COMPLETO,
        tamano=TAMANO_HISTORIAL,
        hasta=solicitud.desde,
    )
    solicitud.terminada_en = timezone.now()
    solicitud.lecturas_nuevas = resumen.nuevas
    if resumen.error:
        solicitud.estado = EstadoRelleno.FALLIDA
        solicitud.error = resumen.error[:300]
    else:
        solicitud.estado = EstadoRelleno.TERMINADA
        anotar_recorrido_completo(solicitud.sensor_id)
    solicitud.save(update_fields=["estado", "terminada_en", "lecturas_nuevas", "error"])
    logger.info(
        "Relleno %s del sensor %s: %s, %d lecturas nuevas",
        solicitud.pk,
        solicitud.sensor_id,
        solicitud.estado,
        resumen.nuevas,
    )


def atender_rellenos(lector: Lector) -> int:
    atendidas = 0
    while (solicitud := _tomar_relleno()) is not None:
        atender_relleno(solicitud, lector)
        atendidas += 1
    return atendidas
