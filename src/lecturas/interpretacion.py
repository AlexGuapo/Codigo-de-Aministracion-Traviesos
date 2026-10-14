"""Interpretación del campo `value` que manda el sensor.

El firmware viejo (v0.1) lo manda como texto JSON, a veces escapado dos o
tres veces; el nuevo (v0.2) como objeto. Adentro los dos traen lo mismo:
`sen55`, `scd40`, `rtc` y `profile`.

Aquí no hay red ni Django: se usa igual para la nube y, más adelante, para
cargar el histórico.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

MAX_NIVELES = 5

# campo de LecturaNormalizada -> (bloque, clave dentro del bloque)
CAMPOS = {
    "pm1_0": ("sen55", "pm1.0"),
    "pm2_5": ("sen55", "pm2.5"),
    "pm4_0": ("sen55", "pm4.0"),
    "pm10_0": ("sen55", "pm10.0"),
    "co2": ("scd40", "co2"),
    "temperatura_sen55": ("sen55", "temperature"),
    "humedad_sen55": ("sen55", "humidity"),
    "temperatura_scd40": ("scd40", "temperature"),
    "humedad_scd40": ("scd40", "humidity"),
    "voc": ("sen55", "voc"),
    "nox": ("sen55", "nox"),
}


class FormatoNoReconocido(ValueError):
    """El valor no se pudo leer como una lectura del sensor."""


@dataclass(frozen=True, slots=True)
class ValorInterpretado:
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
    intervalo_s: int | None
    apodo: str | None


def _desenvolver(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    actual = value
    niveles = 0
    while isinstance(actual, str):
        niveles += 1
        if niveles > MAX_NIVELES:
            raise FormatoNoReconocido("demasiados niveles de texto")
        try:
            actual = json.loads(actual)
        except json.JSONDecodeError:
            # comillas escapadas sin estar dentro de una cadena: {\"sen55\":...}
            try:
                actual = json.loads('"' + actual + '"')
            except json.JSONDecodeError:
                raise FormatoNoReconocido("el valor no es JSON") from None
    if not isinstance(actual, dict):
        raise FormatoNoReconocido("el valor no es un objeto")
    return actual


def _numero(x: Any) -> float | None:
    # bool es subclase de int, pero True no es una medición
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return float(x)


def _bloque(valor: dict, nombre: str) -> dict:
    bloque = valor.get(nombre)
    return bloque if isinstance(bloque, dict) else {}


def interpretar_valor(value: Any) -> ValorInterpretado:
    """Convierte `value` (texto u objeto) en variables con `None` = sin dato.

    Con batería el VOC llega en 0 y el NOx en null: los dos son «sin dato».
    """
    valor = _desenvolver(value)
    if not isinstance(valor.get("sen55"), dict) and not isinstance(
        valor.get("scd40"), dict
    ):
        raise FormatoNoReconocido("no trae sen55 ni scd40")

    variables = {
        campo: _numero(_bloque(valor, bloque).get(clave))
        for campo, (bloque, clave) in CAMPOS.items()
    }
    if variables["voc"] == 0:
        variables["voc"] = None

    intervalo = _bloque(valor, "rtc").get("sleep_interval")
    if (
        isinstance(intervalo, bool)
        or not isinstance(intervalo, (int, float))
        or intervalo <= 0
    ):
        intervalo = None
    else:
        intervalo = int(intervalo)

    apodo = _bloque(valor, "profile").get("nickname")
    apodo = apodo if isinstance(apodo, str) else None

    return ValorInterpretado(**variables, intervalo_s=intervalo, apodo=apodo)


def crudo_de(value: Any) -> str:
    """El valor tal como llegó, para guardarlo como dato crudo.

    Si es texto se regresa idéntico. Si ya viene como objeto no hay bytes
    originales, así que se serializa en forma compacta.
    """
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
