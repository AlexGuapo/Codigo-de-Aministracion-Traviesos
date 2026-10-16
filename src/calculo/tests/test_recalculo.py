from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from calculo.models import EstadoCalculo, MarcaRecalculo, Periodo, ValorCalculado
from calculo.services import cerrar_dia, cerrar_hora, cerrar_mes, procesar_cola
from lecturas.services import registrar_lectura
from recepcion.ports import LecturaNormalizada, Ruta
from sensores.models import Sensor

DIA = date(2026, 10, 5)
TODO_EL_DIA = tuple(range(24))
DESPUES_DEL_DIA = datetime(2026, 10, 6, 1, 0)


@pytest.fixture
def sensor(db):
    return Sensor.objects.create(
        nombre_corto="S-1",
        mac_cifrada="c",
        mac_huella="h" * 64,
        token_cifrado="t",
        lecturas_desde=date(2026, 9, 1),
    )


def guardar(sensor, hora, pm25=None, pm10=None, intervalo_s=1800):
    lectura = LecturaNormalizada(
        sensor_id=sensor.pk,
        hora_local=hora,
        hora_nube=(hora + timedelta(hours=14)).strftime("%Y-%m-%d %H:%M:%S"),
        ruta=Ruta.HISTORIAL,
        crudo="{}",
        intervalo_s=intervalo_s,
        pm1_0=None,
        pm2_5=pm25,
        pm4_0=None,
        pm10_0=pm10,
        co2=None,
        temperatura_sen55=None,
        humedad_sen55=None,
        temperatura_scd40=None,
        humedad_scd40=None,
        voc=None,
        nox=None,
    )
    return registrar_lectura(lectura)


def valor(sensor, periodo, inicio, variable="pm25"):
    return ValorCalculado.objects.get(
        sensor=sensor, periodo=periodo, inicio=inicio, variable=variable
    )


def hora(h, m=0, s=0, dia=DIA):
    return datetime(dia.year, dia.month, dia.day, h, m, s)


def llenar_dia(sensor, pm25, horas=TODO_EL_DIA, dia=DIA, pm10=None):
    """Dos lecturas por hora, a los :05 y a los :35, más la anterior de las 23:35 del día previo."""
    guardar(sensor, hora(23, 35, dia=dia - timedelta(days=1)), pm25, pm10)
    for h in horas:
        guardar(sensor, hora(h, 5, dia=dia), pm25, pm10)
        guardar(sensor, hora(h, 35, dia=dia), pm25, pm10)


# Cola y horas


def test_la_cola_calcula_la_hora_y_borra_sus_marcas(sensor):
    guardar(sensor, hora(9, 35), 15.0)
    guardar(sensor, hora(10, 5), 18.4)
    guardar(sensor, hora(10, 35), 21.0)
    assert procesar_cola(ahora=hora(10, 40)) == 3
    resultado = valor(sensor, Periodo.HORA, hora(10))
    assert resultado.es_valido
    assert resultado.valor == Decimal("19.7")
    assert resultado.cobertura_min == Decimal("60.0")
    assert resultado.lecturas_contadas == 2
    assert resultado.estado == EstadoCalculo.PRELIMINAR
    assert resultado.version_calculo
    assert not MarcaRecalculo.objects.exists()


def test_calcula_las_cinco_variables_y_las_que_no_tienen_dato_quedan_sin_valor(sensor):
    guardar(sensor, hora(9, 35), 15.0)
    guardar(sensor, hora(10, 5), 18.4)
    guardar(sensor, hora(10, 35), 21.0)
    procesar_cola(ahora=hora(10, 40))
    filas = ValorCalculado.objects.filter(sensor=sensor, periodo=Periodo.HORA, inicio=hora(10))
    assert {fila.variable for fila in filas} == {"pm1", "pm25", "pm4", "pm10", "co2"}
    pm10 = filas.get(variable="pm10")
    assert not pm10.es_valido
    assert pm10.valor is None


def test_una_hora_de_29_minutos_no_es_valida(sensor):
    guardar(sensor, hora(9, 43), 15.0)
    guardar(sensor, hora(10, 12), 18.4)
    procesar_cola(ahora=hora(10, 40))
    resultado = valor(sensor, Periodo.HORA, hora(10))
    assert not resultado.es_valido
    assert resultado.valor is None
    assert resultado.cobertura_min == Decimal("29.0")


def test_una_lectura_atrasada_recalcula_tambien_la_hora_siguiente(sensor):
    guardar(sensor, hora(10, 5), 18.4)
    guardar(sensor, hora(11, 5), 20.0)
    guardar(sensor, hora(11, 35), 20.0)
    procesar_cola(ahora=hora(12, 0))
    assert valor(sensor, Periodo.HORA, hora(11)).cobertura_min == Decimal("60.0")
    # Llega tarde la de las 10:50: la de las 11:05 ya solo cubre 15 minutos.
    guardar(sensor, hora(10, 50), 19.0)
    procesar_cola(ahora=hora(12, 30))
    assert valor(sensor, Periodo.HORA, hora(11)).cobertura_min == Decimal("45.0")


def test_entre_copias_discrepantes_cuenta_la_de_hora_mas_temprana(sensor):
    guardar(sensor, hora(9, 35), 15.0)
    # La de las 10:05:02 llega primero a SARRCA, pero cuenta la de las 10:05:00.
    guardar(sensor, hora(10, 5, 2), 18.9)
    guardar(sensor, hora(10, 5, 0), 18.4)
    guardar(sensor, hora(10, 35), 21.0)
    procesar_cola(ahora=hora(10, 40))
    resultado = valor(sensor, Periodo.HORA, hora(10))
    assert resultado.lecturas_contadas == 2
    assert resultado.valor == Decimal("19.7")


def test_una_hora_ya_cerrada_se_guarda_como_cerrada(sensor):
    guardar(sensor, hora(9, 35), 15.0)
    guardar(sensor, hora(10, 5), 18.4)
    procesar_cola(ahora=hora(11, 20))
    assert valor(sensor, Periodo.HORA, hora(10)).estado == EstadoCalculo.CERRADO


def test_las_horas_que_no_han_empezado_no_se_calculan(sensor):
    guardar(sensor, hora(10, 35), 18.4)
    procesar_cola(ahora=hora(10, 40))
    assert not ValorCalculado.objects.filter(inicio=hora(11)).exists()


def test_procesar_la_cola_dos_veces_no_cambia_nada(sensor):
    guardar(sensor, hora(9, 35), 15.0)
    guardar(sensor, hora(10, 5), 18.4)
    procesar_cola(ahora=hora(10, 40))
    antes = list(ValorCalculado.objects.values_list("variable", "inicio", "valor", "es_valido"))
    MarcaRecalculo.objects.create(sensor=sensor, hora=hora(10), causa="manual")
    procesar_cola(ahora=hora(10, 40))
    despues = list(ValorCalculado.objects.values_list("variable", "inicio", "valor", "es_valido"))
    assert sorted(antes) == sorted(despues)


def test_sin_marcas_la_cola_no_hace_nada(sensor):
    assert procesar_cola(ahora=hora(10)) == 0


# Cierres


def test_el_cierre_de_hora_cierra_la_hora_aunque_el_sensor_no_haya_transmitido(sensor):
    assert cerrar_hora(ahora=hora(11, 20)) == hora(10)
    resultado = valor(sensor, Periodo.HORA, hora(10))
    assert resultado.estado == EstadoCalculo.CERRADO
    assert not resultado.es_valido
    assert resultado.lecturas_contadas == 0


def test_el_cierre_de_hora_pasa_la_preliminar_a_cerrada(sensor):
    guardar(sensor, hora(9, 35), 15.0)
    guardar(sensor, hora(10, 5), 18.4)
    guardar(sensor, hora(10, 35), 21.0)
    procesar_cola(ahora=hora(10, 40))
    cerrar_hora(ahora=hora(11, 20))
    resultado = valor(sensor, Periodo.HORA, hora(10))
    assert resultado.estado == EstadoCalculo.CERRADO
    assert resultado.valor == Decimal("19.7")


def test_el_cierre_del_dia_calcula_el_promedio_y_la_excedencia(sensor):
    llenar_dia(sensor, pm25=30.0, pm10=40.0)
    procesar_cola(ahora=hora(23, 59))
    assert cerrar_dia(ahora=datetime(2026, 10, 6, 0, 30)) == DIA
    pm25 = valor(sensor, Periodo.DIA, hora(0))
    assert pm25.es_valido
    assert pm25.horas_validas == 24
    assert pm25.valor == Decimal("30.0")
    assert pm25.valor_entero == 30
    assert pm25.excedencia is True
    assert pm25.parametro.valor == Decimal("25")
    pm10 = valor(sensor, Periodo.DIA, hora(0), "pm10")
    assert pm10.excedencia is False
    assert valor(sensor, Periodo.DIA, hora(0), "co2").excedencia is None


def test_un_dia_con_menos_de_18_horas_validas_queda_sin_promedio(sensor):
    llenar_dia(sensor, pm25=30.0, horas=range(17))
    procesar_cola(ahora=DESPUES_DEL_DIA)
    cerrar_dia(ahora=datetime(2026, 10, 6, 0, 30))
    dia = valor(sensor, Periodo.DIA, hora(0))
    assert dia.horas_validas == 17
    assert not dia.es_valido
    assert dia.valor is None
    assert dia.excedencia is None


def test_una_lectura_atrasada_de_un_dia_cerrado_lo_recalcula(sensor):
    llenar_dia(sensor, pm25=30.0, horas=range(17))
    procesar_cola(ahora=DESPUES_DEL_DIA)
    cerrar_dia(ahora=datetime(2026, 10, 6, 0, 30))
    assert not valor(sensor, Periodo.DIA, hora(0)).es_valido
    # Llega tarde la hora 17: el día ya tiene 18 horas válidas.
    guardar(sensor, hora(17, 5), 30.0)
    guardar(sensor, hora(17, 35), 30.0)
    procesar_cola(ahora=datetime(2026, 10, 6, 2, 0))
    dia = valor(sensor, Periodo.DIA, hora(0))
    assert dia.horas_validas == 18
    assert dia.es_valido


def test_el_cierre_del_mes_guarda_los_valores_del_mes(sensor):
    llenar_dia(sensor, pm25=30.0, pm10=40.0, dia=date(2026, 10, 30))
    llenar_dia(sensor, pm25=20.0, pm10=40.0, dia=date(2026, 10, 31))
    procesar_cola(ahora=datetime(2026, 11, 1, 0, 10))
    cerrar_dia(ahora=datetime(2026, 10, 31, 0, 30))
    cerrar_dia(ahora=datetime(2026, 11, 1, 0, 30))
    assert cerrar_mes(ahora=datetime(2026, 11, 1, 0, 45)) == (2026, 10)
    mes = valor(sensor, Periodo.MES, datetime(2026, 10, 1))
    assert mes.dias_validos == 2
    assert mes.dias_con_medicion == 2
    assert mes.valor == Decimal("25.0")
    assert mes.dias_excedencia == 1
    assert mes.es_valido
    assert valor(sensor, Periodo.MES, datetime(2026, 10, 1), "co2").dias_excedencia is None


def test_los_sensores_dados_de_baja_no_se_cierran(sensor):
    Sensor.objects.filter(pk=sensor.pk).update(
        estado="dado_de_baja", dado_de_baja_en=datetime(2026, 10, 1)
    )
    cerrar_hora(ahora=hora(11, 20))
    assert not ValorCalculado.objects.exists()


def test_el_worker_registra_las_tareas_del_calculo():
    from apscheduler.schedulers.background import BackgroundScheduler

    from calculo import jobs

    programador = BackgroundScheduler()
    jobs.registrar(programador, "calculo")
    tareas = {t.id: t for t in programador.get_jobs()}
    assert set(tareas) == {"cola_recalculo", "cierre_hora", "cierre_dia", "cierre_mes"}
    assert all(t.executor == "calculo" for t in tareas.values())
    assert str(tareas["cierre_hora"].trigger) == "cron[minute='20']"
    assert str(tareas["cierre_dia"].trigger) == "cron[hour='0', minute='30']"
    assert str(tareas["cierre_mes"].trigger) == "cron[day='1', hour='0', minute='45']"
