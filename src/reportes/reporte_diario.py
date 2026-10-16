"""El reporte diario, armado al abrirlo con las lecturas y los valores calculados del momento.

El reporte mensual arma cada una de sus láminas con este mismo procedimiento.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db.models.functions import TruncDate

from calculo.dominio.operacion import hay_hueco
from calculo.dominio.tipos import ParametroVigente, ResultadoDia, TipoParametro, Variable
from calculo.selectors import como_parametro_vigente, parametro_vigente
from calculo.services import resultado_dia, sin_copias
from lecturas.models import Lectura
from reportes.formato import fecha_larga
from reportes.series import VARIABLES_REPORTE, graficas_del_reporte
from sensores.models import Sensor

# El núcleo del cálculo nombra las variables como los campos de la lectura.
VARIABLE_DEL_CAMPO = {variable.value: variable for variable in Variable}
FIN_DEL_DIA = time(23, 59)


@dataclass(frozen=True, slots=True)
class PeriodoSinTransmitir:
    sensor: str
    desde: datetime
    hasta: datetime

    def __str__(self) -> str:
        return f"{self.sensor} sin transmitir de {self.desde:%H:%M} a {self.hasta:%H:%M}"


@dataclass(frozen=True, slots=True)
class Celda:
    """Un promedio de 24 h de un sensor y una variable, como va en la tabla."""

    resultado: ResultadoDia

    @property
    def texto(self) -> str:
        """«27 (20 h)» o «datos insuficientes»."""
        if not self.resultado.valido:
            return "datos insuficientes"
        return f"{self.resultado.promedio_entero} ({self.resultado.horas_validas} h)"

    @property
    def excedencia(self) -> bool:
        return bool(self.resultado.excedencia)


@dataclass(slots=True)
class FilaDeLaTabla:
    etiqueta: str
    unidad: str
    celdas: list[Celda]


@dataclass(slots=True)
class ReporteDiario:
    dia: date
    sensores: list[Sensor]
    hay_lecturas: bool
    graficas: list[dict] = field(default_factory=list)
    tabla: list[FilaDeLaTabla] = field(default_factory=list)
    periodos: list[PeriodoSinTransmitir] = field(default_factory=list)
    limites: dict[Variable, ParametroVigente] = field(default_factory=dict)

    @property
    def titulo(self) -> str:
        return f"Reporte diario · {fecha_larga(self.dia)}"


def inicio_del_dia(dia: date) -> datetime:
    return datetime.combine(dia, time.min)


def periodos_sin_transmitir(
    nombre: str,
    lecturas: list[Lectura],
    anterior: Lectura | None,
    siguiente: datetime | None,
    dia: date,
    ahora: datetime,
) -> list[PeriodoSinTransmitir]:
    """Los periodos del día en que el sensor no transmitió, recortados al día.

    Cada periodo va de la última lectura antes del hueco a la primera después. `lecturas` son
    las del día, sin copias y en orden; `anterior` es la última antes del día y `siguiente`, la
    hora de la primera después (o None si todavía no llega ninguna). El final del día es 23:59;
    en el día de hoy, el último periodo llega hasta ahora.
    """
    inicio = inicio_del_dia(dia)
    fin = min(datetime.combine(dia, FIN_DEL_DIA), ahora)
    if fin <= inicio:
        return []

    puntos: list[tuple[datetime, int | None]] = []
    if anterior is not None:
        puntos.append((anterior.hora, anterior.intervalo_s))
    else:
        # Sin lecturas antes del día: el día cuenta desde las 00:00, como si ahí terminara una.
        puntos.append((inicio, None))
    puntos.extend((lectura.hora, lectura.intervalo_s) for lectura in lecturas)
    cierre = siguiente if siguiente is not None else ahora

    periodos = []
    for (hora, intervalo), (despues, _) in zip(puntos, [*puntos[1:], (cierre, None)], strict=True):
        if not hay_hueco(hora, despues, intervalo):
            continue
        desde, hasta = max(hora, inicio), min(despues, fin)
        if hasta > desde:
            periodos.append(PeriodoSinTransmitir(nombre, desde, hasta))
    return periodos


def _lecturas_del_dia(sensor_id: int, dia: date) -> list[Lectura]:
    inicio = inicio_del_dia(dia)
    margen = timedelta(seconds=30)
    filas = Lectura.objects.filter(
        sensor_id=sensor_id,
        hora__gte=inicio - margen,
        hora__lt=inicio + timedelta(days=1) + margen,
    )
    return [
        lectura
        for lectura in sin_copias(filas)
        if inicio <= lectura.hora < inicio + timedelta(days=1)
    ]


def _anterior_y_siguiente(sensor_id: int, dia: date) -> tuple[Lectura | None, datetime | None]:
    inicio = inicio_del_dia(dia)
    anterior = (
        Lectura.objects.filter(sensor_id=sensor_id, hora__lt=inicio)
        .only("hora", "intervalo_s")
        .order_by("-hora")
        .first()
    )
    siguiente = (
        Lectura.objects.filter(sensor_id=sensor_id, hora__gte=inicio + timedelta(days=1))
        .order_by("hora")
        .values_list("hora", flat=True)
        .first()
    )
    return anterior, siguiente


def limites_del_dia(dia: date) -> dict[Variable, ParametroVigente]:
    limites = {}
    for variable in (Variable.PM25, Variable.PM10):
        parametro = parametro_vigente(TipoParametro.LIMITE_24H, variable, dia)
        if parametro is not None:
            limites[variable] = como_parametro_vigente(parametro)
    return limites


def armar_reporte_diario(dia: date, sensores: list[Sensor], ahora: datetime) -> ReporteDiario:
    """El reporte de un día con los sensores elegidos, en el orden recibido."""
    lecturas = {sensor.pk: _lecturas_del_dia(sensor.pk, dia) for sensor in sensores}
    reporte = ReporteDiario(dia=dia, sensores=sensores, hay_lecturas=any(lecturas.values()))
    if not reporte.hay_lecturas:
        return reporte

    reporte.graficas = graficas_del_reporte(
        [(sensor.nombre_corto, lecturas[sensor.pk]) for sensor in sensores]
    )
    for variable in VARIABLES_REPORTE:
        nucleo = VARIABLE_DEL_CAMPO[variable.campo]
        reporte.tabla.append(
            FilaDeLaTabla(
                etiqueta=variable.etiqueta,
                unidad=variable.unidad,
                celdas=[Celda(resultado_dia(sensor.pk, dia, nucleo)) for sensor in sensores],
            )
        )
    for sensor in sensores:
        anterior, siguiente = _anterior_y_siguiente(sensor.pk, dia)
        reporte.periodos.extend(
            periodos_sin_transmitir(
                sensor.nombre_corto, lecturas[sensor.pk], anterior, siguiente, dia, ahora
            )
        )
    reporte.limites = limites_del_dia(dia)
    return reporte


def dias_con_lecturas(sensores: list[Sensor], desde: date, hasta: date) -> list[date]:
    """Los días entre `desde` y `hasta` (incluidos) en que algún sensor tiene lecturas."""
    return sorted(
        Lectura.objects.filter(
            sensor__in=sensores,
            hora__gte=inicio_del_dia(desde),
            hora__lt=inicio_del_dia(hasta + timedelta(days=1)),
        )
        .annotate(dia=TruncDate("hora"))
        .values_list("dia", flat=True)
        .distinct()
    )
