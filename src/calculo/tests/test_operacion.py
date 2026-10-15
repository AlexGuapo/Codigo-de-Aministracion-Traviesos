from datetime import datetime, timedelta

from calculo.dominio.operacion import fuera_de_operacion, hay_hueco, umbral_sin_transmitir

ULTIMA = datetime(2026, 10, 15, 15, 5)


def test_umbral_con_intervalo_de_30_minutos():
    assert umbral_sin_transmitir(1800) == timedelta(minutes=65)


def test_umbral_sin_intervalo():
    assert umbral_sin_transmitir(None) == timedelta(minutes=65)


def test_todavia_transmite_a_las_16_09():
    assert not fuera_de_operacion(ULTIMA, 1800, datetime(2026, 10, 15, 16, 9))


def test_fuera_de_operacion_a_las_16_11():
    assert fuera_de_operacion(ULTIMA, 1800, datetime(2026, 10, 15, 16, 11))


def test_un_envio_perdido_no_es_hueco():
    assert not hay_hueco(datetime(2026, 10, 15, 8), datetime(2026, 10, 15, 8, 58), 1800)


def test_dos_envios_perdidos_si_son_hueco():
    assert hay_hueco(datetime(2026, 10, 15, 8), datetime(2026, 10, 15, 9, 27), 1800)


def test_sensor_sin_lecturas_no_se_marca_aqui():
    assert not fuera_de_operacion(None, 1800, ULTIMA)
