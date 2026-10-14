"""Tipos del núcleo de cálculo de la norma.

Python puro: aquí no se importa Django ni nada de la base de datos.
Los números del cálculo son `Decimal` para que el resultado sea igual
al cálculo a mano (y para poder redondear los 5 hacia arriba, cosa que
`round()` no hace).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class Variable(StrEnum):
    """Variables a las que se les calcula hora válida y promedios.

    El valor es el nombre del campo en `LecturaNormalizada`. Temperatura,
    humedad, VOC y NOx no están a propósito: esas no se calculan.
    """

    PM1 = "pm1_0"
    PM25 = "pm2_5"
    PM4 = "pm4_0"
    PM10 = "pm10_0"
    CO2 = "co2"


class TipoParametro(StrEnum):
    LIMITE_24H = "limite_24h"
    LIMITE_ANUAL = "limite_anual"


@dataclass(frozen=True, slots=True)
class LecturaParaCalculo:
    """Una variable de una lectura, como la ve el cálculo.

    La lista que recibe el cálculo NO trae las copias (las quita quien
    consulta), pero sí trae las anómalas y las que no tienen valor: no
    cuentan para el promedio, pero sirven como «lectura anterior» para saber
    cuántos minutos cubre la siguiente. Por eso también hay que pasar la
    última lectura de la hora anterior.
    """

    hora: datetime
    valor: Decimal | None  # None = sin dato
    intervalo_s: int | None  # None = no cubre minutos
    anomala: bool = False

    @property
    def cuenta(self) -> bool:
        return self.valor is not None and not self.anomala


@dataclass(frozen=True, slots=True)
class ParametroVigente:
    """Un límite de la norma con sus fechas. `vigente_hasta` es inclusivo."""

    tipo: TipoParametro
    norma: str
    variable: Variable
    valor: Decimal
    unidad: str
    vigente_desde: date
    vigente_hasta: date | None = None

    def __post_init__(self) -> None:
        if self.vigente_hasta is not None and self.vigente_hasta < self.vigente_desde:
            raise ValueError("vigente_hasta no puede ser antes de vigente_desde")

    def aplica_en(self, fecha: date) -> bool:
        if fecha < self.vigente_desde:
            return False
        return self.vigente_hasta is None or fecha <= self.vigente_hasta


@dataclass(frozen=True, slots=True)
class ResultadoHora:
    """Hora válida si cubre al menos 2700 s (45 min); el tope es 3600 s."""

    inicio: datetime
    variable: Variable
    cobertura_s: int
    valida: bool
    concentracion: Decimal | None  # un decimal; None si la hora no es válida
    lecturas_usadas: int


@dataclass(frozen=True, slots=True)
class ResultadoDia:
    """Día válido con 18 horas válidas o más; si no, «datos insuficientes».

    `excedencia` y `limite` quedan en None si el día no es válido o si la
    variable no tiene límite en esa fecha.
    """

    fecha: date
    variable: Variable
    horas_validas: int
    valido: bool
    promedio: Decimal | None  # un decimal
    promedio_entero: int | None  # el que se informa y se compara con el límite
    excedencia: bool | None
    limite: ParametroVigente | None


@dataclass(frozen=True, slots=True)
class ResultadoMes:
    anio: int
    mes: int
    variable: Variable
    dias_con_medicion: int
    dias_validos: int
    promedio: Decimal | None  # None = «sin días válidos»
    promedio_entero: int | None
    dias_con_excedencia: tuple[date, ...] = ()
