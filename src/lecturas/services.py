"""Registro de lecturas: el único lugar del sistema que las escribe."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from django.db import connection, transaction
from django.utils import timezone

from calculo.cola import causa_por_llegada, marcar_recalculo
from lecturas.huella import huella_valores
from lecturas.models import Lectura, OrigenLectura
from recepcion.ports import LecturaNormalizada, Origen
from sensores.models import Sensor

logger = logging.getLogger("lecturas")

# Espacio de nombres del bloqueo por sensor, para no chocar con otros bloqueos de la base.
BLOQUEO_LECTURAS = 7301
UMBRAL_COPIA = timedelta(seconds=30)


class Resultado(StrEnum):
    GUARDADA = "guardada"
    COPIA_DISCREPANTE = "copia_discrepante"
    REPETIDA = "repetida"
    COPIA_IDENTICA = "copia_identica"
    FUERA_DE_FECHA = "fuera_de_fecha"


@dataclass(frozen=True, slots=True)
class Registro:
    resultado: Resultado
    lectura_id: int | None = None


def _umbral_de_copia(intervalo_s: int | None) -> timedelta:
    """Dos registros más cercanos que esto son la misma medición enviada dos veces."""
    if intervalo_s is None:
        return UMBRAL_COPIA
    return min(UMBRAL_COPIA, timedelta(seconds=intervalo_s) / 2)


def registrar_lectura(lectura: LecturaNormalizada) -> Registro:
    """Guarda una lectura sin repetir ninguna, aunque se lea varias veces la misma.

    En una sola transacción, con un bloqueo por sensor para que dos hilos no escriban a la vez
    lecturas del mismo sensor:

    - Antes de la fecha desde la que se reciben lecturas del sensor, no se guarda.
    - La misma hora con los mismos valores ya está guardada: no se guarda.
    - Otro registro a menos de mín(30 s, intervalo / 2) es la misma medición enviada dos veces.
      Con los mismos valores no se guarda; con valores distintos se guardan los dos, ligados.
      Cuál cuenta en los cálculos (la de hora más temprana) se decide al calcular.
    - Se deja una marca para recalcular su hora, en la misma transacción.

    El estado de la consulta a la nube no se toca aquí: lo actualiza la recepción, que llama a
    esta función dentro de su propia transacción.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)", [BLOQUEO_LECTURAS, lectura.sensor_id]
            )

        sensor = Sensor.objects.only("lecturas_desde").get(pk=lectura.sensor_id)
        if lectura.hora_local.date() < sensor.lecturas_desde:
            return Registro(Resultado.FUERA_DE_FECHA)

        huella = huella_valores(lectura)
        if Lectura.objects.filter(
            sensor_id=lectura.sensor_id, hora=lectura.hora_local, huella_valores=huella
        ).exists():
            return Registro(Resultado.REPETIDA)

        umbral = _umbral_de_copia(lectura.intervalo_s)
        cercanas = list(
            Lectura.objects.filter(
                sensor_id=lectura.sensor_id,
                hora__gt=lectura.hora_local - umbral,
                hora__lt=lectura.hora_local + umbral,
            ).order_by("hora", "id")
        )
        if any(cercana.huella_valores == huella for cercana in cercanas):
            return Registro(Resultado.COPIA_IDENTICA)

        original = None
        if cercanas:
            primera = cercanas[0]
            original = primera.copia_discrepante_de_id or primera.pk

        nueva = Lectura.objects.create(
            sensor_id=lectura.sensor_id,
            hora=lectura.hora_local,
            hora_nube_original=lectura.hora_nube,
            ruta=str(lectura.ruta),
            origen=OrigenLectura.NUBE if lectura.origen == Origen.NUBE else OrigenLectura.HISTORICO,
            pm1_0=lectura.pm1_0,
            pm2_5=lectura.pm2_5,
            pm4_0=lectura.pm4_0,
            pm10_0=lectura.pm10_0,
            co2=lectura.co2,
            temperatura_sen55=lectura.temperatura_sen55,
            humedad_sen55=lectura.humedad_sen55,
            temperatura_scd40=lectura.temperatura_scd40,
            humedad_scd40=lectura.humedad_scd40,
            voc=lectura.voc,
            nox=lectura.nox,
            intervalo_s=lectura.intervalo_s,
            huella_valores=huella,
            crudo=lectura.crudo,
            copia_discrepante_de_id=original,
        )

        marcar_recalculo(
            lectura.sensor_id,
            lectura.hora_local,
            causa_por_llegada(lectura.hora_local, timezone.now()),
        )

    if original is not None:
        logger.warning(
            "Sensor %s: copia con valores distintos a las %s", lectura.sensor_id, lectura.hora_local
        )
        return Registro(Resultado.COPIA_DISCREPANTE, nueva.pk)
    return Registro(Resultado.GUARDADA, nueva.pk)
