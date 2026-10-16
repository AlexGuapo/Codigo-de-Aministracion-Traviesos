"""Entrada a la cola de recálculo.

Es la única forma en que otro módulo pide que se recalcule una hora: quien guarda una lectura o
cataloga una la llama dentro de su propia transacción, así la lectura y su marca se guardan
juntas o no se guarda ninguna. Ningún otro módulo escribe en las tablas del cálculo.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from calculo.models import CausaRecalculo, MarcaRecalculo

# Una hora se cierra a los 20 minutos de la siguiente; lo que llega después es atrasado.
GRACIA_CIERRE_HORA = timedelta(minutes=20)


def inicio_de_hora(momento: datetime) -> datetime:
    return momento.replace(minute=0, second=0, microsecond=0)


def causa_por_llegada(hora: datetime, ahora: datetime) -> CausaRecalculo:
    """Lectura nueva si su hora todavía no cierra; atrasada si ya cerró."""
    if ahora > inicio_de_hora(hora) + timedelta(hours=1) + GRACIA_CIERRE_HORA:
        return CausaRecalculo.LECTURA_ATRASADA
    return CausaRecalculo.LECTURA_NUEVA


def marcar_recalculo(sensor_id: int, hora: datetime, causa: CausaRecalculo) -> None:
    """Deja pendiente el recálculo de la hora a la que pertenece `hora`."""
    MarcaRecalculo.objects.create(sensor_id=sensor_id, hora=inicio_de_hora(hora), causa=causa)
