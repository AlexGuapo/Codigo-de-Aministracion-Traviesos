"""Interfaz de la fuente de lecturas.

Todo el sistema habla con `FuenteDeLecturas`; solo los adaptadores de
`recepcion/adapters/` saben cómo responde la nube real (rutas, hora UTC+8,
formatos del campo `value`). Aquí no se importa Django.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class Ruta(StrEnum):
    """Por dónde llegó la lectura."""

    HISTORIAL = "history"
    ULTIMA = "dataMacByKey"


class Origen(StrEnum):
    NUBE = "nube"
    HISTORICO = "historico"


@dataclass(frozen=True, slots=True)
class SensorConsultado:
    """Lo que un adaptador necesita para consultar un sensor.

    La MAC y el token van descifrados, así que no salen en el repr
    (por si alguien hace print o log del objeto).
    """

    id: int
    mac: str = field(repr=False)
    token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class LecturaNormalizada:
    """Una lectura ya interpretada, lista para `registrar_lectura`.

    Los valores van tal como llegaron (sin redondear). `None` significa
    «sin dato»; con batería el VOC llega en 0 y el adaptador ya lo pasa a None.
    """

    sensor_id: int  # 0 si el sensor todavía no existe (la última lectura del alta)
    hora_local: datetime  # sin zona, hora de Zacatecas
    hora_nube: str  # tal cual la dio la nube (texto UTC+8 o segundos Unix)
    ruta: Ruta
    crudo: str  # el campo value tal como llegó, sin el token
    intervalo_s: int | None  # sleep_interval; None si no vino
    pm1_0: float | None
    pm2_5: float | None
    pm4_0: float | None
    pm10_0: float | None
    co2: float | None
    temperatura_sen55: float | None
    humedad_sen55: float | None
    temperatura_scd40: float | None
    humedad_scd40: float | None
    voc: float | None
    nox: float | None
    origen: Origen = Origen.NUBE


@dataclass(frozen=True, slots=True)
class ResultadoToken:
    """Respuesta de `obtener_token`, la usa la verificación del alta."""

    token: str = field(repr=False)
    apodo: str | None
    ultima: LecturaNormalizada | None


class FuenteNoDisponible(Exception):
    """La fuente no respondió o respondió con error.

    Solo lleva el motivo y el id del sensor: nunca la URL, la MAC ni el token.
    `respondio` distingue una nube que contestó con error o sin datos (un token
    que cambió, una MAC que no existe) de una que no contestó.
    """

    def __init__(
        self, motivo: str, sensor_id: int | None = None, *, respondio: bool = False
    ) -> None:
        self.motivo = motivo
        self.sensor_id = sensor_id
        self.respondio = respondio
        if sensor_id is None:
            super().__init__(motivo)
        else:
            super().__init__(f"sensor {sensor_id}: {motivo}")


class FuenteDeLecturas(Protocol):
    """Las tres operaciones lanzan `FuenteNoDisponible` si algo sale mal."""

    def historial(
        self, sensor: SensorConsultado, pagina: int, tamano: int
    ) -> list[LecturaNormalizada]:
        """Una página del historial, de la más reciente a la más antigua.

        El sondeo pide la página 1 con 5 lecturas; el historial diario,
        páginas de 50.
        """
        ...

    def ultima_lectura(self, sensor: SensorConsultado) -> LecturaNormalizada: ...

    def obtener_token(self, mac: str) -> ResultadoToken: ...
