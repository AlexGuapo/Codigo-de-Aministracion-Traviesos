"""Cálculo con las lecturas guardadas: horas, días y meses de cada sensor.

Lee las lecturas, les aplica el núcleo de `calculo/dominio/` y guarda el resultado vigente en
`valor_calculado`, que se sobrescribe cada vez que se recalcula. Lo dispara la cola de recálculo
(cada lectura nueva deja una marca) y los cierres de hora, día y mes.
"""

from __future__ import annotations

import bisect
import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from calculo.cola import inicio_de_hora
from calculo.dominio.diario import VARIABLES_CON_LIMITE, promedio_diario
from calculo.dominio.horario import calcular_hora
from calculo.dominio.mensual import contar_dias_con_medicion, promedio_mensual
from calculo.dominio.redondeo import a_decimal, a_un_decimal
from calculo.dominio.tipos import (
    LecturaParaCalculo,
    ResultadoDia,
    ResultadoHora,
    ResultadoMes,
    TipoParametro,
    Variable,
)
from calculo.models import EstadoCalculo, MarcaRecalculo, Periodo, ValorCalculado
from calculo.selectors import (
    VARIABLE_DEL_NUCLEO,
    VARIABLE_EN_BASE,
    como_parametro_vigente,
    parametro_vigente,
)
from lecturas.models import Lectura
from sensores.models import EstadoSensor, Sensor

logger = logging.getLogger("calculo")

VERSION_CALCULO = "mvp-1"

UNA_HORA = timedelta(hours=1)
CIERRE_HORA = timedelta(minutes=20)
CIERRE_DIA = timedelta(minutes=30)
CIERRE_MES = timedelta(minutes=45)

# Las copias de una medición están a menos de 30 s entre sí; con este margen se ve el grupo
# completo aunque quede partido por el borde del intervalo que se consulta.
MARGEN_COPIAS = timedelta(seconds=30)
# Cuánto antes de la primera hora se buscan lecturas para tener la «anterior» de cada hora.
VENTANA_ANTERIOR = timedelta(hours=3)

LOTE_COLA = 500
# Espacio de nombres del bloqueo por sensor del cálculo (el de las lecturas es otro).
BLOQUEO_CALCULO = 7302
CAMPOS_LECTURA = ("id", "hora", "intervalo_s", "copia_discrepante_de_id", *Variable)


def inicio_del_dia(fecha: date) -> datetime:
    return datetime.combine(fecha, time.min)


def primer_dia_del_mes_siguiente(anio: int, mes: int) -> date:
    return date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)


def hora_cerrada(inicio: datetime, ahora: datetime) -> bool:
    return ahora >= inicio + UNA_HORA + CIERRE_HORA


def dia_cerrado(fecha: date, ahora: datetime) -> bool:
    return ahora >= inicio_del_dia(fecha + timedelta(days=1)) + CIERRE_DIA


def mes_cerrado(anio: int, mes: int, ahora: datetime) -> bool:
    return ahora >= inicio_del_dia(primer_dia_del_mes_siguiente(anio, mes)) + CIERRE_MES


# Lecturas


def sin_copias(lecturas: Iterable[Lectura]) -> list[Lectura]:
    """De cada grupo de copias deja solo la de hora más temprana (a igual hora, la primera
    guardada). Regresa las lecturas ordenadas por hora."""
    elegidas: dict[int, Lectura] = {}
    for lectura in sorted(lecturas, key=lambda lectura: (lectura.hora, lectura.pk)):
        elegidas.setdefault(lectura.copia_discrepante_de_id or lectura.pk, lectura)
    return sorted(elegidas.values(), key=lambda lectura: lectura.hora)


def _lecturas_entre(sensor_id: int, desde: datetime, hasta: datetime) -> list[Lectura]:
    filas = Lectura.objects.filter(
        sensor_id=sensor_id, hora__gte=desde - MARGEN_COPIAS, hora__lt=hasta + MARGEN_COPIAS
    ).only(*CAMPOS_LECTURA)
    return [lectura for lectura in sin_copias(filas) if desde <= lectura.hora < hasta]


def _ultima_antes_de(sensor_id: int, momento: datetime) -> Lectura | None:
    ultima = (
        Lectura.objects.filter(sensor_id=sensor_id, hora__lt=momento)
        .only(*CAMPOS_LECTURA)
        .order_by("-hora", "-pk")
        .first()
    )
    if ultima is None:
        return None
    raiz = ultima.copia_discrepante_de_id or ultima.pk
    grupo = Lectura.objects.filter(Q(pk=raiz) | Q(copia_discrepante_de_id=raiz))
    return sin_copias(grupo.only(*CAMPOS_LECTURA))[0]


def para_calculo(lectura: Lectura, variable: Variable) -> LecturaParaCalculo:
    valor = getattr(lectura, variable.value)
    return LecturaParaCalculo(
        hora=lectura.hora,
        valor=None if valor is None else a_decimal(valor),
        intervalo_s=lectura.intervalo_s,
    )


@dataclass
class LecturasDelSensor:
    """Las lecturas de un sensor alrededor de unas horas, sin copias, para calcularlas juntas."""

    lecturas: list[Lectura]
    anterior_a_todas: Lectura | None

    @classmethod
    def para_horas(cls, sensor_id: int, horas: Iterable[datetime]) -> LecturasDelSensor:
        horas = sorted(horas)
        desde = horas[0] - VENTANA_ANTERIOR
        lecturas = _lecturas_entre(sensor_id, desde, horas[-1] + UNA_HORA)
        return cls(lecturas, _ultima_antes_de(sensor_id, desde))

    def de_la_hora(self, inicio: datetime) -> tuple[list[Lectura], Lectura | None]:
        """Las lecturas de la hora y la última lectura del sensor antes de ella."""
        horas = [lectura.hora for lectura in self.lecturas]
        primera = bisect.bisect_left(horas, inicio)
        despues = bisect.bisect_left(horas, inicio + UNA_HORA)
        anterior = self.lecturas[primera - 1] if primera > 0 else self.anterior_a_todas
        return self.lecturas[primera:despues], anterior


# Guardar


def _guardar(sensor_id: int, variable: Variable, periodo: str, inicio: datetime, **valores):
    """Sobrescribe el valor vigente del periodo. Si el periodo ya estaba cerrado y su valor
    cambia, lo deja en el log."""
    anterior = (
        ValorCalculado.objects.filter(
            sensor_id=sensor_id,
            variable=VARIABLE_EN_BASE[variable],
            periodo=periodo,
            inicio=inicio,
        )
        .only("valor", "estado")
        .first()
    )
    if (
        anterior is not None
        and anterior.estado == EstadoCalculo.CERRADO
        and anterior.valor != valores.get("valor")
    ):
        logger.info(
            "Sensor %s: %s %s de %s cambió de %s a %s",
            sensor_id,
            periodo,
            inicio,
            variable,
            anterior.valor,
            valores.get("valor"),
        )
    ValorCalculado.objects.update_or_create(
        sensor_id=sensor_id,
        variable=VARIABLE_EN_BASE[variable],
        periodo=periodo,
        inicio=inicio,
        defaults={**valores, "version_calculo": VERSION_CALCULO, "calculado_en": timezone.now()},
    )


def guardar_hora(sensor_id: int, resultado: ResultadoHora, ahora: datetime) -> None:
    cerrada = hora_cerrada(resultado.inicio, ahora)
    _guardar(
        sensor_id,
        resultado.variable,
        Periodo.HORA,
        resultado.inicio,
        cobertura_min=a_un_decimal(Decimal(resultado.cobertura_s) / 60),
        lecturas_contadas=resultado.lecturas_usadas,
        es_valido=resultado.valida,
        valor=resultado.concentracion,
        estado=EstadoCalculo.CERRADO if cerrada else EstadoCalculo.PRELIMINAR,
    )


def guardar_dia(sensor_id: int, resultado: ResultadoDia) -> None:
    limite = None
    if resultado.limite is not None:
        limite = parametro_vigente(TipoParametro.LIMITE_24H, resultado.variable, resultado.fecha)
    _guardar(
        sensor_id,
        resultado.variable,
        Periodo.DIA,
        inicio_del_dia(resultado.fecha),
        horas_validas=resultado.horas_validas,
        es_valido=resultado.valido,
        valor=resultado.promedio,
        valor_entero=resultado.promedio_entero,
        excedencia=resultado.excedencia,
        parametro=limite,
        estado=EstadoCalculo.CERRADO,
    )


def guardar_mes(sensor_id: int, resultado: ResultadoMes) -> None:
    con_limite = resultado.variable in VARIABLES_CON_LIMITE
    _guardar(
        sensor_id,
        resultado.variable,
        Periodo.MES,
        inicio_del_dia(date(resultado.anio, resultado.mes, 1)),
        dias_con_medicion=resultado.dias_con_medicion,
        dias_validos=resultado.dias_validos,
        dias_excedencia=len(resultado.dias_con_excedencia) if con_limite else None,
        es_valido=resultado.dias_validos > 0,
        valor=resultado.promedio,
        valor_entero=resultado.promedio_entero,
        estado=EstadoCalculo.CERRADO,
    )


# Calcular


def _bloquear_sensor(sensor_id: int) -> None:
    """La cola y los cierres corren en hilos distintos: así nunca calculan a la vez el mismo
    sensor. El bloqueo dura hasta el final de la transacción."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [BLOQUEO_CALCULO, sensor_id])


def recalcular_horas(sensor_id: int, horas: Iterable[datetime], ahora: datetime) -> None:
    """Calcula y guarda cada hora de las cinco variables. Las horas que no han empezado se
    saltan."""
    horas = sorted({inicio_de_hora(hora) for hora in horas if inicio_de_hora(hora) <= ahora})
    if not horas:
        return
    _bloquear_sensor(sensor_id)
    datos = LecturasDelSensor.para_horas(sensor_id, horas)
    for inicio in horas:
        de_la_hora, anterior = datos.de_la_hora(inicio)
        for variable in Variable:
            resultado = calcular_hora(
                inicio,
                variable,
                [para_calculo(lectura, variable) for lectura in de_la_hora],
                None if anterior is None else para_calculo(anterior, variable),
            )
            guardar_hora(sensor_id, resultado, ahora)


def _hora_guardada(fila: ValorCalculado) -> ResultadoHora:
    return ResultadoHora(
        inicio=fila.inicio,
        variable=VARIABLE_DEL_NUCLEO[fila.variable],
        cobertura_s=int(fila.cobertura_min * 60),
        valida=fila.es_valido,
        concentracion=fila.valor,
        lecturas_usadas=fila.lecturas_contadas,
    )


def resultado_dia(sensor_id: int, fecha: date, variable: Variable) -> ResultadoDia:
    """El promedio de 24 h con las horas guardadas de ese día."""
    inicio = inicio_del_dia(fecha)
    horas = ValorCalculado.objects.filter(
        sensor_id=sensor_id,
        variable=VARIABLE_EN_BASE[variable],
        periodo=Periodo.HORA,
        inicio__gte=inicio,
        inicio__lt=inicio + timedelta(days=1),
    )
    limite = None
    if variable in VARIABLES_CON_LIMITE:
        parametro = parametro_vigente(TipoParametro.LIMITE_24H, variable, fecha)
        limite = None if parametro is None else como_parametro_vigente(parametro)
    return promedio_diario(fecha, variable, [_hora_guardada(fila) for fila in horas], limite)


def recalcular_dia(sensor_id: int, fecha: date) -> None:
    _bloquear_sensor(sensor_id)
    for variable in Variable:
        guardar_dia(sensor_id, resultado_dia(sensor_id, fecha, variable))


def _dia_guardado(fila: ValorCalculado) -> ResultadoDia:
    return ResultadoDia(
        fecha=fila.inicio.date(),
        variable=VARIABLE_DEL_NUCLEO[fila.variable],
        horas_validas=fila.horas_validas,
        valido=fila.es_valido,
        promedio=fila.valor,
        promedio_entero=fila.valor_entero,
        excedencia=fila.excedencia,
        limite=None,
    )


def resultados_mes(sensor_id: int, anio: int, mes: int) -> dict[Variable, ResultadoMes]:
    """Los valores del mes de cada variable con los días guardados.

    Sirve también para el mes en curso, que no se guarda: queda parcial hasta que cierra.
    """
    inicio = inicio_del_dia(date(anio, mes, 1))
    fin = inicio_del_dia(primer_dia_del_mes_siguiente(anio, mes))
    filas = ValorCalculado.objects.filter(
        sensor_id=sensor_id, periodo=Periodo.DIA, inicio__gte=inicio, inicio__lt=fin
    )
    dias = [_dia_guardado(fila) for fila in filas]
    con_medicion = contar_dias_con_medicion(dias)
    por_variable: dict[Variable, list[ResultadoDia]] = defaultdict(list)
    for dia in dias:
        por_variable[dia.variable].append(dia)
    return {
        variable: promedio_mensual(anio, mes, variable, por_variable[variable], con_medicion)
        for variable in Variable
    }


def recalcular_mes(sensor_id: int, anio: int, mes: int) -> None:
    _bloquear_sensor(sensor_id)
    for resultado in resultados_mes(sensor_id, anio, mes).values():
        guardar_mes(sensor_id, resultado)


# Cola y cierres


def recalcular_sensor(sensor_id: int, horas: Iterable[datetime], ahora: datetime) -> None:
    """Lo que cambia cuando llegan lecturas a unas horas de un sensor, en orden.

    La hora marcada y la siguiente (una lectura cambia los minutos que cubre la primera lectura
    de la hora siguiente), después el día si ya cerró y el mes si ya cerró.
    """
    marcadas = {inicio_de_hora(hora) for hora in horas}
    recalcular_horas(sensor_id, marcadas | {hora + UNA_HORA for hora in marcadas}, ahora)

    dias = sorted({hora.date() for hora in marcadas | {h + UNA_HORA for h in marcadas}})
    for fecha in dias:
        if dia_cerrado(fecha, ahora):
            recalcular_dia(sensor_id, fecha)
    for anio, mes in sorted({(fecha.year, fecha.month) for fecha in dias}):
        if mes_cerrado(anio, mes, ahora):
            recalcular_mes(sensor_id, anio, mes)


def procesar_cola(ahora: datetime | None = None, lote: int = LOTE_COLA) -> int:
    """Atiende las marcas pendientes y las borra. Regresa cuántas atendió.

    Las marcas se toman con `SKIP LOCKED` y se borran en la misma transacción que guarda los
    cálculos: si algo falla, quedan para la siguiente vuelta. Solo se borran las que se tomaron,
    así una marca que llega mientras se calcula no se pierde.
    """
    ahora = ahora or timezone.now()
    with transaction.atomic():
        marcas = list(
            MarcaRecalculo.objects.select_for_update(skip_locked=True)
            .only("id", "sensor_id", "hora")
            .order_by("id")[:lote]
        )
        if not marcas:
            return 0
        por_sensor: dict[int, set[datetime]] = defaultdict(set)
        for marca in marcas:
            por_sensor[marca.sensor_id].add(marca.hora)
        for sensor_id, horas in sorted(por_sensor.items()):
            recalcular_sensor(sensor_id, horas, ahora)
        MarcaRecalculo.objects.filter(pk__in=[marca.pk for marca in marcas]).delete()
    logger.info("Cola de recálculo: %d marcas de %d sensores", len(marcas), len(por_sensor))
    return len(marcas)


def _sensores_activos() -> list[int]:
    return list(
        Sensor.objects.filter(estado=EstadoSensor.ACTIVO)
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def cerrar_hora(ahora: datetime | None = None) -> datetime:
    """A las hh+1:20 la hora hh queda cerrada para todos los sensores activos, tenga o no
    lecturas."""
    ahora = ahora or timezone.now()
    hora = inicio_de_hora(ahora - UNA_HORA - CIERRE_HORA)
    with transaction.atomic():
        for sensor_id in _sensores_activos():
            recalcular_horas(sensor_id, [hora], ahora)
    return hora


def cerrar_dia(ahora: datetime | None = None) -> date:
    """A las 00:30 se calcula el promedio de 24 h del día anterior y su excedencia."""
    ahora = ahora or timezone.now()
    fecha = (ahora - CIERRE_DIA).date() - timedelta(days=1)
    with transaction.atomic():
        for sensor_id in _sensores_activos():
            recalcular_dia(sensor_id, fecha)
    return fecha


def cerrar_mes(ahora: datetime | None = None) -> tuple[int, int]:
    """El día 1 a las 00:45 se guardan los valores del mes anterior."""
    ahora = ahora or timezone.now()
    ultimo_dia = (ahora - CIERRE_MES).date().replace(day=1) - timedelta(days=1)
    with transaction.atomic():
        for sensor_id in _sensores_activos():
            recalcular_mes(sensor_id, ultimo_dia.year, ultimo_dia.month)
    return ultimo_dia.year, ultimo_dia.month
