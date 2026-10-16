"""Reporte mensual: la portada con los valores del mes y una lámina por día, armada al pedirla."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from django.shortcuts import render
from django.utils import timezone

from calculo.dominio.tipos import ResultadoMes, TipoParametro, Variable
from calculo.models import MarcaRecalculo
from calculo.selectors import parametro_vigente
from calculo.services import resultados_mes
from cuentas.models import Rol
from cuentas.permisos import rol_requerido
from reportes.formato import dia_corto, mes_largo
from reportes.reporte_diario import armar_reporte_diario, dias_con_lecturas
from reportes.series import VARIABLES_REPORTE
from reportes.views.diario import dia_pedido, sensores_pedidos

CON_LIMITE = (("PM2.5", Variable.PM25), ("PM10", Variable.PM10))


def mes_pedido(texto: str | None, hoy: date) -> tuple[int, int]:
    """El mes pedido como (año, mes); por omisión, o si no se entiende, el último mes completo."""
    anterior = hoy.replace(day=1) - timedelta(days=1)
    try:
        anio, mes = (int(parte) for parte in (texto or "").split("-"))
        date(anio, mes, 1)
    except ValueError:
        return anterior.year, anterior.month
    if (anio, mes) > (hoy.year, hoy.month):
        return hoy.year, hoy.month
    return anio, mes


@dataclass(frozen=True, slots=True)
class CeldaMes:
    resultado: ResultadoMes
    dias_del_mes: int
    unidad: str

    @property
    def texto(self) -> str:
        """«23 µg/m³ (24 de 31 días válidos)» o «sin días válidos»."""
        if self.resultado.promedio_entero is None:
            return "sin días válidos"
        return (
            f"{self.resultado.promedio_entero} {self.unidad} "
            f"({self.resultado.dias_validos} de {self.dias_del_mes} días válidos)"
        )


def _lista_de_dias(fechas: tuple[date, ...]) -> str:
    """(5, 12 y 20 de octubre) como «5 oct, 12 oct y 20 oct»."""
    textos = [dia_corto(fecha) for fecha in fechas]
    if len(textos) < 2:
        return "".join(textos)
    return ", ".join(textos[:-1]) + " y " + textos[-1]


def _limites(ultimo_dia: date) -> list[dict]:
    filas = []
    for etiqueta, variable in CON_LIMITE:
        dia = parametro_vigente(TipoParametro.LIMITE_24H, variable, ultimo_dia)
        anual = parametro_vigente(TipoParametro.LIMITE_ANUAL, variable, ultimo_dia)
        if dia is not None or anual is not None:
            filas.append({"etiqueta": etiqueta, "dia": dia, "anual": anual})
    return filas


@rol_requerido(Rol.ADMINISTRADOR)
def reporte_mensual(request):
    ahora = timezone.now()
    hoy = ahora.date()
    anio, mes = mes_pedido(request.GET.get("mes"), hoy)
    todos, elegidos = sensores_pedidos(request.GET.getlist("sensores"))
    primer_dia = date(anio, mes, 1)
    ultimo_dia = date(anio, mes, calendar.monthrange(anio, mes)[1])
    en_curso = (anio, mes) == (hoy.year, hoy.month)
    # El mes en curso solo tiene calculados los días que ya cerraron.
    hasta = min(ultimo_dia, hoy - timedelta(days=1)) if en_curso else ultimo_dia
    dias_del_mes = max(0, (hasta - primer_dia).days + 1)

    resultados = {sensor.pk: resultados_mes(sensor.pk, anio, mes) for sensor in elegidos}
    filas_promedio = [
        {
            "etiqueta": variable.etiqueta,
            "celdas": [
                CeldaMes(
                    resultados[sensor.pk][Variable(variable.campo)], dias_del_mes, variable.unidad
                )
                for sensor in elegidos
            ],
        }
        for variable in VARIABLES_REPORTE
    ]
    dias_con_medicion = [
        resultados[sensor.pk][Variable.PM25].dias_con_medicion for sensor in elegidos
    ]
    filas_limite = [
        {
            "etiqueta": etiqueta,
            "dias_validos": [resultados[s.pk][variable].dias_validos for s in elegidos],
            "excedencias": [
                {
                    "cuantas": len(resultados[s.pk][variable].dias_con_excedencia),
                    "cuales": _lista_de_dias(resultados[s.pk][variable].dias_con_excedencia),
                }
                for s in elegidos
            ],
        }
        for etiqueta, variable in CON_LIMITE
    ]
    inicio, fin = (
        datetime.combine(primer_dia, datetime.min.time()),
        datetime.combine(ultimo_dia + timedelta(days=1), datetime.min.time()),
    )
    actualizando = MarcaRecalculo.objects.filter(
        sensor__in=elegidos, hora__gte=inicio, hora__lt=fin
    ).exists()
    sensores_url = [("sensores", sensor.pk) for sensor in elegidos]
    laminas = [
        {
            "dia": dia,
            "url": "?" + urlencode([("fecha", dia.isoformat()), *sensores_url]),
        }
        for dia in dias_con_lecturas(elegidos, primer_dia, min(ultimo_dia, hoy))
    ]

    contexto = {
        "seccion": "reportes",
        "mes_valor": f"{anio:04d}-{mes:02d}",
        "titulo_mes": mes_largo(anio, mes),
        "todos": todos,
        "elegidos": elegidos,
        "ids_elegidos": {sensor.pk for sensor in elegidos},
        "en_curso": en_curso,
        "datos_hasta": hasta if en_curso and dias_del_mes else None,
        "actualizando": actualizando,
        "filas_promedio": filas_promedio,
        "dias_con_medicion": dias_con_medicion,
        "filas_limite": filas_limite,
        "limites": _limites(ultimo_dia),
        "ultimo_dia": ultimo_dia,
        "laminas": laminas,
    }
    return render(request, "reportes/mensual.html", contexto)


@rol_requerido(Rol.ADMINISTRADOR)
def lamina(request):
    """Una lámina del mensual: el reporte diario de ese día, solo con los sensores elegidos."""
    ahora = timezone.now()
    dia = dia_pedido(request.GET.get("fecha"), ahora.date())
    _, elegidos = sensores_pedidos(request.GET.getlist("sensores"))
    reporte = armar_reporte_diario(dia, elegidos, ahora)
    return render(request, "reportes/_lamina_diaria.html", {"reporte": reporte})
