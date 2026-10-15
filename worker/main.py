"""Proceso de fondo de SARRCA (contenedor `worker`).

Un solo proceso con dos grupos de hilos separados, para que el cálculo no frene la recepción:

- `recepcion`: el único que habla con EzData (sondeo, historial, conciliación, verificaciones).
- `calculo`: cola de recálculo y cierres de hora, día y mes.

Cada módulo declara sus tareas en su `jobs.py` con una función `registrar(programador, grupo)`.
Este archivo solo arranca el programador; para agregar una tarea no hay que tocarlo.

Uso: `python worker/main.py`
"""

import logging
import os
import signal
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from apscheduler.executors.pool import ThreadPoolExecutor  # noqa: E402
from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402

from calculo import jobs as jobs_calculo  # noqa: E402
from recepcion import jobs as jobs_recepcion  # noqa: E402

ZONA = ZoneInfo("America/Mexico_City")  # explícita, aunque el servidor esté en UTC
GRUPO_RECEPCION = "recepcion"
GRUPO_CALCULO = "calculo"

log = logging.getLogger("worker")


def crear_programador() -> BlockingScheduler:
    """Arma el programador con los dos grupos de hilos y las tareas de cada módulo.

    Ninguna tarea corre dos veces a la vez (`max_instances=1`) y, si se atrasó, se ejecuta una
    sola vez en lugar de ponerse al corriente con todas las que perdió (`coalesce=True`).
    """
    programador = BlockingScheduler(
        timezone=ZONA,
        executors={
            GRUPO_RECEPCION: ThreadPoolExecutor(max_workers=4),
            GRUPO_CALCULO: ThreadPoolExecutor(max_workers=2),
        },
        job_defaults={"max_instances": 1, "coalesce": True, "misfire_grace_time": 300},
    )
    jobs_recepcion.registrar(programador, GRUPO_RECEPCION)
    jobs_calculo.registrar(programador, GRUPO_CALCULO)
    return programador


def main() -> None:
    programador = crear_programador()

    def detener(signum, _frame):
        log.info("Señal %s recibida; deteniendo el worker", signum)
        programador.shutdown(wait=True)

    signal.signal(signal.SIGTERM, detener)
    signal.signal(signal.SIGINT, detener)

    tareas = programador.get_jobs()
    log.info("Worker iniciado con %d tareas: %s", len(tareas), ", ".join(t.id for t in tareas))
    programador.start()


if __name__ == "__main__":
    main()
