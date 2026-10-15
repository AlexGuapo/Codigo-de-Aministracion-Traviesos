from datetime import date
from decimal import Decimal

from calculo.dominio.mensual import contar_dias_con_medicion, promedio_mensual
from calculo.dominio.tipos import ResultadoDia, Variable


def dia(n, promedio=None, horas_validas=None, excedencia=None, variable=Variable.PM25):
    valido = promedio is not None
    if horas_validas is None:
        horas_validas = 24 if valido else 0
    return ResultadoDia(
        fecha=date(2026, 10, n),
        variable=variable,
        horas_validas=horas_validas,
        valido=valido,
        promedio=None if promedio is None else Decimal(promedio),
        promedio_entero=None,
        excedencia=excedencia,
        limite=None,
    )


def test_octubre_con_24_dias_validos_que_suman_552():
    dias = [dia(n, "23.0") for n in range(1, 25)] + [dia(n) for n in range(25, 32)]
    mes = promedio_mensual(2026, 10, Variable.PM25, dias, dias_con_medicion=24)
    assert mes.dias_validos == 24
    assert mes.promedio == Decimal("23.0")
    assert mes.promedio_entero == 23


def test_mes_sin_dias_validos():
    mes = promedio_mensual(2026, 10, Variable.PM25, [dia(1, horas_validas=5)], dias_con_medicion=1)
    assert mes.dias_validos == 0
    assert mes.promedio is None
    assert mes.promedio_entero is None


def test_el_promedio_es_de_los_promedios_diarios():
    dias = [dia(1, "10.0"), dia(2, "20.0"), dia(3, "31.0")]
    mes = promedio_mensual(2026, 10, Variable.PM25, dias, dias_con_medicion=3)
    assert mes.promedio == Decimal("20.3")
    assert mes.promedio_entero == 20


def test_dias_con_excedencia_en_orden():
    dias = [dia(15, "30.0", excedencia=True), dia(3, "28.0", excedencia=True), dia(4, "10.0")]
    mes = promedio_mensual(2026, 10, Variable.PM25, dias, dias_con_medicion=3)
    assert mes.dias_con_excedencia == (date(2026, 10, 3), date(2026, 10, 15))


def test_dia_con_16_horas_cuenta_como_medicion_y_no_como_valido():
    dias = [dia(27, horas_validas=16), dia(28, "12.0")]
    assert contar_dias_con_medicion(dias) == 2
    mes = promedio_mensual(2026, 10, Variable.PM25, dias, dias_con_medicion=2)
    assert mes.dias_validos == 1


def test_dia_sin_horas_validas_no_cuenta_como_medicion():
    assert contar_dias_con_medicion([dia(5, horas_validas=0)]) == 0


def test_dias_con_medicion_se_cuentan_una_vez_entre_variables():
    dias = [
        dia(5, horas_validas=3, variable=Variable.PM25),
        dia(5, horas_validas=2, variable=Variable.CO2),
        dia(6, horas_validas=0, variable=Variable.PM25),
        dia(6, horas_validas=1, variable=Variable.CO2),
    ]
    assert contar_dias_con_medicion(dias) == 2
