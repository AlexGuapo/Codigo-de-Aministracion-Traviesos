"""Promedio de 24 horas de un sensor y una variable, y su excedencia diaria."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from calculo.dominio.redondeo import a_entero, a_un_decimal
from calculo.dominio.tipos import ParametroVigente, ResultadoDia, ResultadoHora, Variable

MINIMO_HORAS_VALIDAS = 18
# Solo las partículas que regula la norma tienen límite de 24 h.
VARIABLES_CON_LIMITE = (Variable.PM25, Variable.PM10)


def excedencia_diaria(
    fecha: date, variable: Variable, promedio_entero: int | None, limite: ParametroVigente | None
) -> tuple[bool | None, ParametroVigente | None]:
    """Si el día rebasa el límite de 24 h que regía ese día, y con qué límite se comparó.

    Una excedencia es que el promedio redondeado sea mayor que el límite; igual al límite no lo
    es. Una excedencia no significa incumplir la norma: eso solo lo decide la evaluación anual.
    Devuelve (None, None) si no hay con qué comparar: el día no es válido, la variable no tiene
    límite o la norma todavía no regía en esa fecha.
    """
    if promedio_entero is None or variable not in VARIABLES_CON_LIMITE:
        return None, None
    if limite is None or limite.variable != variable or not limite.aplica_en(fecha):
        return None, None
    return promedio_entero > limite.valor, limite


def promedio_diario(
    fecha: date,
    variable: Variable,
    horas: Iterable[ResultadoHora],
    limite: ParametroVigente | None = None,
) -> ResultadoDia:
    """Promedio de las concentraciones de las horas válidas del día (de 00:00 a 23:59).

    Con menos de 18 horas válidas el día queda como «datos insuficientes», sin promedio y sin
    comparar con el límite. El promedio conserva un decimal y de él sale el entero que se
    informa y se compara.
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
    entero = a_entero(promedio)
    excedencia, limite_usado = excedencia_diaria(fecha, variable, entero, limite)
    return ResultadoDia(
        fecha=fecha,
        variable=variable,
        horas_validas=horas_validas,
        valido=True,
        promedio=promedio,
        promedio_entero=entero,
        excedencia=excedencia,
        limite=limite_usado,
    )
