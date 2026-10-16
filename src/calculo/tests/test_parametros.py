from datetime import date
from decimal import Decimal

import pytest

from calculo.dominio.tipos import TipoParametro, Variable
from calculo.models import Parametro
from calculo.selectors import como_parametro_vigente, parametro_vigente

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "variable, fecha, esperado",
    [
        (Variable.PM25, date(2021, 12, 26), 41),
        (Variable.PM25, date(2023, 12, 25), 41),
        (Variable.PM25, date(2025, 6, 15), 33),
        (Variable.PM25, date(2025, 12, 25), 33),
        (Variable.PM25, date(2025, 12, 26), 25),
        (Variable.PM25, date(2026, 6, 15), 25),
        (Variable.PM10, date(2022, 5, 1), 70),
        (Variable.PM10, date(2024, 5, 1), 60),
        (Variable.PM10, date(2026, 5, 1), 50),
    ],
)
def test_limite_de_24h_segun_la_fecha(variable, fecha, esperado):
    parametro = parametro_vigente(TipoParametro.LIMITE_24H, variable, fecha)
    assert parametro.valor == Decimal(esperado)


def test_antes_de_la_norma_no_hay_limite():
    assert parametro_vigente(TipoParametro.LIMITE_24H, Variable.PM25, date(2021, 3, 10)) is None


def test_limites_anuales():
    assert (
        parametro_vigente(TipoParametro.LIMITE_ANUAL, Variable.PM10, date(2025, 12, 31)).valor == 20
    )
    assert (
        parametro_vigente(TipoParametro.LIMITE_ANUAL, Variable.PM25, date(2023, 1, 1)).valor == 10
    )


def test_co2_no_tiene_limite():
    assert parametro_vigente(TipoParametro.LIMITE_24H, Variable.CO2, date(2026, 1, 1)) is None


def test_un_cambio_nuevo_no_altera_los_dias_anteriores():
    Parametro.objects.create(
        tipo="limite_24h",
        norma="NOM-025-SSA1-2021",
        variable="pm25",
        valor=Decimal("20"),
        unidad="µg/m³",
        vigente_desde=date(2027, 1, 1),
    )
    assert parametro_vigente(TipoParametro.LIMITE_24H, Variable.PM25, date(2026, 6, 1)).valor == 25
    assert parametro_vigente(TipoParametro.LIMITE_24H, Variable.PM25, date(2027, 6, 1)).valor == 20


def test_como_parametro_vigente():
    vigente = como_parametro_vigente(
        parametro_vigente(TipoParametro.LIMITE_24H, Variable.PM25, date(2026, 1, 10))
    )
    assert vigente.variable == Variable.PM25
    assert vigente.valor == Decimal("25")
    assert vigente.aplica_en(date(2026, 1, 10))
