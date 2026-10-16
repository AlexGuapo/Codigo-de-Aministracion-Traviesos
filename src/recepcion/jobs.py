"""Tareas programadas de la recepción (grupo de hilos `recepcion`)."""

from __future__ import annotations

import functools
import logging
from datetime import datetime

from django.db import close_old_connections

from recepcion import alta, services

logger = logging.getLogger("recepcion")

_fuente = None


def _fuente_del_worker():
    """Una sola fuente para todo el proceso (con el archivo, todas las tareas ven la misma hora)."""
    global _fuente
    if _fuente is None:
        _fuente = services.fuente_configurada()
    return _fuente


def _tarea(funcion):
    """Cada ejecución usa una conexión sana a la base. Un error queda en el log y no detiene al
    programador."""

    @functools.wraps(funcion)
    def envoltura():
        close_old_connections()
        try:
            funcion()
        except Exception:
            logger.exception("La tarea %s falló", funcion.__name__)
        finally:
            close_old_connections()

    return envoltura


@_tarea
def sondeo():
    services.sondear(services.Lector(_fuente_del_worker()))


@_tarea
def historial_diario():
    services.leer_historial_diario(services.Lector(_fuente_del_worker()))


@_tarea
def conciliacion():
    services.conciliar(services.Lector(_fuente_del_worker()))


@_tarea
def verificaciones():
    alta.atender_verificaciones(_fuente_del_worker())


@_tarea
def rellenos():
    alta.atender_rellenos(services.Lector(_fuente_del_worker()))


def registrar(programador, grupo: str) -> None:
    """Agrega al programador las tareas de la recepción, todas con `executor=grupo`."""
    programador.add_job(
        sondeo, "interval", minutes=15, next_run_time=datetime.now(), id="sondeo", executor=grupo
    )
    programador.add_job(
        historial_diario, "cron", hour=2, minute=10, id="historial_diario", executor=grupo
    )
    programador.add_job(
        conciliacion,
        "cron",
        day_of_week="sun",
        hour=3,
        minute=10,
        id="conciliacion",
        executor=grupo,
    )
    programador.add_job(verificaciones, "interval", seconds=3, id="verificaciones", executor=grupo)
    programador.add_job(rellenos, "interval", seconds=10, id="rellenos", executor=grupo)
