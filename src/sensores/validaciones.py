"""Validaciones del alta de un sensor que no necesitan Django ni la base.

- La MAC se normaliza a 12 hexadecimales en mayúsculas y sin separadores
  (ADR «MAC y token protegidos»): así se cifra, así se saca su huella y así
  la pide el adaptador de EzData.

Los mensajes de error nunca repiten la MAC que se capturó: pueden acabar en
un log o en la pantalla de otro rol.
"""

from __future__ import annotations

import re

# 12 hexadecimales, o 6 pares separados siempre por ":" o siempre por "-"
_FORMATO_MAC = re.compile(r"^[0-9A-F]{2}([:-]?)[0-9A-F]{2}(?:\1[0-9A-F]{2}){4}$")


class MacInvalida(ValueError):
    """La MAC capturada no tiene el formato de un aparato."""


def normalizar_mac(texto: str) -> str:
    """Regresa la MAC como 12 hexadecimales en mayúsculas.

    Acepta `AA:BB:CC:DD:EE:FF`, `AA-BB-CC-DD-EE-FF` o `AABBCCDDEEFF`, en
    mayúsculas o minúsculas y con espacios alrededor.
    """
    limpio = (texto or "").strip().upper()
    if not _FORMATO_MAC.match(limpio):
        raise MacInvalida(
            "La MAC debe tener 12 caracteres hexadecimales (0-9 y A-F), con o sin «:»."
        )
    return limpio.replace(":", "").replace("-", "")
