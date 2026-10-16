from django import template

from calculo.dominio.redondeo import a_entero
from reportes import formato

register = template.Library()


@register.filter
def duracion(tiempo):
    return "" if tiempo is None else formato.duracion(tiempo)


@register.filter
def duracion_larga(tiempo):
    return "" if tiempo is None else formato.duracion_larga(tiempo)


@register.filter
def momento(hora, hoy):
    return "" if hora is None else formato.momento(hora, hoy)


@register.filter
def dia_corto(fecha):
    return formato.dia_corto(fecha)


@register.filter
def entero(valor):
    """Un valor calculado tal como se informa: entero, con los 5 hacia arriba."""
    return "" if valor is None else a_entero(valor)


@register.filter
def minutos(tiempo):
    """Un umbral en minutos: «65 min»."""
    return "" if tiempo is None else f"{int(tiempo.total_seconds() // 60)} min"
