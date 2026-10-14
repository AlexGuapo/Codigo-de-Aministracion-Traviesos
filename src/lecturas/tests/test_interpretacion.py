import json
from pathlib import Path

import pytest

from lecturas.interpretacion import FormatoNoReconocido, crudo_de, interpretar_valor

FIXTURES = Path(__file__).parents[2] / "recepcion" / "tests" / "fixtures"


def cargar(nombre):
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


def filas_del_historial():
    return cargar("historial_pagina.json")["data"]["rows"]


def valor(sen55=None, scd40=None, rtc=None, profile=None):
    return {
        "sen55": sen55 if sen55 is not None else {"pm2.5": 3.7},
        "scd40": scd40 if scd40 is not None else {"co2": 751},
        "rtc": rtc if rtc is not None else {"sleep_interval": 1800},
        "profile": profile if profile is not None else {"nickname": "Aparato"},
    }


def test_formato_objeto_v020_da_lo_esperado():
    fixture = cargar("valor_objeto_v020.json")
    v = interpretar_valor(fixture["registro"]["value"])
    for campo, esperado in fixture["esperado"]["variables"].items():
        assert getattr(v, campo) == esperado, campo
    assert v.intervalo_s == 1800


def test_texto_con_tres_niveles_de_escapado():
    fila = filas_del_historial()[1]  # 3 niveles
    v = interpretar_valor(fila["value"])
    assert v.pm2_5 is not None
    assert v.co2 is not None
    assert v.intervalo_s == 1800
    assert v.apodo == "Aparato de prueba"


def test_texto_con_dos_niveles_de_escapado():
    fila = filas_del_historial()[0]  # 2 niveles
    v = interpretar_valor(fila["value"])
    assert v.pm10_0 is not None
    assert v.intervalo_s == 1800


def test_con_bateria_voc_y_nox_son_sin_dato():
    v = interpretar_valor(valor(sen55={"pm2.5": 3.0, "voc": 0, "nox": None}))
    assert v.voc is None
    assert v.nox is None


def test_voc_distinto_de_cero_si_se_conserva():
    v = interpretar_valor(valor(sen55={"voc": 79, "nox": 1}))
    assert v.voc == 79.0
    assert v.nox == 1.0


def test_variable_que_falta_es_sin_dato():
    v = interpretar_valor(valor(sen55={"pm2.5": 3.0}))
    assert v.pm10_0 is None
    assert v.humedad_sen55 is None


def test_valores_que_no_son_numero_son_sin_dato():
    v = interpretar_valor(
        valor(sen55={"pm2.5": True, "pm10.0": "4.3", "pm1.0": float("nan")})
    )
    assert v.pm2_5 is None
    assert v.pm10_0 is None
    assert v.pm1_0 is None


def test_cero_en_particulas_si_es_un_valor():
    assert interpretar_valor(valor(sen55={"pm2.5": 0})).pm2_5 == 0.0


def test_sin_sleep_interval():
    assert interpretar_valor(valor(rtc={})).intervalo_s is None
    assert interpretar_valor(valor(rtc={"sleep_interval": 0})).intervalo_s is None


def test_texto_que_no_es_json():
    with pytest.raises(FormatoNoReconocido):
        interpretar_valor("esto no es json")


def test_objeto_sin_sensores():
    with pytest.raises(FormatoNoReconocido):
        interpretar_valor({"otra": 1})


def test_lista_no_es_lectura():
    with pytest.raises(FormatoNoReconocido):
        interpretar_valor("[1, 2, 3]")


def test_crudo_de_texto_es_identico():
    original = filas_del_historial()[1]["value"]
    assert crudo_de(original) == original


def test_crudo_de_objeto_es_json_compacto():
    crudo = crudo_de({"sen55": {"pm2.5": 3.7}, "nombre": "ñ"})
    assert crudo == '{"sen55":{"pm2.5":3.7},"nombre":"ñ"}'
    assert json.loads(crudo)["sen55"]["pm2.5"] == 3.7
