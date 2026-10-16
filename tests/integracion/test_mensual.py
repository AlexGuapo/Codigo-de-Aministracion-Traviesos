"""El reporte mensual con los promedios diarios que calcula el proceso de fondo."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from calculo.models import EstadoCalculo, Periodo, ValorCalculado
from calculo.services import cerrar_dia, cerrar_mes
from tests.integracion.ayudas import crear_sensor, llega, sesion_de_administrador

OCTUBRE = date(2025, 10, 1)  # año 3 de la NOM-025: PM2.5 33 y PM10 60 µg/m³ en 24 h


def horas(sensor, dia, valor, cuantas=20):
    """`cuantas` horas válidas de PM2.5 con el mismo valor, como las deja la cola de recálculo."""
    for hora in range(cuantas):
        ValorCalculado.objects.create(
            sensor=sensor,
            variable="pm25",
            periodo=Periodo.HORA,
            inicio=datetime.combine(dia, datetime.min.time()) + timedelta(hours=hora),
            cobertura_min=Decimal("60"),
            lecturas_contadas=2,
            es_valido=True,
            valor=Decimal(str(valor)),
            version_calculo="prueba",
            estado=EstadoCalculo.CERRADO,
        )


@pytest.fixture
def octubre(db):
    """24 días válidos (22 a 22 µg/m³ y 2 a 34), suman 552; el 27 tiene solo 16 horas válidas."""
    sensor = crear_sensor("G3", desde=date(2025, 9, 1))
    dias = [OCTUBRE + timedelta(days=n) for n in range(24)]
    for dia in dias:
        horas(sensor, dia, 34.0 if dia.day in (5, 12) else 22.0)
        llega(sensor, datetime.combine(dia, datetime.min.time()).replace(hour=1), pm25=22.0)
    dia_27 = date(2025, 10, 27)
    horas(sensor, dia_27, 50.0, cuantas=16)
    llega(sensor, datetime.combine(dia_27, datetime.min.time()).replace(hour=1), pm25=50.0)
    for dia in [*dias, dia_27]:
        cerrar_dia(
            ahora=datetime.combine(dia + timedelta(days=1), datetime.min.time()).replace(minute=30)
        )
    cerrar_mes(ahora=datetime(2025, 11, 1, 0, 45))
    return sensor


def test_los_valores_del_mes_guardados_al_cerrarlo(octubre):
    mes = ValorCalculado.objects.get(
        sensor=octubre, periodo=Periodo.MES, inicio=datetime(2025, 10, 1), variable="pm25"
    )
    assert mes.valor_entero == 23
    assert mes.dias_validos == 24
    assert mes.dias_con_medicion == 25
    assert mes.dias_excedencia == 2


def test_la_portada_del_mes(client, octubre):
    sesion_de_administrador(client)
    respuesta = client.get(reverse("reportes:mensual"), {"mes": "2025-10", "sensores": octubre.pk})
    html = respuesta.content.decode()
    assert "Reporte mensual · octubre de 2025" in html
    assert "23 µg/m³ (24 de 31 días válidos)" in html
    assert "5 oct y 12 oct" in html
    assert "sin días válidos" in html  # PM10 no tiene ningún día válido
    assert "vigentes al 31/10/2025" in html
    assert "33 µg/m³" in html and "60 µg/m³" in html
    assert "incumple" not in html.lower()


def test_una_lamina_por_dia_con_lecturas(client, octubre):
    sesion_de_administrador(client)
    respuesta = client.get(reverse("reportes:mensual"), {"mes": "2025-10", "sensores": octubre.pk})
    assert len(respuesta.context["laminas"]) == 25
    lamina = client.get(
        reverse("reportes:lamina"), {"fecha": "2025-10-05", "sensores": octubre.pk}
    ).content.decode()
    assert "Reporte diario · domingo 5 de octubre de 2025" in lamina
    assert "34 (20 h)" in lamina
    assert "excedencia" in lamina
