from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from calculo.models import EstadoCalculo, Periodo, ValorCalculado
from cuentas.services import crear_administrador
from lecturas.models import Lectura
from reportes.reporte_diario import armar_reporte_diario, periodos_sin_transmitir
from reportes.views.diario import dia_pedido
from sensores.models import Sensor

DIA = date(2025, 12, 1)
DESPUES = datetime(2025, 12, 5, 12, 0)
CONTRASENA = "contrasena-de-prueba"


def a_las(h, m=0, dia=DIA):
    return datetime(dia.year, dia.month, dia.day, h, m)


def crear_sensor(nombre):
    return Sensor.objects.create(
        nombre_corto=nombre,
        mac_cifrada="c",
        mac_huella=nombre.ljust(64, "x"),
        token_cifrado="t",
        lecturas_desde=date(2025, 11, 1),
    )


def lectura(sensor, hora, pm25=20.0, intervalo_s=1800):
    return Lectura.objects.create(
        sensor=sensor,
        hora=hora,
        hora_nube_original="x",
        ruta="history",
        origen="nube",
        pm2_5=pm25,
        intervalo_s=intervalo_s,
        huella_valores=f"{sensor.pk}-{hora.isoformat()}".ljust(64, "x"),
        crudo="{}",
    )


def horas_validas(sensor, valores, variable="pm25", dia=DIA):
    for h, valor in enumerate(valores):
        ValorCalculado.objects.create(
            sensor=sensor,
            variable=variable,
            periodo=Periodo.HORA,
            inicio=a_las(h, dia=dia),
            cobertura_min=Decimal("60"),
            lecturas_contadas=2,
            es_valido=True,
            valor=Decimal(str(valor)),
            version_calculo="prueba",
            estado=EstadoCalculo.CERRADO,
        )


@pytest.fixture
def g3(db):
    return crear_sensor("G3")


@pytest.fixture
def g4(db):
    return crear_sensor("G4")


def celda(reporte, variable, sensor):
    fila = next(fila for fila in reporte.tabla if fila.etiqueta == variable)
    return fila.celdas[[s.pk for s in reporte.sensores].index(sensor.pk)]


# Título y día


def test_el_titulo_lleva_el_dia_de_la_semana(g3):
    lectura(g3, a_las(10))
    reporte = armar_reporte_diario(DIA, [g3], DESPUES)
    assert reporte.titulo == "Reporte diario · lunes 1 de diciembre de 2025"


def test_sin_elegir_dia_es_el_ultimo_dia_completo():
    assert dia_pedido(None, date(2025, 12, 2)) == DIA
    assert dia_pedido("no-es-fecha", date(2025, 12, 2)) == DIA
    assert dia_pedido("2025-11-20", date(2025, 12, 2)) == date(2025, 11, 20)
    assert dia_pedido("2099-01-01", date(2025, 12, 2)) == date(2025, 12, 2)


# Tabla de promedios de 24 h


def test_27_con_20_horas_validas(g3):
    lectura(g3, a_las(10))
    horas_validas(g3, [27.0] * 20)
    pm25 = celda(armar_reporte_diario(DIA, [g3], DESPUES), "PM2.5", g3)
    assert pm25.texto == "27 (20 h)"


def test_la_excedencia_usa_el_limite_vigente_ese_dia(g3):
    # 01/12/2025: año 3 de la NOM-025, PM2.5 = 33 µg/m³; 28/12/2025: año 5, 25 µg/m³.
    dia_5 = date(2025, 12, 28)
    lectura(g3, a_las(10))
    lectura(g3, a_las(10, dia=dia_5))
    horas_validas(g3, [30.0] * 20)
    horas_validas(g3, [30.0] * 20, dia=dia_5)
    assert not celda(armar_reporte_diario(DIA, [g3], DESPUES), "PM2.5", g3).excedencia
    reporte_5 = armar_reporte_diario(dia_5, [g3], datetime(2026, 1, 2))
    assert celda(reporte_5, "PM2.5", g3).excedencia


def test_17_horas_validas_dice_datos_insuficientes_y_sin_marca(g3):
    lectura(g3, a_las(10))
    horas_validas(g3, [90.0] * 17)
    pm25 = celda(armar_reporte_diario(DIA, [g3], DESPUES), "PM2.5", g3)
    assert pm25.texto == "datos insuficientes"
    assert not pm25.excedencia


def test_cada_variable_va_por_separado(g3):
    lectura(g3, a_las(10))
    horas_validas(g3, [10.0] * 20, variable="pm25")
    horas_validas(g3, [10.0] * 15, variable="pm10")
    reporte = armar_reporte_diario(DIA, [g3], DESPUES)
    assert celda(reporte, "PM2.5", g3).texto == "10 (20 h)"
    assert celda(reporte, "PM10", g3).texto == "datos insuficientes"


def test_una_columna_por_sensor_sin_mezclarlos(g3, g4):
    lectura(g3, a_las(10))
    lectura(g4, a_las(10))
    horas_validas(g3, [10.0] * 20)
    horas_validas(g4, [40.0] * 20)
    reporte = armar_reporte_diario(DIA, [g3, g4], DESPUES)
    assert [c.texto for c in reporte.tabla[1].celdas] == ["10 (20 h)", "40 (20 h)"]
    assert [fila.etiqueta for fila in reporte.tabla] == ["PM1", "PM2.5", "PM4", "PM10", "CO2"]


# Gráficas


def test_cada_grafica_tiene_exactamente_las_lecturas_del_dia(g3, g4):
    for paso in range(48):
        lectura(g3, a_las(0, 10) + timedelta(minutes=30 * paso))
    lectura(g3, a_las(23, 50, dia=DIA - timedelta(days=1)))
    lectura(g4, a_las(1))
    reporte = armar_reporte_diario(DIA, [g3, g4], DESPUES)
    pm25 = next(g for g in reporte.graficas if g.get("variable") == "pm25")
    series = {serie["sensor"]: serie["puntos"] for serie in pm25["series"]}
    assert len([p for p in series["G3"] if p[1] is not None]) == 48
    assert len(series["G4"]) == 1


def test_un_dia_sin_lecturas_de_ningun_sensor_lo_dice(g3):
    reporte = armar_reporte_diario(DIA, [g3], DESPUES)
    assert not reporte.hay_lecturas
    assert reporte.graficas == []
    assert reporte.tabla == []


# Periodos sin transmitir


def test_g4_deja_de_transmitir_a_las_03_10(g3, g4):
    lectura(g3, a_las(10))
    lectura(g4, a_las(2, 40, dia=DIA))
    lectura(g4, a_las(3, 10))
    reporte = armar_reporte_diario(DIA, [g3, g4], DESPUES)
    assert "G4 sin transmitir de 03:10 a 23:59" in [str(p) for p in reporte.periodos]


def test_un_sensor_sin_lecturas_en_todo_el_dia(g3, g4):
    lectura(g3, a_las(10))
    lectura(g4, a_las(22, dia=DIA - timedelta(days=1)))
    reporte = armar_reporte_diario(DIA, [g3, g4], DESPUES)
    assert "G4 sin transmitir de 00:00 a 23:59" in [str(p) for p in reporte.periodos]
    assert celda(reporte, "PM2.5", g4).texto == "datos insuficientes"


def test_un_envio_perdido_no_es_periodo(g3):
    for hora in [a_las(9, 50, dia=DIA - timedelta(days=1)), a_las(10), a_las(11)]:
        lectura(g3, hora)
    lectura(g3, a_las(0, 5, dia=DIA + timedelta(days=1)))
    reporte = armar_reporte_diario(DIA, [g3], DESPUES)
    # De las 11:00 a las 00:05 del día siguiente sí hay hueco; de las 10:00 a las 11:00, no.
    assert [str(p) for p in reporte.periodos] == [
        "G3 sin transmitir de 00:00 a 10:00",
        "G3 sin transmitir de 11:00 a 23:59",
    ]


def test_un_hueco_que_empieza_el_dia_anterior_se_recorta_a_las_00_00():
    anterior = Lectura(hora=a_las(20, dia=DIA - timedelta(days=1)), intervalo_s=1800)
    lecturas = [Lectura(hora=a_las(6, 30), intervalo_s=1800)]
    periodos = periodos_sin_transmitir("G3", lecturas, anterior, a_las(7), DIA, DESPUES)
    assert [str(p) for p in periodos] == ["G3 sin transmitir de 00:00 a 06:30"]


def test_hoy_el_ultimo_periodo_llega_hasta_ahora():
    anterior = Lectura(hora=a_las(23, 40, dia=DIA - timedelta(days=1)), intervalo_s=1800)
    lecturas = [Lectura(hora=a_las(8), intervalo_s=1800)]
    periodos = periodos_sin_transmitir("G3", lecturas, anterior, None, DIA, a_las(12))
    assert [str(p) for p in periodos][-1] == "G3 sin transmitir de 08:00 a 12:00"


# Pantalla


@pytest.fixture
def cliente(client, db):
    crear_administrador("doctora@ejemplo.mx", "Doctora", CONTRASENA)
    client.post(
        reverse("cuentas:entrar"), {"correo": "doctora@ejemplo.mx", "contrasena": CONTRASENA}
    )
    return client


def test_la_pagina_muestra_tabla_marca_y_periodos(cliente, g3, g4):
    dia = date.today() - timedelta(days=3)
    lectura(g3, a_las(10, dia=dia))
    lectura(g4, a_las(3, 10, dia=dia))
    horas_validas(g3, [40.0] * 20, dia=dia)
    respuesta = cliente.get(
        reverse("reportes:diario"), {"fecha": dia.isoformat(), "sensores": [g3.pk, g4.pk]}
    )
    html = respuesta.content.decode()
    assert "40 (20 h)" in html
    assert "excedencia" in html
    assert "G4 sin transmitir de 03:10 a 23:59" in html
    assert "Día anterior" in html and "Día siguiente" in html
    assert "incumple" not in html.lower()


def test_solo_los_sensores_elegidos(cliente, g3, g4):
    dia = date.today() - timedelta(days=3)
    lectura(g3, a_las(10, dia=dia))
    lectura(g4, a_las(10, dia=dia))
    respuesta = cliente.get(
        reverse("reportes:diario"), {"fecha": dia.isoformat(), "sensores": [g4.pk]}
    )
    assert [s.nombre_corto for s in respuesta.context["reporte"].sensores] == ["G4"]


def test_hoy_no_tiene_dia_siguiente(cliente, g3):
    respuesta = cliente.get(reverse("reportes:diario"), {"fecha": date.today().isoformat()})
    assert respuesta.context["dia_siguiente"] is None
