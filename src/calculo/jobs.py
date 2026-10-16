"""Tareas programadas del cálculo (grupo de hilos `calculo`)."""

from __future__ import annotations

import functools
import logging

from django.db import close_old_connections

from calculo import services

logger = logging.getLogger("calculo")


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
def cola_recalculo():
    # Una vuelta atiende un lote; si quedan marcas, sigue hasta vaciar la cola.
    while services.procesar_cola() == services.LOTE_COLA:
        pass


@_tarea
def cierre_hora():
    services.cerrar_hora()


@_tarea
def cierre_dia():
    services.cerrar_dia()


@_tarea
def cierre_mes():
    services.cerrar_mes()


def registrar(programador, grupo: str) -> None:
    """Agrega al programador las tareas del cálculo, todas con `executor=grupo`."""
    programador.add_job(cola_recalculo, "interval", minutes=1, id="cola_recalculo", executor=grupo)
    programador.add_job(cierre_hora, "cron", minute=20, id="cierre_hora", executor=grupo)
    programador.add_job(cierre_dia, "cron", hour=0, minute=30, id="cierre_dia", executor=grupo)
    programador.add_job(
        cierre_mes, "cron", day=1, hour=0, minute=45, id="cierre_mes", executor=grupo
    )
