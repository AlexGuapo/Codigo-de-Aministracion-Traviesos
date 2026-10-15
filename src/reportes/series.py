"""Series de las gráficas de los reportes: una por sensor y por variable.

Cada serie lleva todas las lecturas del día. Donde el sensor dejó de transmitir se agrega un
punto sin valor para que la línea se corte, en lugar de unir dos lecturas lejanas como si
hubiera datos entre ellas. Una lectura «sin dato» también corta la línea; nunca se dibuja como 0.

El mismo formato sirve para Chart.js en la página:
`{"variable": "pm25", "unidad": "µg/m³", "series": [{"sensor": "G3", "puntos": [[hora, valor]]}]}`
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from calculo.dominio.operacion import hay_hueco
from calculo.dominio.redondeo import a_un_decimal


@dataclass(frozen=True, slots=True)
class VariableDeReporte:
    campo: str  # nombre del campo en la lectura
    clave: str  # nombre corto que viaja a la página
    etiqueta: str
    unidad: str


VARIABLES_REPORTE = (
    VariableDeReporte("pm1_0", "pm1", "PM1", "µg/m³"),
    VariableDeReporte("pm2_5", "pm25", "PM2.5", "µg/m³"),
    VariableDeReporte("pm4_0", "pm4", "PM4", "µg/m³"),
    VariableDeReporte("pm10_0", "pm10", "PM10", "µg/m³"),
    VariableDeReporte("co2", "co2", "CO2", "ppm"),
)


class LecturaDeSerie(Protocol):
    """Lo que la serie necesita de una lectura: su hora, su intervalo y sus valores."""

    hora: datetime
    intervalo_s: int | None


Punto = list[Any]  # [hora en ISO, valor o None]


def _iso(hora: datetime) -> str:
    return hora.replace(microsecond=0).isoformat()


def puntos_de_la_serie(lecturas: Iterable[LecturaDeSerie], campo: str) -> list[Punto]:
    """Puntos de un sensor para una variable, con un punto vacío en cada hueco.

    Las lecturas deben ser de un solo sensor y ya sin copias.
    """
    puntos: list[Punto] = []
    anterior = None
    for lectura in sorted(lecturas, key=lambda lectura: lectura.hora):
        if anterior is not None and hay_hueco(anterior.hora, lectura.hora, anterior.intervalo_s):
            mitad = anterior.hora + (lectura.hora - anterior.hora) / 2
            puntos.append([_iso(mitad), None])
        valor = getattr(lectura, campo)
        puntos.append([_iso(lectura.hora), None if valor is None else float(a_un_decimal(valor))])
        anterior = lectura
    return puntos


def graficas_del_reporte(
    lecturas_por_sensor: Sequence[tuple[str, Sequence[LecturaDeSerie]]],
) -> list[dict[str, Any]]:
    """Una gráfica por variable del reporte, con una serie por sensor en el orden recibido.

    `lecturas_por_sensor` es una lista de (nombre corto, lecturas). Un sensor sin lecturas no
    lleva serie.
    """
    graficas = []
    for variable in VARIABLES_REPORTE:
        series = [
            {"sensor": nombre, "puntos": puntos_de_la_serie(lecturas, variable.campo)}
            for nombre, lecturas in lecturas_por_sensor
            if lecturas
        ]
        graficas.append(
            {
                "variable": variable.clave,
                "etiqueta": variable.etiqueta,
                "unidad": variable.unidad,
                "series": series,
            }
        )
    return graficas
