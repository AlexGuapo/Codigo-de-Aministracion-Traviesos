from datetime import date, datetime
from decimal import Decimal

from calculo.dominio.diario import promedio_diario
from calculo.dominio.tipos import ResultadoHora, Variable

DIA = date(2026, 1, 10)


def horas(valores, no_validas=0):
    resultado = [
        ResultadoHora(
            inicio=datetime(2026, 1, 10, i),
            variable=Variable.PM25,
            cobertura_s=3600,
            valida=True,
            concentracion=Decimal(v),
            lecturas_usadas=2,
        )
        for i, v in enumerate(valores)
    ]
    resultado += [
        ResultadoHora(
            inicio=datetime(2026, 1, 10, 23),
            variable=Variable.PM25,
            cobertura_s=1740,
            valida=False,
            concentracion=None,
            lecturas_usadas=1,
        )
    ] * no_validas
    return resultado


def test_20_horas_que_suman_540():
    dia = promedio_diario(DIA, Variable.PM25, horas(["27.0"] * 20))
    assert dia.valido
    assert dia.horas_validas == 20
    assert dia.promedio == Decimal("27.0")
    assert dia.promedio_entero == 27


def test_17_horas_son_datos_insuficientes():
    dia = promedio_diario(DIA, Variable.PM25, horas(["30.0"] * 17, no_validas=7))
    assert not dia.valido
    assert dia.horas_validas == 17
    assert dia.promedio is None
    assert dia.promedio_entero is None


def test_18_horas_ya_es_dia_valido():
    assert promedio_diario(DIA, Variable.PM25, horas(["10.0"] * 18)).valido


def test_25_4_se_informa_como_25():
    dia = promedio_diario(DIA, Variable.PM25, horas(["25.4"] * 24))
    assert dia.promedio_entero == 25


def test_25_5_se_informa_como_26():
    dia = promedio_diario(DIA, Variable.PM25, horas(["25.5"] * 24))
    assert dia.promedio_entero == 26


def test_el_promedio_conserva_un_decimal():
    dia = promedio_diario(DIA, Variable.PM25, horas(["10.0"] * 9 + ["10.1"] * 9))
    assert dia.promedio == Decimal("10.1")


def test_horas_no_validas_no_entran_al_promedio():
    dia = promedio_diario(DIA, Variable.PM25, horas(["20.0"] * 20, no_validas=4))
    assert dia.horas_validas == 20
    assert dia.promedio == Decimal("20.0")


def test_dia_sin_horas():
    dia = promedio_diario(DIA, Variable.PM25, [])
    assert not dia.valido
    assert dia.horas_validas == 0
