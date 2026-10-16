"""El promedio de 24 h y la excedencia con las concentraciones horarias guardadas."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from calculo.models import Periodo, ValorCalculado
from calculo.services import cerrar_dia
from tests.integracion.ayudas import calcular, crear_sensor, dia_completo, llega

DIA = date(2026, 3, 10)  # año 5 de la NOM-025: PM2.5 25 y PM10 50 µg/m³
CIERRE = datetime(2026, 3, 11, 0, 30)


@pytest.fixture
def sensor(db):
    return crear_sensor()


def el_dia(sensor, variable="pm25"):
    return ValorCalculado.objects.get(
        sensor=sensor,
        periodo=Periodo.DIA,
        inicio=datetime.combine(DIA, datetime.min.time()),
        variable=variable,
    )


def cerrar():
    calcular(CIERRE)
    cerrar_dia(ahora=CIERRE)


def test_20_horas_validas_de_27_dan_27_con_20_horas_y_excedencia(sensor):
    dia_completo(sensor, DIA, pm25=27.0, horas=range(20))
    cerrar()
    dia = el_dia(sensor)
    assert dia.horas_validas == 20
    assert dia.valor == Decimal("27.0")
    assert dia.valor_entero == 27
    assert dia.excedencia is True
    assert dia.parametro.valor == Decimal("25")


def test_igual_al_limite_no_es_excedencia(sensor):
    dia_completo(sensor, DIA, pm25=25.4, pm10=50.0)
    cerrar()
    assert el_dia(sensor).valor_entero == 25
    assert el_dia(sensor).excedencia is False
    assert el_dia(sensor, "pm10").excedencia is False


def test_los_5_suben_al_redondear(sensor):
    dia_completo(sensor, DIA, pm25=25.5)
    cerrar()
    assert el_dia(sensor).valor_entero == 26
    assert el_dia(sensor).excedencia is True


def test_17_horas_validas_son_datos_insuficientes(sensor):
    dia_completo(sensor, DIA, pm25=90.0, horas=range(17))
    cerrar()
    dia = el_dia(sensor)
    assert dia.horas_validas == 17
    assert not dia.es_valido
    assert dia.valor is None
    assert dia.excedencia is None


def test_el_promedio_es_de_las_concentraciones_horarias(sensor):
    # 12 horas a 10 y 12 horas a 20: el promedio del día es 15, no el de las lecturas sueltas.
    dia_completo(sensor, DIA, pm25=10.0, horas=range(12))
    for hora in range(12, 24):
        inicio = datetime.combine(DIA, datetime.min.time()).replace(hour=hora)
        llega(sensor, inicio.replace(minute=5), pm25=20.0)
        llega(sensor, inicio.replace(minute=35), pm25=20.0)
    cerrar()
    assert el_dia(sensor).valor == Decimal("15.0")


def test_co2_tiene_promedio_pero_nunca_excedencia(sensor):
    inicio = datetime.combine(DIA, datetime.min.time())
    for hora in range(24):
        llega(sensor, inicio.replace(hour=hora, minute=5), co2=800.0)
        llega(sensor, inicio.replace(hour=hora, minute=35), co2=800.0)
    cerrar()
    co2 = el_dia(sensor, "co2")
    assert co2.valor_entero == 800
    assert co2.excedencia is None


def test_el_limite_es_el_vigente_ese_dia(sensor):
    # El 15/06/2025 regía el año 3: PM2.5 33 µg/m³, así que 30 no es excedencia.
    dia = date(2025, 6, 15)
    dia_completo(sensor, dia, pm25=30.0)
    cierre = datetime(2025, 6, 16, 0, 30)
    calcular(cierre)
    cerrar_dia(ahora=cierre)
    fila = ValorCalculado.objects.get(
        sensor=sensor,
        periodo=Periodo.DIA,
        inicio=datetime.combine(dia, datetime.min.time()),
        variable="pm25",
    )
    assert fila.excedencia is False
    assert fila.parametro.valor == Decimal("33")
