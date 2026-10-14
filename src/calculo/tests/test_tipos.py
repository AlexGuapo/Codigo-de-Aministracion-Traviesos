import dataclasses
from datetime import date, datetime
from decimal import Decimal

import pytest

from calculo.dominio.tipos import (
    LecturaParaCalculo,
    ParametroVigente,
    TipoParametro,
    Variable,
)
from recepcion.ports import LecturaNormalizada

HORA = datetime(2026, 10, 1, 10, 12)


def limite_pm25(desde, hasta=None):
    return ParametroVigente(
        tipo=TipoParametro.LIMITE_24H,
        norma="NOM-025-SSA1-2021",
        variable=Variable.PM25,
        valor=Decimal("25"),
        unidad="µg/m³",
        vigente_desde=desde,
        vigente_hasta=hasta,
    )


def test_cada_variable_es_un_campo_de_la_lectura():
    campos = {f.name for f in dataclasses.fields(LecturaNormalizada)}
    for variable in Variable:
        assert variable.value in campos


def test_no_se_calculan_temperatura_humedad_voc_ni_nox():
    nombres = {v.value for v in Variable}
    assert not nombres & {"temperatura_sen55", "humedad_sen55", "voc", "nox"}


def test_lectura_con_valor_cuenta():
    assert LecturaParaCalculo(HORA, Decimal("18.4"), 1800).cuenta


def test_lectura_sin_dato_no_cuenta():
    assert not LecturaParaCalculo(HORA, None, 1800).cuenta


def test_lectura_anomala_no_cuenta():
    assert not LecturaParaCalculo(HORA, Decimal("18.4"), 1800, anomala=True).cuenta


def test_lectura_para_calculo_es_inmutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        LecturaParaCalculo(HORA, Decimal("1"), 1800).valor = Decimal("2")


def test_parametro_abierto_aplica_desde_su_inicio():
    p = limite_pm25(date(2025, 12, 26))
    assert not p.aplica_en(date(2025, 12, 25))
    assert p.aplica_en(date(2025, 12, 26))
    assert p.aplica_en(date(2030, 1, 1))


def test_parametro_cerrado_incluye_su_ultimo_dia():
    p = limite_pm25(date(2023, 12, 26), date(2025, 12, 25))
    assert p.aplica_en(date(2025, 12, 25))
    assert not p.aplica_en(date(2025, 12, 26))


def test_parametro_con_fechas_al_reves_falla():
    with pytest.raises(ValueError):
        limite_pm25(date(2025, 1, 1), date(2024, 1, 1))
