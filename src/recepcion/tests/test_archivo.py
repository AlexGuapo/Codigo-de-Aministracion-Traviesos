import json
from datetime import datetime

import pytest

from recepcion.adapters.archivo import TOKEN_DE_ARCHIVO, FuenteDeArchivo
from recepcion.ports import FuenteNoDisponible, Ruta, SensorConsultado

SENSOR = SensorConsultado(id=7, mac="AABBCCDDEEFF", token=TOKEN_DE_ARCHIVO)


@pytest.fixture(scope="module")
def fuente():
    return FuenteDeArchivo()


def test_lee_las_500_lecturas_de_la_muestra(fuente):
    pagina = fuente.historial(SENSOR, 1, 1000)
    assert len(pagina) == 500


def test_entrega_primero_la_mas_reciente(fuente):
    pagina = fuente.historial(SENSOR, 1, 5)
    horas = [lectura.hora_local for lectura in pagina]
    assert horas == sorted(horas, reverse=True)
    assert pagina[0].hora_local == datetime(2026, 10, 13, 18, 30, 13)


def test_las_paginas_no_se_enciman(fuente):
    primera = fuente.historial(SENSOR, 1, 50)
    segunda = fuente.historial(SENSOR, 2, 50)
    assert primera[-1].hora_local >= segunda[0].hora_local
    assert len(segunda) == 50


def test_pagina_despues_del_final_viene_vacia(fuente):
    assert fuente.historial(SENSOR, 11, 50) == []


def test_convierte_la_hora_de_china_a_local(fuente):
    mas_antigua = fuente.historial(SENSOR, 10, 50)[-1]
    assert mas_antigua.hora_nube == "2026-09-19 17:53:11"
    assert mas_antigua.hora_local == datetime(2026, 9, 19, 3, 53, 11)


def test_valores_e_intervalo(fuente):
    mas_antigua = fuente.historial(SENSOR, 10, 50)[-1]
    assert mas_antigua.sensor_id == 7
    assert mas_antigua.ruta == Ruta.HISTORIAL
    assert mas_antigua.pm2_5 == pytest.approx(20.4, abs=1e-6)
    assert mas_antigua.co2 == 530
    assert mas_antigua.intervalo_s == 1800
    assert mas_antigua.voc is None
    assert mas_antigua.nox is None


def test_el_crudo_no_lleva_token(fuente):
    lectura = fuente.ultima_lectura(SENSOR)
    crudo = json.loads(lectura.crudo)
    assert set(crudo) == {"sen55", "scd40", "rtc"}
    assert TOKEN_DE_ARCHIVO not in lectura.crudo


def test_terminar_en_recorre_todas_las_horas():
    ahora = datetime(2026, 10, 17, 9, 0, 0)
    fuente = FuenteDeArchivo(terminar_en=ahora)
    pagina = fuente.historial(SENSOR, 1, 2)
    assert pagina[0].hora_local == ahora
    original = FuenteDeArchivo().historial(SENSOR, 1, 2)
    assert pagina[0].hora_local - pagina[1].hora_local == (
        original[0].hora_local - original[1].hora_local
    )


def test_token_para_el_alta(fuente):
    resultado = fuente.obtener_token("AABBCCDDEEFF")
    assert resultado.token == TOKEN_DE_ARCHIVO
    assert resultado.ultima is not None


def test_archivo_que_no_existe(tmp_path):
    with pytest.raises(FuenteNoDisponible):
        FuenteDeArchivo(tmp_path / "no_existe.json")
