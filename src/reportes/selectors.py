"""Estado de la red de sensores para el panel del Administrador.

Todo se calcula al leer, con las lecturas y los valores ya guardados: el panel no depende de que
el proceso de fondo esté corriendo para decir qué sensor dejó de transmitir.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from django.db.models import Count, Max
from django.db.models.functions import TruncDate

from calculo.cola import inicio_de_hora
from calculo.dominio.operacion import fuera_de_operacion, umbral_sin_transmitir
from calculo.models import Periodo, ValorCalculado
from lecturas.models import Lectura
from sensores.models import EstadoSensor, Sensor, Ubicacion

DIAS_DE_CONTINUIDAD = 30
# Una hora cierra a los 20 minutos de la siguiente; antes de eso su valor es preliminar.
CIERRE_DE_HORA = timedelta(hours=1, minutes=20)


class Estado(StrEnum):
    TRANSMITIENDO = "transmitiendo"
    FUERA_DE_OPERACION = "fuera_de_operacion"
    SIN_LECTURAS = "sin_lecturas"


ETIQUETAS_ESTADO = {
    Estado.TRANSMITIENDO: "Transmitiendo",
    Estado.FUERA_DE_OPERACION: "Fuera de operación",
    Estado.SIN_LECTURAS: "Sin lecturas todavía",
}


class EstadoDia(StrEnum):
    VALIDO = "valido"
    INCOMPLETO = "incompleto"
    SIN_LECTURAS = "sin_lecturas"
    EN_CURSO = "en_curso"


ETIQUETAS_DIA = {
    EstadoDia.VALIDO: "Día válido",
    EstadoDia.INCOMPLETO: "Incompleto",
    EstadoDia.SIN_LECTURAS: "Sin lecturas",
    EstadoDia.EN_CURSO: "Hoy, en curso",
}


@dataclass(frozen=True, slots=True)
class DiaDeContinuidad:
    fecha: date
    estado: EstadoDia

    @property
    def etiqueta(self) -> str:
        return ETIQUETAS_DIA[self.estado]


@dataclass(slots=True)
class EstadoDeSensor:
    """Lo que el panel muestra de un sensor activo. Nunca lleva la MAC, el token ni el apodo."""

    id: int
    nombre: str
    colonia: str | None
    municipio: str | None
    estado: Estado
    ultima_lectura: datetime | None
    sin_lectura_desde: timedelta | None
    umbral: timedelta
    hora_cerrada: datetime
    pm25: Decimal | None  # None = «datos insuficientes»
    pm10: Decimal | None
    continuidad: list[DiaDeContinuidad] = field(default_factory=list)

    @property
    def etiqueta_estado(self) -> str:
        return ETIQUETAS_ESTADO[self.estado]

    @property
    def dias_contados(self) -> int:
        return sum(1 for dia in self.continuidad if dia.estado != EstadoDia.EN_CURSO)

    @property
    def dias_validos(self) -> int:
        return sum(1 for dia in self.continuidad if dia.estado == EstadoDia.VALIDO)

    @property
    def porcentaje_validos(self) -> int | None:
        if not self.dias_contados:
            return None
        return round(100 * self.dias_validos / self.dias_contados)


@dataclass(slots=True)
class EstadoDeLaRed:
    ahora: datetime
    sensores: list[EstadoDeSensor]

    def con_estado(self, estado: Estado) -> list[EstadoDeSensor]:
        return [sensor for sensor in self.sensores if sensor.estado == estado]

    @property
    def transmitiendo(self) -> list[EstadoDeSensor]:
        return self.con_estado(Estado.TRANSMITIENDO)

    @property
    def fuera_de_operacion(self) -> list[EstadoDeSensor]:
        return self.con_estado(Estado.FUERA_DE_OPERACION)

    @property
    def porcentaje_validos(self) -> int | None:
        contados = sum(sensor.dias_contados for sensor in self.sensores)
        if not contados:
            return None
        validos = sum(sensor.dias_validos for sensor in self.sensores)
        return round(100 * validos / contados)


def ultima_hora_cerrada(ahora: datetime) -> datetime:
    """La hora más reciente que ya cerró: a las 16:11 es la de las 14:00 (cerró a las 15:20)."""
    return inicio_de_hora(ahora - CIERRE_DE_HORA)


def _colonias_vigentes(ids: list[int]) -> dict[int, tuple[str, str]]:
    ubicaciones = Ubicacion.objects.filter(
        sensor_id__in=ids, vigente_hasta__isnull=True
    ).select_related("colonia")
    return {u.sensor_id: (u.colonia.nombre, u.colonia.municipio) for u in ubicaciones}


def _ultimas_lecturas(ids: list[int]) -> dict[int, Lectura]:
    ultimas = (
        Lectura.objects.filter(sensor_id__in=ids).values("sensor_id").annotate(hora=Max("hora"))
    )
    filas = Lectura.objects.filter(
        sensor_id__in=ids, hora__in=[fila["hora"] for fila in ultimas]
    ).only("sensor_id", "hora", "intervalo_s")
    por_sensor: dict[int, Lectura] = {}
    for lectura in sorted(filas, key=lambda lectura: (lectura.hora, lectura.pk)):
        por_sensor[lectura.sensor_id] = lectura
    return por_sensor


def _particulas_de_la_hora(ids: list[int], hora: datetime) -> dict[tuple[int, str], Decimal]:
    filas = ValorCalculado.objects.filter(
        sensor_id__in=ids,
        periodo=Periodo.HORA,
        inicio=hora,
        variable__in=["pm25", "pm10"],
        es_valido=True,
    ).values_list("sensor_id", "variable", "valor")
    return {(sensor_id, variable): valor for sensor_id, variable, valor in filas}


def continuidad(
    ids: list[int], hoy: date, desde_por_sensor: dict[int, date], dias: int = DIAS_DE_CONTINUIDAD
) -> dict[int, list[DiaDeContinuidad]]:
    """El estado de cada uno de los últimos `dias` días de cada sensor, del más antiguo a hoy.

    Un día es válido si su promedio de 24 h de PM2.5 lo es (18 horas válidas o más); incompleto
    si tuvo lecturas pero no alcanzó; hoy siempre está en curso. Los días anteriores a la fecha
    desde la que el sensor recibe lecturas no se muestran.
    """
    inicio = hoy - timedelta(days=dias - 1)
    desde = datetime.combine(inicio, datetime.min.time())
    con_lecturas: dict[int, set[date]] = defaultdict(set)
    for fila in (
        Lectura.objects.filter(sensor_id__in=ids, hora__gte=desde)
        .annotate(dia=TruncDate("hora"))
        .values("sensor_id", "dia")
        .annotate(n=Count("id"))
    ):
        con_lecturas[fila["sensor_id"]].add(fila["dia"])
    validos: dict[int, set[date]] = defaultdict(set)
    for sensor_id, inicio_dia in ValorCalculado.objects.filter(
        sensor_id__in=ids,
        periodo=Periodo.DIA,
        variable="pm25",
        es_valido=True,
        inicio__gte=desde,
    ).values_list("sensor_id", "inicio"):
        validos[sensor_id].add(inicio_dia.date())

    resultado = {}
    for sensor_id in ids:
        primero = max(inicio, desde_por_sensor.get(sensor_id, inicio))
        dias_sensor = []
        fecha = primero
        while fecha <= hoy:
            if fecha == hoy:
                estado = EstadoDia.EN_CURSO
            elif fecha in validos[sensor_id]:
                estado = EstadoDia.VALIDO
            elif fecha in con_lecturas[sensor_id]:
                estado = EstadoDia.INCOMPLETO
            else:
                estado = EstadoDia.SIN_LECTURAS
            dias_sensor.append(DiaDeContinuidad(fecha, estado))
            fecha += timedelta(days=1)
        resultado[sensor_id] = dias_sensor
    return resultado


def _orden(sensor: EstadoDeSensor):
    """Primero los fuera de operación, del que lleva más tiempo al que lleva menos; luego los que
    transmiten y al final los que no tienen lecturas, cada grupo por nombre."""
    if sensor.estado == Estado.FUERA_DE_OPERACION:
        return (0, -sensor.sin_lectura_desde.total_seconds(), sensor.nombre.lower())
    if sensor.estado == Estado.TRANSMITIENDO:
        return (1, 0, sensor.nombre.lower())
    return (2, 0, sensor.nombre.lower())


def estado_red(ahora: datetime) -> EstadoDeLaRed:
    """El estado de cada sensor activo, en el orden del panel. Los dados de baja no aparecen."""
    sensores = list(
        Sensor.objects.filter(estado=EstadoSensor.ACTIVO).only(
            "id", "nombre_corto", "lecturas_desde"
        )
    )
    ids = [sensor.pk for sensor in sensores]
    colonias = _colonias_vigentes(ids)
    ultimas = _ultimas_lecturas(ids)
    hora = ultima_hora_cerrada(ahora)
    particulas = _particulas_de_la_hora(ids, hora)
    dias = continuidad(ids, ahora.date(), {s.pk: s.lecturas_desde for s in sensores})

    estados = []
    for sensor in sensores:
        ultima = ultimas.get(sensor.pk)
        intervalo = ultima.intervalo_s if ultima else None
        if ultima is None:
            estado = Estado.SIN_LECTURAS
        elif fuera_de_operacion(ultima.hora, intervalo, ahora):
            estado = Estado.FUERA_DE_OPERACION
        else:
            estado = Estado.TRANSMITIENDO
        colonia, municipio = colonias.get(sensor.pk, (None, None))
        estados.append(
            EstadoDeSensor(
                id=sensor.pk,
                nombre=sensor.nombre_corto,
                colonia=colonia,
                municipio=municipio,
                estado=estado,
                ultima_lectura=ultima.hora if ultima else None,
                sin_lectura_desde=ahora - ultima.hora if ultima else None,
                umbral=umbral_sin_transmitir(intervalo),
                hora_cerrada=hora,
                pm25=particulas.get((sensor.pk, "pm25")),
                pm10=particulas.get((sensor.pk, "pm10")),
                continuidad=dias[sensor.pk],
            )
        )
    return EstadoDeLaRed(ahora=ahora, sensores=sorted(estados, key=_orden))


def hueco_mas_largo(
    sensor_id: int, ahora: datetime, dias: int = DIAS_DE_CONTINUIDAD
) -> timedelta | None:
    """El tiempo más largo sin transmitir en los últimos `dias` días, contando hasta ahora.

    Solo cuenta lo que pasa del umbral de «sin transmitir»: un envío perdido no es un hueco.
    None si el sensor nunca ha transmitido.
    """
    desde = ahora - timedelta(days=dias)
    horas = list(
        Lectura.objects.filter(sensor_id=sensor_id, hora__gte=desde)
        .order_by("hora")
        .values_list("hora", "intervalo_s")
    )
    anterior = (
        Lectura.objects.filter(sensor_id=sensor_id, hora__lt=desde)
        .order_by("-hora")
        .values_list("hora", "intervalo_s")
        .first()
    )
    if anterior is not None:
        horas.insert(0, (desde, anterior[1]))
    if not horas:
        return None
    mayor = timedelta(0)
    for (hora, intervalo), (siguiente, _) in zip(horas, [*horas[1:], (ahora, None)], strict=True):
        hueco = siguiente - hora
        if hueco > umbral_sin_transmitir(intervalo) and hueco > mayor:
            mayor = hueco
    return mayor
