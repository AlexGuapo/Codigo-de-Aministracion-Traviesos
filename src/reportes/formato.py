"""Formato de fechas de los reportes, sin depender del idioma instalado en el servidor."""

from __future__ import annotations

from datetime import date

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def fecha_larga(fecha: date) -> str:
    """`date(2025, 12, 1)` → «lunes 1 de diciembre de 2025»."""
    return f"{DIAS[fecha.weekday()]} {fecha.day} de {MESES[fecha.month - 1]} de {fecha.year}"


def mes_largo(anio: int, mes: int) -> str:
    """`(2026, 9)` → «septiembre de 2026»."""
    return f"{MESES[mes - 1]} de {anio}"
