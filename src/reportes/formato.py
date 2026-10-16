"""Formato de fechas de los reportes, sin depender del idioma instalado en el servidor."""

from __future__ import annotations

from datetime import date, datetime, timedelta

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


MESES_CORTOS = tuple(mes[:3] for mes in MESES)


def duracion(tiempo: timedelta) -> str:
    """`timedelta(minutes=166)` → «2 h 46 min»; desde un día, días y horas («1 d 13 h»)."""
    minutos = int(tiempo.total_seconds() // 60)
    dias, minutos = divmod(minutos, 24 * 60)
    horas, minutos = divmod(minutos, 60)
    if dias:
        return f"{dias} d {horas} h" if horas else f"{dias} d"
    if horas:
        return f"{horas} h {minutos} min" if minutos else f"{horas} h"
    return f"{minutos} min"


def duracion_larga(tiempo: timedelta) -> str:
    """Para huecos: «12 días», «1 día», o en horas y minutos si no llega a un día."""
    dias = tiempo.days
    if dias >= 1:
        return f"{dias} día" if dias == 1 else f"{dias} días"
    return duracion(tiempo)


def momento(hora: datetime, hoy: date) -> str:
    """«Hoy, 19:42», «Ayer, 23:10» o «13 oct, 06:30»."""
    if hora.date() == hoy:
        return f"Hoy, {hora:%H:%M}"
    if hora.date() == hoy - timedelta(days=1):
        return f"Ayer, {hora:%H:%M}"
    return f"{hora.day} {MESES_CORTOS[hora.month - 1]}, {hora:%H:%M}"


def dia_corto(fecha: date) -> str:
    """`date(2026, 10, 14)` → «14 oct»."""
    return f"{fecha.day} {MESES_CORTOS[fecha.month - 1]}"
