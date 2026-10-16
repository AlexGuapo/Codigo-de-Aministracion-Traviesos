"""Consultas del cálculo que leen la base."""

from __future__ import annotations

from datetime import date

from calculo.dominio.tipos import ParametroVigente, TipoParametro, Variable
from calculo.models import Parametro

# El núcleo nombra las variables como los campos de la lectura (`pm2_5`); la base, como el
# modelo de datos (`pm25`).
VARIABLE_EN_BASE = {
    Variable.PM1: "pm1",
    Variable.PM25: "pm25",
    Variable.PM4: "pm4",
    Variable.PM10: "pm10",
    Variable.CO2: "co2",
}
VARIABLE_DEL_NUCLEO = {en_base: variable for variable, en_base in VARIABLE_EN_BASE.items()}


def parametro_vigente(tipo: TipoParametro, variable: Variable, fecha: date) -> Parametro | None:
    """El límite que regía en esa fecha, o None si la norma todavía no regía.

    Si dos filas cubren la misma fecha, gana la de inicio más reciente y, a igual inicio, la
    cargada al final.
    """
    return (
        Parametro.objects.filter(
            tipo=tipo,
            variable=VARIABLE_EN_BASE[variable],
            vigente_desde__lte=fecha,
        )
        .exclude(vigente_hasta__lt=fecha)
        .order_by("-vigente_desde", "-cargado_en", "-id")
        .first()
    )


def como_parametro_vigente(parametro: Parametro) -> ParametroVigente:
    """El parámetro de la base en la forma que usa el núcleo de cálculo."""
    return ParametroVigente(
        tipo=TipoParametro(parametro.tipo),
        norma=parametro.norma,
        variable=VARIABLE_DEL_NUCLEO[parametro.variable],
        valor=parametro.valor,
        unidad=parametro.unidad,
        vigente_desde=parametro.vigente_desde,
        vigente_hasta=parametro.vigente_hasta,
    )
