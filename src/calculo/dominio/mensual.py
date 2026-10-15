"""Promedio mensual de un sensor y una variable, y los días con medición del mes.

La norma no fija un límite mensual: el promedio del mes es informativo y nunca lleva veredicto.
"""

from __future__ import annotations

from collections.abc import Iterable

from calculo.dominio.redondeo import a_entero, a_un_decimal
from calculo.dominio.tipos import ResultadoDia, ResultadoMes, Variable


def promedio_mensual(
    anio: int,
    mes: int,
    variable: Variable,
    dias: Iterable[ResultadoDia],
    dias_con_medicion: int,
) -> ResultadoMes:
    """Promedio de los promedios diarios de los días válidos del mes.

    `dias` son los resultados diarios de esa variable en el mes. `dias_con_medicion` se cuenta
    aparte con `contar_dias_con_medicion`, porque mira todas las variables del sensor.
    """
    dias = list(dias)
    validos = [dia for dia in dias if dia.valido]
    excedencias = tuple(sorted(dia.fecha for dia in validos if dia.excedencia))
    if not validos:
        return ResultadoMes(
            anio=anio,
            mes=mes,
            variable=variable,
            dias_con_medicion=dias_con_medicion,
            dias_validos=0,
            promedio=None,
            promedio_entero=None,
            dias_con_excedencia=excedencias,
        )
    promedio = a_un_decimal(sum(dia.promedio for dia in validos) / len(validos))
    return ResultadoMes(
        anio=anio,
        mes=mes,
        variable=variable,
        dias_con_medicion=dias_con_medicion,
        dias_validos=len(validos),
        promedio=promedio,
        promedio_entero=a_entero(promedio),
        dias_con_excedencia=excedencias,
    )


def contar_dias_con_medicion(dias: Iterable[ResultadoDia]) -> int:
    """Días con al menos una hora válida en alguna variable.

    Recibe los resultados diarios de todas las variables del sensor en el mes. Un día con
    lecturas pero sin ninguna hora válida no cuenta.
    """
    return len({dia.fecha for dia in dias if dia.horas_validas >= 1})
