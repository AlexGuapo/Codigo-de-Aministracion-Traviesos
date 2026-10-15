"""Reporte diario.

Por ahora muestra las gráficas con lecturas de ejemplo generadas aquí mismo; la consulta real a
las lecturas guardadas, la tabla de promedios y los periodos sin transmitir llegan después.
"""

import math
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from django.shortcuts import render

from reportes.formato import fecha_larga
from reportes.series import graficas_del_reporte

INTERVALO_EJEMPLO_S = 1800


def _lecturas_de_ejemplo(dia: date, desfase_min: int, hasta: datetime | None, base: float):
    """Lecturas inventadas cada ~29 min, con la forma de un día real (más alto de madrugada)."""
    lecturas = []
    hora = datetime.combine(dia, datetime.min.time()) + timedelta(minutes=desfase_min)
    fin = datetime.combine(dia + timedelta(days=1), datetime.min.time())
    while hora < fin and (hasta is None or hora <= hasta):
        onda = 1 + 0.6 * math.cos((hora.hour + hora.minute / 60 - 3) / 24 * 2 * math.pi)
        pm1 = base * onda
        lecturas.append(
            SimpleNamespace(
                hora=hora,
                intervalo_s=INTERVALO_EJEMPLO_S,
                pm1_0=pm1,
                pm2_5=pm1 * 1.3,
                pm4_0=pm1 * 1.5,
                pm10_0=pm1 * 1.6,
                co2=480 + 60 * onda,
            )
        )
        hora += timedelta(minutes=29, seconds=7)
    return lecturas


def _a_las(dia: date, hora: int, minuto: int) -> datetime:
    return datetime.combine(dia, datetime.min.time()) + timedelta(hours=hora, minutes=minuto)


def _dia_pedido(texto: str | None) -> date:
    ayer = date.today() - timedelta(days=1)
    if not texto:
        return ayer
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return ayer


def reporte_diario(request):
    dia = _dia_pedido(request.GET.get("fecha"))
    sensores = [
        ("S-1", _lecturas_de_ejemplo(dia, 12, None, 4.0)),
        ("S-2", _lecturas_de_ejemplo(dia, 3, _a_las(dia, 3, 10), 6.5)),
    ]
    contexto = {
        "seccion": "reportes",
        "dia": dia,
        "titulo_dia": fecha_larga(dia),
        "sensores": [nombre for nombre, _ in sensores],
        "graficas": graficas_del_reporte(sensores),
        "es_ejemplo": True,
    }
    return render(request, "reportes/diario.html", contexto)
