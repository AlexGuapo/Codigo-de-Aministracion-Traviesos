"""Validaciones del alta de un sensor que no necesitan Django ni la base.

- La MAC se normaliza a 12 hexadecimales en mayúsculas y sin separadores
  (ADR «MAC y token protegidos»): así se cifra, así se saca su huella y así
  la pide el adaptador de EzData.
- El nombre corto es lo único que ve el público, así que no puede llevar el
  nombre del responsable ni la dirección (RNF-SEG-02, D-89, HU-012 cond. 4).

Los mensajes de error nunca repiten la MAC, el nombre ni la dirección que se
capturaron: pueden acabar en un log o en la pantalla de otro rol.
"""

from __future__ import annotations

import re
import unicodedata

# 12 hexadecimales, o 6 pares separados siempre por ":" o siempre por "-"
_FORMATO_MAC = re.compile(r"^[0-9A-F]{2}([:-]?)[0-9A-F]{2}(?:\1[0-9A-F]{2}){4}$")

# Palabras de una dirección o de un nombre que no identifican a nadie
_PALABRAS_COMUNES = frozenset(
    {
        "de", "del", "la", "las", "los", "el", "y", "e",
        "calle", "av", "avenida", "blvd", "boulevard", "calzada", "cda",
        "cerrada", "privada", "priv", "andador", "callejon", "prolongacion",
        "col", "colonia", "fracc", "fraccionamiento", "barrio", "num",
        "numero", "no", "int", "ext", "interior", "exterior", "esquina",
        "entre", "zacatecas", "guadalupe", "zac", "mexico", "cp",
    }
)  # fmt: skip

LARGO_MINIMO_PALABRA = 3
LARGO_NOMBRE_CORTO = (2, 10)

# Rectángulo que cubre los municipios de Zacatecas y Guadalupe: (latitud mín., latitud máx.,
# longitud mín., longitud máx.). Fuera de él solo se avisa; no se rechaza.
ZONA_ZACATECAS_GUADALUPE = (22.45, 23.05, -102.80, -102.15)


class MacInvalida(ValueError):
    """La MAC capturada no tiene el formato de un aparato."""


class NombreCortoInvalido(ValueError):
    """El nombre corto está vacío o lleva datos personales."""


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


def _sin_acentos(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def _compactar(texto: str) -> str:
    """Minúsculas, sin acentos y solo letras y números: «S-Pérez» -> «sperez»."""
    return re.sub(r"[^a-z0-9]", "", _sin_acentos(texto).lower())


def _palabras_que_identifican(texto: str) -> set[str]:
    palabras = re.findall(r"[a-z]+", _sin_acentos(texto or "").lower())
    return {
        p
        for p in palabras
        if len(p) >= LARGO_MINIMO_PALABRA and p not in _PALABRAS_COMUNES
    }


def validar_nombre_corto(
    nombre: str, *, nombre_responsable: str, direccion: str
) -> str:
    """Regresa el nombre corto sin espacios alrededor, o lanza el error.

    Se rechaza si contiene alguna palabra del nombre del responsable o de la
    dirección, aunque cambien las mayúsculas, los acentos o los separadores
    («S-Perez», «sPÉREZ», «Hidalgo1»). Los números de la dirección no se
    revisan: el nombre corto suele llevar uno («S-1»).
    """
    limpio = (nombre or "").strip()
    if not limpio:
        raise NombreCortoInvalido("Falta el nombre corto del sensor.")
    minimo, maximo = LARGO_NOMBRE_CORTO
    if not minimo <= len(limpio) <= maximo:
        raise NombreCortoInvalido(
            f"El nombre corto debe tener de {minimo} a {maximo} caracteres."
        )

    compacto = _compactar(limpio)
    if any(p in compacto for p in _palabras_que_identifican(nombre_responsable)):
        raise NombreCortoInvalido(
            "El nombre corto no puede llevar el nombre del responsable: "
            "lo ve el público."
        )
    if any(p in compacto for p in _palabras_que_identifican(direccion)):
        raise NombreCortoInvalido(
            "El nombre corto no puede llevar la dirección: lo ve el público."
        )
    return limpio


def fuera_de_la_zona(latitud: float, longitud: float) -> bool:
    lat_min, lat_max, lon_min, lon_max = ZONA_ZACATECAS_GUADALUPE
    return not (lat_min <= latitud <= lat_max and lon_min <= longitud <= lon_max)
