"""La concentración horaria con las lecturas guardadas y la validez de su hora."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from calculo.models import EstadoCalculo, Periodo, ValorCalculado
from calculo.services import cerrar_hora
from tests.integracion.ayudas import calcular, crear_sensor, llega

A_LAS_10 = datetime(2026, 9, 26, 10, 0)


def m(minuto, segundo=0):
    return A_LAS_10 + timedelta(minutes=minuto, seconds=segundo)


@pytest.fixture
def sensor(db):
    return crear_sensor()


def hora_10(sensor, variable="pm25"):
    return ValorCalculado.objects.get(
        sensor=sensor, periodo=Periodo.HORA, inicio=A_LAS_10, variable=variable
    )


def test_18_4_y_21_0_dan_19_7(sensor):
    llega(sensor, m(-25), pm25=15.0)
    llega(sensor, m(5), pm25=18.4)
    llega(sensor, m(35), pm25=21.0)
    calcular(m(40))
    assert hora_10(sensor).valor == Decimal("19.7")


def test_una_hora_que_no_es_valida_no_tiene_concentracion(sensor):
    llega(sensor, m(-17), pm25=15.0)
    llega(sensor, m(12), pm25=18.4)
    calcular(m(40))
    assert hora_10(sensor).valor is None


def test_entre_copias_discrepantes_cuenta_la_de_hora_mas_temprana(sensor):
    llega(sensor, m(-25), pm25=15.0)
    llega(sensor, m(5, 2), pm25=18.9)
    llega(sensor, m(5), pm25=18.4)
    llega(sensor, m(35), pm25=21.0)
    calcular(m(40))
    assert hora_10(sensor).valor == Decimal("19.7")


def test_una_lectura_sin_dato_no_entra_al_promedio_ni_cuenta_como_cero(sensor):
    llega(sensor, m(-25), pm25=15.0, pm10=20.0)
    llega(sensor, m(5), pm25=18.4, pm10=None)
    llega(sensor, m(20), pm25=18.4, pm10=30.0)
    llega(sensor, m(35), pm25=21.0, pm10=30.0)
    calcular(m(50))
    # PM10 con 2 lecturas que cuentan: 30 minutos cubiertos, la hora no es válida.
    assert not hora_10(sensor, "pm10").es_valido
    assert hora_10(sensor, "pm25").valor == Decimal("19.3")


def test_el_ruido_del_flotante_no_cambia_el_resultado(sensor):
    llega(sensor, m(-25), pm25=15.0)
    llega(sensor, m(5), pm25=4.0999999999)
    llega(sensor, m(35), pm25=4.1)
    calcular(m(40))
    assert hora_10(sensor).valor == Decimal("4.1")


def test_la_hora_en_curso_es_preliminar_y_al_cerrar_queda_cerrada(sensor):
    llega(sensor, m(-25), pm25=15.0)
    llega(sensor, m(5), pm25=18.4)
    llega(sensor, m(35), pm25=21.0)
    calcular(m(40))
    assert hora_10(sensor).estado == EstadoCalculo.PRELIMINAR
    cerrar_hora(ahora=m(80))
    assert hora_10(sensor).estado == EstadoCalculo.CERRADO
    assert hora_10(sensor).valor == Decimal("19.7")
