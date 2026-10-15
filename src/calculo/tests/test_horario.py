from datetime import datetime
from decimal import Decimal

from calculo.dominio.horario import calcular_hora, concentracion_horaria
from calculo.dominio.redondeo import a_entero, a_un_decimal
from calculo.dominio.tipos import LecturaParaCalculo, Variable

INICIO = datetime(2026, 9, 26, 10)


def lectura(hhmm, valor, intervalo_s=1800, anomala=False):
    h, m = map(int, hhmm.split(":"))
    return LecturaParaCalculo(
        hora=datetime(2026, 9, 26, h, m),
        valor=None if valor is None else Decimal(valor),
        intervalo_s=intervalo_s,
        anomala=anomala,
    )


def test_promedio_de_la_hora_valida():
    lecturas = [lectura("10:05", "18.4"), lectura("10:35", "21.0")]
    resultado = calcular_hora(INICIO, Variable.PM25, lecturas, lectura("09:36", "17.0"))
    assert resultado.valida
    assert resultado.concentracion == Decimal("19.7")
    assert resultado.lecturas_usadas == 2


def test_hora_no_valida_queda_sin_promedio():
    resultado = calcular_hora(
        INICIO, Variable.PM25, [lectura("10:12", "18.4")], lectura("09:43", "1")
    )
    assert not resultado.valida
    assert resultado.concentracion is None
    assert resultado.cobertura_s == 29 * 60


def test_validez_por_variable():
    # PM2.5 llega en las dos lecturas y PM10 solo en una: la hora vale para PM2.5 y no para PM10.
    anterior = lectura("09:43", "1")
    pm25 = calcular_hora(
        INICIO, Variable.PM25, [lectura("10:12", "8"), lectura("10:41", "9")], anterior
    )
    pm10 = calcular_hora(
        INICIO, Variable.PM10, [lectura("10:12", "8"), lectura("10:41", None)], anterior
    )
    assert pm25.valida
    assert not pm10.valida


def test_lectura_sin_intervalo_entra_al_promedio():
    lecturas = [
        lectura("10:05", "10.0", 900),
        lectura("10:20", "20.0", None),
        lectura("10:35", "10.0", 900),
        lectura("10:50", "10.0", 900),
    ]
    resultado = calcular_hora(INICIO, Variable.PM25, lecturas, lectura("09:50", "1", 900))
    assert resultado.valida
    assert resultado.concentracion == Decimal("12.5")


def test_la_anomala_no_entra_al_promedio():
    lecturas = [
        lectura("10:01", "50", anomala=True),
        lectura("10:30", "10"),
        lectura("10:59", "12"),
    ]
    assert concentracion_horaria(lecturas) == Decimal("11.0")


def test_quita_el_ruido_del_flotante():
    lecturas = [
        LecturaParaCalculo(hora=INICIO, valor=a_un_decimal(4.099999904632568), intervalo_s=1800)
    ]
    assert concentracion_horaria(lecturas) == Decimal("4.1")


def test_nunca_inventa_cero():
    assert concentracion_horaria([lectura("10:05", None)]) is None


def test_redondeo_de_la_norma():
    assert a_entero(Decimal("2.5")) == 3
    assert a_entero(Decimal("25.5")) == 26
    assert a_entero(Decimal("25.4")) == 25
    assert a_entero(Decimal("9.5")) == 10
    assert a_un_decimal(Decimal("0.05")) == Decimal("0.1")
