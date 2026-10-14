import dataclasses
from datetime import datetime

import pytest

from recepcion.ports import (
    FuenteNoDisponible,
    LecturaNormalizada,
    Origen,
    ResultadoToken,
    Ruta,
    SensorConsultado,
)

MAC = "AABBCCDDEEFF"
TOKEN = "token-secreto-123"


def lectura(**cambios):
    datos = dict(
        sensor_id=1,
        hora_local=datetime(2026, 9, 26, 12, 18, 11),
        hora_nube="2026-09-27 02:18:11",
        ruta=Ruta.HISTORIAL,
        crudo='{"sen55": {}}',
        intervalo_s=1800,
        pm1_0=3.5,
        pm2_5=3.7,
        pm4_0=4.1,
        pm10_0=4.3,
        co2=751.0,
        temperatura_sen55=36.03,
        humedad_sen55=36.55,
        temperatura_scd40=37.18,
        humedad_scd40=34.54,
        voc=None,
        nox=None,
    )
    datos.update(cambios)
    return LecturaNormalizada(**datos)


def test_lectura_por_omision_viene_de_la_nube():
    assert lectura().origen is Origen.NUBE


def test_lectura_es_inmutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        lectura().pm2_5 = 99.0


def test_ruta_usa_el_nombre_de_la_nube():
    assert Ruta.HISTORIAL == "history"
    assert Ruta.ULTIMA == "dataMacByKey"


def test_sensor_no_muestra_mac_ni_token():
    texto = repr(SensorConsultado(id=7, mac=MAC, token=TOKEN))
    assert "7" in texto
    assert MAC not in texto
    assert TOKEN not in texto


def test_resultado_token_no_muestra_el_token():
    texto = repr(ResultadoToken(token=TOKEN, apodo="Aparato", ultima=None))
    assert TOKEN not in texto


def test_falla_solo_dice_sensor_y_motivo():
    error = FuenteNoDisponible("tiempo de espera agotado", sensor_id=3)
    assert str(error) == "sensor 3: tiempo de espera agotado"
    assert error.sensor_id == 3


def test_falla_sin_sensor():
    assert str(FuenteNoDisponible("la nube no responde")) == "la nube no responde"
