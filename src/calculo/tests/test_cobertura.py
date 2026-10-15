from datetime import datetime
from decimal import Decimal

import pytest

from calculo.dominio.cobertura import cobertura_s, es_hora_valida
from calculo.dominio.tipos import LecturaParaCalculo

MIN = 60


def lectura(hhmm, intervalo_min=30, valor="10.0", anomala=False, segundos=0):
    h, m = map(int, hhmm.split(":"))
    return LecturaParaCalculo(
        hora=datetime(2026, 9, 26, h, m, segundos),
        valor=None if valor is None else Decimal(valor),
        intervalo_s=None if intervalo_min is None else intervalo_min * MIN,
        anomala=anomala,
    )


# Casos de la hora de las 10 con su lectura anterior; resultado en minutos cubiertos
CASOS = [
    ("1: dos lecturas", ["10:12", "10:41"], "09:43", 30, 58, True),
    ("2: tres lecturas, tope de 60", ["10:01", "10:30", "10:59"], "09:32", 30, 60, True),
    ("3: hueco interno cubre solo su intervalo", ["10:01", "10:59"], "09:32", 30, 59, True),
    ("4: una sola lectura", ["10:12"], "09:43", 30, 29, False),
    ("5: reinicio a los 3 minutos", ["10:05", "10:08"], "09:36", 30, 32, False),
    ("6: cada 15 minutos", ["10:05", "10:20", "10:35", "10:50"], "09:50", 15, 60, True),
    ("7: justo el 75 %", ["10:05", "10:35", "10:50"], "09:50", 15, 45, True),
    ("8: dos de cuatro", ["10:05", "10:50"], "09:50", 15, 30, False),
]


@pytest.mark.parametrize("nombre, horas, anterior, delta, minutos, valida", CASOS)
def test_casos_de_la_hora_valida(nombre, horas, anterior, delta, minutos, valida):
    lecturas = [lectura(h, delta) for h in horas]
    cubiertos = cobertura_s(lecturas, lectura(anterior, delta))
    assert cubiertos == minutos * MIN
    assert es_hora_valida(cubiertos) is valida


def test_caso_9_la_copia_no_se_recibe_y_no_cuenta():
    # La copia de 10:12:02 la quita quien consulta; el resultado es el mismo que sin ella.
    lecturas = [lectura("10:12"), lectura("10:41")]
    assert cobertura_s(lecturas, lectura("09:43")) == 58 * MIN


def test_caso_10_la_anomala_no_cubre_pero_es_anterior():
    lecturas = [lectura("10:12", anomala=True), lectura("10:41")]
    cubiertos = cobertura_s(lecturas, lectura("09:43"))
    assert cubiertos == 29 * MIN
    assert not es_hora_valida(cubiertos)


def test_caso_11_lectura_sin_intervalo_no_cubre():
    lecturas = [
        lectura("10:05", 15),
        lectura("10:20", None),
        lectura("10:35", 15),
        lectura("10:50", 15),
    ]
    cubiertos = cobertura_s(lecturas, lectura("09:50", 15))
    assert cubiertos == 45 * MIN
    assert es_hora_valida(cubiertos)


def test_caso_12_una_lectura_sin_intervalo_tras_tres_horas():
    lecturas = [lectura("10:12", None)]
    assert cobertura_s(lecturas, lectura("07:00")) == 0


def test_lectura_sin_valor_no_cubre_pero_sirve_de_anterior():
    lecturas = [lectura("10:12", valor=None), lectura("10:41")]
    assert cobertura_s(lecturas, lectura("09:43")) == 29 * MIN


def test_primera_lectura_del_sensor_cubre_su_intervalo():
    assert cobertura_s([lectura("10:12")], None) == 30 * MIN


def test_hora_sin_lecturas():
    assert cobertura_s([], lectura("09:43")) == 0


def test_no_importa_el_orden_en_que_llegan():
    lecturas = [lectura("10:41"), lectura("10:12")]
    assert cobertura_s(lecturas, lectura("09:43")) == 58 * MIN


def test_lectura_a_las_11_en_punto_es_de_la_hora_de_las_11():
    # Quien consulta separa las horas; aquí solo se confirma que cubre desde la anterior.
    assert cobertura_s([lectura("11:00")], lectura("10:41")) == 19 * MIN


def test_limite_de_45_minutos():
    assert es_hora_valida(45 * MIN)
    assert not es_hora_valida(45 * MIN - 1)
