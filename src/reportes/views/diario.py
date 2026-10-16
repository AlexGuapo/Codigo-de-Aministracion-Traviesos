"""Reporte diario: se arma al abrirlo, con los datos de ese momento."""

from datetime import date, timedelta
from urllib.parse import urlencode

from django.shortcuts import render
from django.utils import timezone

from cuentas.models import Rol
from cuentas.permisos import rol_requerido
from reportes.reporte_diario import armar_reporte_diario
from sensores.models import EstadoSensor, Sensor


def dia_pedido(texto: str | None, hoy: date) -> date:
    """El día pedido; por omisión (o si no se entiende), el último día completo."""
    ayer = hoy - timedelta(days=1)
    try:
        dia = date.fromisoformat(texto) if texto else ayer
    except ValueError:
        return ayer
    return min(dia, hoy)


def sensores_pedidos(ids: list[str]) -> tuple[list[Sensor], list[Sensor]]:
    """Todos los sensores para elegir y los elegidos; sin elegir, los activos."""
    todos = list(Sensor.objects.order_by("nombre_corto"))
    elegidos = [sensor for sensor in todos if str(sensor.pk) in ids]
    if not elegidos:
        elegidos = [sensor for sensor in todos if sensor.estado == EstadoSensor.ACTIVO]
    return todos, elegidos


def _enlace(dia: date, elegidos: list[Sensor]) -> str:
    return "?" + urlencode([("fecha", dia.isoformat())] + [("sensores", s.pk) for s in elegidos])


@rol_requerido(Rol.ADMINISTRADOR)
def reporte_diario(request):
    ahora = timezone.now()
    dia = dia_pedido(request.GET.get("fecha"), ahora.date())
    todos, elegidos = sensores_pedidos(request.GET.getlist("sensores"))
    contexto = {
        "seccion": "reportes",
        "dia": dia,
        "todos": todos,
        "elegidos": {sensor.pk for sensor in elegidos},
        "reporte": armar_reporte_diario(dia, elegidos, ahora),
        "dia_anterior": _enlace(dia - timedelta(days=1), elegidos),
        "dia_siguiente": _enlace(dia + timedelta(days=1), elegidos) if dia < ahora.date() else None,
    }
    return render(request, "reportes/diario.html", contexto)
