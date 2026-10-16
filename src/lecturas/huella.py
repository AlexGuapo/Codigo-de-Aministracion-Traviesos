"""Huella de los valores de una lectura.

Dos registros con la misma huella y la misma hora son la misma medición. La huella se calcula
con los valores ya interpretados, así el texto del firmware viejo y el objeto del nuevo dan la
misma huella para la misma medición.

No se cambia nunca después de guardar lecturas: con otra fórmula, una medición ya guardada
volvería a entrar como si fuera nueva.
"""

from __future__ import annotations

import hashlib
from typing import Any

CAMPOS_DE_LA_HUELLA = (
    "pm1_0",
    "pm2_5",
    "pm4_0",
    "pm10_0",
    "co2",
    "temperatura_sen55",
    "humedad_sen55",
    "temperatura_scd40",
    "humedad_scd40",
    "voc",
    "nox",
    "intervalo_s",
)


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return repr(int(valor))
    return repr(valor)


def huella_valores(lectura: Any) -> str:
    """SHA-256 en hexadecimal de los valores separados por `|`, en un orden fijo.

    Cada número se escribe con `repr()` (un flotante entero, sin el `.0`); un «sin dato», vacío.
    """
    texto = "|".join(_texto(getattr(lectura, campo)) for campo in CAMPOS_DE_LA_HUELLA)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()
