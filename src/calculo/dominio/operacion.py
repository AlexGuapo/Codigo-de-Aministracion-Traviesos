"""Cuándo un sensor dejó de transmitir.

Un sensor está «Fuera de operación» cuando le faltan dos lecturas seguidas: pasaron más de
`2 × intervalo + 5 min` desde la última. Los 5 minutos cubren que un ciclo real dura unos
segundos más o menos que su intervalo. Si la última lectura no trae intervalo, el umbral es fijo
de 65 minutos, el que da el ciclo actual de 30 minutos.

La misma regla corta las líneas de las gráficas y marca los periodos sin transmitir de los
reportes.
"""

from __future__ import annotations

from datetime import datetime, timedelta

MARGEN = timedelta(minutes=5)
UMBRAL_SIN_INTERVALO = timedelta(minutes=65)


def umbral_sin_transmitir(intervalo_s: int | None) -> timedelta:
    if intervalo_s is None:
        return UMBRAL_SIN_INTERVALO
    return 2 * timedelta(seconds=intervalo_s) + MARGEN


def hay_hueco(anterior: datetime, siguiente: datetime, intervalo_s: int | None) -> bool:
    """True si entre dos lecturas seguidas el sensor estuvo sin transmitir.

    `intervalo_s` es el de la lectura anterior.
    """
    return siguiente - anterior > umbral_sin_transmitir(intervalo_s)


def fuera_de_operacion(ultima: datetime | None, intervalo_s: int | None, ahora: datetime) -> bool:
    """True si el sensor ya pasó su umbral sin lecturas. Sin ninguna lectura, no se decide aquí."""
    if ultima is None:
        return False
    return hay_hueco(ultima, ahora, intervalo_s)
