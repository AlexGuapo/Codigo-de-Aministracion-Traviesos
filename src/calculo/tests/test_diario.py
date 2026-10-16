from datetime import date, datetime
from decimal import Decimal

from calculo.dominio.diario import promedio_diario
from calculo.dominio.tipos import ParametroVigente, ResultadoHora, TipoParametro, Variable

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


# Excedencia diaria contra el límite de 24 h que regía ese día

LIMITE_ANIO_5 = ParametroVigente(
    tipo=TipoParametro.LIMITE_24H,
    norma="NOM-025-SSA1-2021",
    variable=Variable.PM25,
    valor=Decimal("25.00"),
    unidad="µg/m³",
    vigente_desde=date(2025, 12, 26),
)
LIMITE_ANIO_3 = ParametroVigente(
    tipo=TipoParametro.LIMITE_24H,
    norma="NOM-025-SSA1-2021",
    variable=Variable.PM25,
    valor=Decimal("33.00"),
    unidad="µg/m³",
    vigente_desde=date(2023, 12, 26),
    vigente_hasta=date(2025, 12, 25),
)


def dia_con(valor, n=24, fecha=DIA, limite=LIMITE_ANIO_5):
    return promedio_diario(fecha, Variable.PM25, horas([valor] * n), limite)


def test_casos_de_la_ficha():
    assert dia_con("27.0", n=20).excedencia is True
    assert dia_con("30.0", n=17).excedencia is None
    assert dia_con("25.4").excedencia is False
    assert dia_con("25.5").excedencia is True
    assert dia_con("30.0", fecha=date(2025, 12, 25), limite=LIMITE_ANIO_3).excedencia is False
    assert dia_con("30.0", fecha=date(2025, 12, 26), limite=LIMITE_ANIO_5).excedencia is True


def test_guarda_el_limite_con_que_se_comparo():
    assert dia_con("27.0").limite == LIMITE_ANIO_5


def test_igual_al_limite_no_es_excedencia():
    assert dia_con("25.0").excedencia is False


def test_limite_que_no_regia_ese_dia_no_se_usa():
    dia = dia_con("40.0", fecha=date(2025, 6, 15), limite=LIMITE_ANIO_5)
    assert dia.excedencia is None
    assert dia.limite is None


def test_sin_limite_el_dia_no_se_evalua():
    dia = dia_con("40.0", limite=None)
    assert dia.valido
    assert dia.excedencia is None


def test_variables_sin_limite_no_tienen_excedencia():
    dia = promedio_diario(DIA, Variable.CO2, horas(["600.0"] * 24), LIMITE_ANIO_5)
    assert dia.excedencia is None


def test_limite_de_otra_variable_no_se_usa():
    dia = promedio_diario(DIA, Variable.PM10, horas(["40.0"] * 24), LIMITE_ANIO_5)
    assert dia.excedencia is None
