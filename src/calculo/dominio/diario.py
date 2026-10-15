"""Promedio de 24 horas de un sensor y una variable."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from calculo.dominio.redondeo import a_entero, a_un_decimal
from calculo.dominio.tipos import ResultadoDia, ResultadoHora, Variable

MINIMO_HORAS_VALIDAS = 18


def promedio_diario(
    fecha: date, variable: Variable, horas: Iterable[ResultadoHora]
) -> ResultadoDia:
    """Promedio de las concentraciones de las horas válidas del día (de 00:00 a 23:59).

    Con menos de 18 horas válidas el día queda como «datos insuficientes» y sin promedio. El
    promedio conserva un decimal y de él sale el entero que se informa.
    """
    concentraciones = [hora.concentracion for hora in horas if hora.valida]
    horas_validas = len(concentraciones)
    if horas_validas < MINIMO_HORAS_VALIDAS:
        return ResultadoDia(
            fecha=fecha,
            variable=variable,
            horas_validas=horas_validas,
            valido=False,
            promedio=None,
            promedio_entero=None,
            excedencia=None,
            limite=None,
        )
    promedio = a_un_decimal(sum(concentraciones) / horas_validas)
    return ResultadoDia(
        fecha=fecha,
        variable=variable,
        horas_validas=horas_validas,
        valido=True,
        promedio=promedio,
        promedio_entero=a_entero(promedio),
        excedencia=None,
        limite=None,
    )
