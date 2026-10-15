"""Concentración horaria: el promedio de las lecturas que cuentan, solo si la hora es válida."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from calculo.dominio.cobertura import cobertura_s, es_hora_valida
from calculo.dominio.redondeo import a_un_decimal
from calculo.dominio.tipos import LecturaParaCalculo, ResultadoHora, Variable


def concentracion_horaria(lecturas: Sequence[LecturaParaCalculo]) -> Decimal | None:
    """Promedio con un decimal de las lecturas que cuentan; None si ninguna cuenta.

    Cada valor se toma con un decimal antes de promediar, para quitar el ruido del flotante.
    """
    valores = [a_un_decimal(lectura.valor) for lectura in lecturas if lectura.cuenta]
    if not valores:
        return None
    return a_un_decimal(sum(valores) / len(valores))


def calcular_hora(
    inicio: datetime,
    variable: Variable,
    lecturas: Sequence[LecturaParaCalculo],
    anterior: LecturaParaCalculo | None,
) -> ResultadoHora:
    """Resultado de una hora de un sensor para una variable.

    `lecturas` son las de la hora (de hh:00:00 a hh:59:59), sin copias; `anterior`, la última
    lectura del sensor antes de esa hora.
    """
    cubiertos = cobertura_s(lecturas, anterior)
    valida = es_hora_valida(cubiertos)
    return ResultadoHora(
        inicio=inicio,
        variable=variable,
        cobertura_s=cubiertos,
        valida=valida,
        concentracion=concentracion_horaria(lecturas) if valida else None,
        lecturas_usadas=sum(1 for lectura in lecturas if lectura.cuenta),
    )
