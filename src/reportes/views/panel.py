"""Panel del estado de la red: la primera pantalla del Administrador."""

from django.shortcuts import render
from django.utils import timezone

from cuentas.models import Rol
from cuentas.permisos import rol_requerido
from reportes.selectors import Estado, estado_red, hueco_mas_largo

FILTROS = {
    "todos": None,
    "transmitiendo": Estado.TRANSMITIENDO,
    "fuera": Estado.FUERA_DE_OPERACION,
}


def _corte_minutos(red) -> int | None:
    """El umbral de «sin transmitir» si todos los sensores con lecturas comparten el mismo."""
    umbrales = {sensor.umbral for sensor in red.sensores if sensor.ultima_lectura}
    if len(umbrales) != 1:
        return None
    return int(umbrales.pop().total_seconds() // 60)


def _barra_sin_lectura(sensor) -> int:
    """Qué tanto de la barra llena el tiempo sin lectura; el corte queda a la mitad."""
    if sensor is None or sensor.sin_lectura_desde is None:
        return 0
    return min(100, round(50 * sensor.sin_lectura_desde / sensor.umbral))


def _sensor_elegido(red, texto):
    try:
        elegido = int(texto)
    except (TypeError, ValueError):
        elegido = None
    for sensor in red.sensores:
        if sensor.id == elegido:
            return sensor
    return red.sensores[0] if red.sensores else None


@rol_requerido(Rol.ADMINISTRADOR)
def panel_red(request):
    """La página completa; con HTMX, solo su contenido.

    Elegir un sensor, cambiar de filtro y la actualización automática de cada 15 min piden el
    contenido con el filtro y el sensor en la dirección, así ninguno de los tres pierde a los otros.
    """
    ahora = timezone.now()
    red = estado_red(ahora)
    filtro = request.GET.get("filtro", "todos")
    if filtro not in FILTROS:
        filtro = "todos"
    elegido = _sensor_elegido(red, request.GET.get("sensor"))
    visibles = [
        sensor
        for sensor in red.sensores
        if FILTROS[filtro] is None or sensor.estado == FILTROS[filtro]
    ]
    contexto = {
        "seccion": "panel",
        "red": red,
        "hoy": ahora.date(),
        "filtro": filtro,
        "visibles": visibles,
        "elegido": elegido,
        "hueco": hueco_mas_largo(elegido.id, ahora) if elegido else None,
        "barra_sin_lectura": _barra_sin_lectura(elegido),
        "corte_min": _corte_minutos(red),
        "conteos": {
            "todos": len(red.sensores),
            "transmitiendo": len(red.transmitiendo),
            "fuera": len(red.fuera_de_operacion),
        },
    }
    if request.headers.get("HX-Request") == "true":
        return render(request, "reportes/_panel_contenido.html", contexto)
    return render(request, "reportes/panel.html", contexto)
