"""La validez de cada hora calculada con lecturas guardadas: de la llegada al valor de la hora."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from calculo.models import Periodo, ValorCalculado
from tests.integracion.ayudas import calcular, crear_sensor, llega

A_LAS_10 = datetime(2026, 9, 26, 10, 0)
DESPUES = datetime(2026, 9, 26, 12, 0)


def m(minuto, segundo=0):
    return A_LAS_10 + timedelta(minutes=minuto, seconds=segundo)


@pytest.fixture
def sensor(db):
    return crear_sensor()


def hora_10(sensor, variable="pm25"):
    return ValorCalculado.objects.get(
        sensor=sensor, periodo=Periodo.HORA, inicio=A_LAS_10, variable=variable
    )


@pytest.mark.parametrize(
    ("anterior", "lecturas", "intervalo", "minutos", "valida"),
    [
        (m(-17), [m(12), m(41)], 1800, "58.0", True),  # caso 1
        (m(-28), [m(1), m(30), m(59)], 1800, "60.0", True),  # caso 2, con tope
        (m(-17), [m(12)], 1800, "29.0", False),  # caso 4
        (m(-10), [m(5), m(35), m(50)], 900, "45.0", True),  # caso 7
        (m(-10), [m(5), m(50)], 900, "30.0", False),  # caso 8
    ],
)
def test_casos_de_la_hora_valida(sensor, anterior, lecturas, intervalo, minutos, valida):
    for hora in [anterior, *lecturas]:
        llega(sensor, hora, pm25=10.0, intervalo_s=intervalo)
    calcular(DESPUES)
    resultado = hora_10(sensor)
    assert resultado.cobertura_min == Decimal(minutos)
    assert resultado.es_valido is valida


def test_reinicio_cubre_solo_el_tiempo_desde_la_anterior(sensor):
    # Caso 5: la de las 10:08 llega 3 minutos después de la de las 10:05.
    for hora in [m(-24), m(5), m(8)]:
        llega(sensor, hora, pm25=10.0)
    calcular(DESPUES)
    assert hora_10(sensor).cobertura_min == Decimal("32.0")
    assert not hora_10(sensor).es_valido


def test_una_copia_no_cuenta_dos_veces(sensor):
    # Caso 9: la copia idéntica a los 2 s no se guarda; la hora queda igual que sin ella.
    for hora in [m(-17), m(12), m(12, 2), m(41)]:
        llega(sensor, hora, pm25=10.0)
    calcular(DESPUES)
    assert hora_10(sensor).cobertura_min == Decimal("58.0")
    assert hora_10(sensor).lecturas_contadas == 2


def test_una_lectura_sin_intervalo_no_cubre_minutos(sensor):
    # Caso 12: una sola lectura sin intervalo después de 3 horas sin transmitir.
    llega(sensor, m(-180), pm25=10.0)
    llega(sensor, m(20), pm25=10.0, intervalo_s=None)
    calcular(DESPUES)
    assert hora_10(sensor).cobertura_min == Decimal("0.0")
    assert not hora_10(sensor).es_valido


def test_la_validez_es_por_variable(sensor):
    llega(sensor, m(-17), pm25=10.0, pm10=12.0)
    llega(sensor, m(12), pm25=10.0, pm10=12.0)
    llega(sensor, m(41), pm25=10.0, pm10=None)
    calcular(DESPUES)
    assert hora_10(sensor, "pm25").es_valido
    assert not hora_10(sensor, "pm10").es_valido


def test_una_lectura_que_llega_tarde_cambia_la_hora_ya_calculada(sensor):
    llega(sensor, m(-17), pm25=10.0)
    llega(sensor, m(12), pm25=10.0)
    calcular(m(30))
    assert not hora_10(sensor).es_valido
    llega(sensor, m(41), pm25=10.0)
    calcular(DESPUES)
    assert hora_10(sensor).es_valido
