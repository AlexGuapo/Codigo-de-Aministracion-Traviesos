"""El reporte diario con el promedio de 24 h calculado de las lecturas que llegaron."""

from datetime import date, datetime, timedelta

import pytest
from django.urls import reverse

from calculo.services import cerrar_dia
from tests.integracion.ayudas import (
    calcular,
    crear_sensor,
    dia_completo,
    llega,
    sesion_de_administrador,
)

DIA = date(2026, 3, 10)
CIERRE = datetime(2026, 3, 11, 0, 30)


@pytest.fixture
def cliente(client, db):
    sesion_de_administrador(client)
    return client


def reporte(cliente, *sensores):
    return cliente.get(
        reverse("reportes:diario"),
        {"fecha": DIA.isoformat(), "sensores": [sensor.pk for sensor in sensores]},
    )


def test_la_tabla_coincide_con_el_calculo_de_las_lecturas(cliente):
    g3, g4 = crear_sensor("G3"), crear_sensor("G4")
    dia_completo(g3, DIA, pm25=27.0, horas=range(20))
    dia_completo(g4, DIA, pm25=12.0, pm10=20.0)
    calcular(CIERRE)
    cerrar_dia(ahora=CIERRE)
    contexto = reporte(cliente, g3, g4).context["reporte"]
    pm25 = next(fila for fila in contexto.tabla if fila.etiqueta == "PM2.5")
    pm10 = next(fila for fila in contexto.tabla if fila.etiqueta == "PM10")
    assert [celda.texto for celda in pm25.celdas] == ["27 (20 h)", "12 (24 h)"]
    assert [celda.excedencia for celda in pm25.celdas] == [True, False]
    assert [celda.texto for celda in pm10.celdas] == ["datos insuficientes", "20 (24 h)"]


def test_el_reporte_se_arma_con_los_datos_del_momento(cliente):
    sensor = crear_sensor("G3")
    dia_completo(sensor, DIA, pm25=10.0, horas=range(17))
    calcular(CIERRE)
    cerrar_dia(ahora=CIERRE)
    assert "datos insuficientes" in reporte(cliente, sensor).content.decode()
    # Llega tarde la hora 17: al volver a abrir el reporte ya tiene el promedio.
    inicio = datetime.combine(DIA, datetime.min.time()).replace(hour=17)
    llega(sensor, inicio.replace(minute=5), pm25=10.0)
    llega(sensor, inicio.replace(minute=35), pm25=10.0)
    calcular(CIERRE + timedelta(hours=1))
    assert "10 (18 h)" in reporte(cliente, sensor).content.decode()


def test_la_grafica_y_los_periodos_salen_de_las_mismas_lecturas(cliente):
    sensor = crear_sensor("G4")
    inicio = datetime.combine(DIA, datetime.min.time())
    for paso in range(7):
        llega(sensor, inicio + timedelta(minutes=10 + 30 * paso), pm25=8.0)
    calcular(CIERRE)
    html = reporte(cliente, sensor).content.decode()
    contexto = reporte(cliente, sensor).context["reporte"]
    serie = next(g for g in contexto.graficas if g["variable"] == "pm25")["series"][0]
    assert len(serie["puntos"]) == 7
    assert "G4 sin transmitir de 03:10 a 23:59" in html
