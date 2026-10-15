from datetime import date, datetime
from types import SimpleNamespace

from reportes.formato import fecha_larga, mes_largo
from reportes.series import graficas_del_reporte, puntos_de_la_serie


def lectura(hhmm, pm25, intervalo_s=1800, segundos=0):
    h, m = map(int, hhmm.split(":"))
    return SimpleNamespace(
        hora=datetime(2025, 12, 1, h, m, segundos),
        intervalo_s=intervalo_s,
        pm1_0=None,
        pm2_5=pm25,
        pm4_0=None,
        pm10_0=None,
        co2=None,
    )


def test_cada_lectura_es_un_punto_en_orden():
    puntos = puntos_de_la_serie([lectura("00:41", 13.1), lectura("00:12", 12.6)], "pm2_5")
    assert puntos == [["2025-12-01T00:12:00", 12.6], ["2025-12-01T00:41:00", 13.1]]


def test_un_envio_perdido_no_corta_la_linea():
    puntos = puntos_de_la_serie([lectura("08:00", 10.0), lectura("08:58", 11.0)], "pm2_5")
    assert [p[1] for p in puntos] == [10.0, 11.0]


def test_un_hueco_corta_la_linea():
    puntos = puntos_de_la_serie([lectura("03:10", 10.0), lectura("05:00", 11.0)], "pm2_5")
    assert puntos[1] == ["2025-12-01T04:05:00", None]
    assert len(puntos) == 3


def test_sin_dato_no_se_dibuja_como_cero():
    puntos = puntos_de_la_serie([lectura("00:12", None)], "pm2_5")
    assert puntos == [["2025-12-01T00:12:00", None]]


def test_valor_con_un_decimal():
    puntos = puntos_de_la_serie([lectura("00:12", 20.399999618530273)], "pm2_5")
    assert puntos[0][1] == 20.4


def test_una_serie_por_sensor_sin_mezclarlos():
    graficas = graficas_del_reporte(
        [("G3", [lectura("00:12", 1.0)]), ("G4", [lectura("00:20", 2.0)])]
    )
    assert [g["variable"] for g in graficas] == ["pm1", "pm25", "pm4", "pm10", "co2"]
    pm25 = graficas[1]
    assert [s["sensor"] for s in pm25["series"]] == ["G3", "G4"]
    assert pm25["series"][0]["puntos"] == [["2025-12-01T00:12:00", 1.0]]
    assert pm25["unidad"] == "µg/m³"
    assert graficas[4]["unidad"] == "ppm"


def test_sensor_sin_lecturas_no_lleva_serie():
    graficas = graficas_del_reporte([("G3", [lectura("00:12", 1.0)]), ("G4", [])])
    assert [s["sensor"] for s in graficas[1]["series"]] == ["G3"]


def test_titulo_del_reporte():
    assert fecha_larga(date(2025, 12, 1)) == "lunes 1 de diciembre de 2025"
    assert fecha_larga(date(2026, 9, 23)) == "miércoles 23 de septiembre de 2026"


def test_titulo_del_mes():
    assert mes_largo(2026, 9) == "septiembre de 2026"
