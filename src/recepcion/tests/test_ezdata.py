import json
import logging
import urllib.error
from datetime import datetime
from pathlib import Path

import pytest

from recepcion.adapters.ezdata import SIN_DATOS, FuenteEzData, a_hora_local
from recepcion.ports import FuenteNoDisponible, Ruta, SensorConsultado

FIXTURES = Path(__file__).parent / "fixtures"
MAC = "AABBCCDDEEFF"
TOKEN = "tokendeprueba1234"
SENSOR = SensorConsultado(id=1, mac=MAC, token=TOKEN)


def texto(nombre):
    return (FIXTURES / nombre).read_text(encoding="utf-8")


class NubeFalsa:
    """Hace las veces de la red: regresa un cuerpo o lanza una excepción."""

    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.urls = []

    def __call__(self, url, espera):
        self.urls.append(url)
        if isinstance(self.respuesta, BaseException):
            raise self.respuesta
        if isinstance(self.respuesta, str):
            return self.respuesta.encode("utf-8")
        return self.respuesta


def fuente(respuesta):
    nube = NubeFalsa(respuesta)
    return FuenteEzData(obtener=nube), nube


# -- hora -------------------------------------------------------------------


def test_texto_en_hora_de_china_pasa_a_hora_local():
    assert a_hora_local("2026-09-27 02:18:11") == datetime(2026, 9, 26, 12, 18, 11)


def test_segundos_unix_pasan_a_hora_local():
    assert a_hora_local("1791053592") == datetime(2026, 10, 3, 12, 53, 12)
    assert a_hora_local(1791053592) == datetime(2026, 10, 3, 12, 53, 12)


def test_milisegundos_unix():
    assert a_hora_local(1791053592000) == datetime(2026, 10, 3, 12, 53, 12)


def test_hora_no_reconocida():
    assert a_hora_local("ayer en la tarde") is None
    assert a_hora_local(None) is None
    assert a_hora_local(True) is None


def test_ultima_y_historial_dan_la_misma_hora():
    # medido en el spike: 0 s de diferencia entre las dos rutas
    fh, _ = fuente(texto("historial_pagina.json"))
    fu, _ = fuente(texto("ultima.json"))
    assert (
        fh.historial(SENSOR, 1, 5)[0].hora_local == fu.ultima_lectura(SENSOR).hora_local
    )


# -- historial --------------------------------------------------------------


def test_historial_convierte_todas_las_filas():
    f, nube = fuente(texto("historial_pagina.json"))
    lecturas = f.historial(SENSOR, 1, 5)
    assert len(lecturas) == 7  # las copias también llegan; las quita registrar_lectura
    primera = lecturas[0]
    assert primera.sensor_id == 1
    assert primera.ruta is Ruta.HISTORIAL
    assert primera.hora_nube == "2026-10-04 02:53:12"
    assert primera.hora_local == datetime(2026, 10, 3, 12, 53, 12)
    assert primera.intervalo_s == 1800
    assert primera.voc is None
    assert primera.nox is None
    assert nube.urls[0].endswith(f"/{TOKEN}/history?pageSize=5&pageNum=1")


def test_historial_guarda_el_crudo_sin_el_token():
    f, _ = fuente(texto("historial_pagina.json"))
    filas = json.loads(texto("historial_pagina.json"))["data"]["rows"]
    lecturas = f.historial(SENSOR, 1, 5)
    for lectura, fila in zip(lecturas, filas, strict=True):
        assert lectura.crudo == fila["value"]
        assert TOKEN not in lectura.crudo


def test_historial_vacio_no_es_falla():
    f, _ = fuente(
        json.dumps({"code": 200, "msg": "OK", "data": {"total": 0, "rows": []}})
    )
    assert f.historial(SENSOR, 1, 5) == []


def test_fila_que_no_se_entiende_se_salta(caplog):
    datos = json.loads(texto("historial_pagina.json"))
    datos["data"]["rows"][2]["value"] = "basura"
    datos["data"]["rows"][3]["updateTime"] = "sin hora"
    f, _ = fuente(json.dumps(datos))
    with caplog.at_level(logging.WARNING, logger="recepcion.ezdata"):
        lecturas = f.historial(SENSOR, 1, 5)
    assert len(lecturas) == 5
    assert "se salta" in caplog.text


def test_pagina_invalida():
    f, nube = fuente(texto("historial_pagina.json"))
    with pytest.raises(ValueError):
        f.historial(SENSOR, 0, 5)
    assert nube.urls == []


# -- última lectura y token -------------------------------------------------


def test_ultima_lectura():
    f, nube = fuente(texto("ultima.json"))
    lectura = f.ultima_lectura(SENSOR)
    assert lectura.ruta is Ruta.ULTIMA
    assert lectura.hora_nube == "1791053592"
    assert nube.urls[0].endswith(f"/{MAC}/dataMacByKey/raw")


def test_obtener_token():
    f, _ = fuente(texto("ultima.json"))
    resultado = f.obtener_token(MAC)
    assert resultado.token == TOKEN
    assert resultado.apodo == "Aparato de prueba"
    assert resultado.ultima is not None
    assert resultado.ultima.hora_local == datetime(2026, 10, 3, 12, 53, 12)


def test_obtener_token_sin_token_es_falla():
    f, _ = fuente(json.dumps({"code": 200, "msg": "OK", "data": {"value": "{}"}}))
    with pytest.raises(FuenteNoDisponible):
        f.obtener_token(MAC)


def test_obtener_token_pide_mac_normalizada():
    f, nube = fuente(texto("ultima.json"))
    with pytest.raises(ValueError):
        f.obtener_token("aa:bb:cc:dd:ee:ff")
    assert nube.urls == []


# -- rutas permitidas -------------------------------------------------------


def test_ruta_no_permitida_no_se_consulta():
    f, nube = fuente(texto("historial_pagina.json"))
    raro = SensorConsultado(id=1, mac=MAC, token="abc/../../delete")
    with pytest.raises(ValueError):
        f.historial(raro, 1, 5)
    assert nube.urls == []


def test_mac_rara_no_se_consulta():
    f, nube = fuente(texto("ultima.json"))
    with pytest.raises(ValueError):
        f.ultima_lectura(SensorConsultado(id=1, mac="AABB/add", token=TOKEN))
    assert nube.urls == []


# -- fallas de la nube ------------------------------------------------------

FALLAS = [
    (texto("respuesta_code_500.json"), "code=500"),
    (json.dumps({"code": 200, "msg": "OK", "data": None}), SIN_DATOS),
    ("<html>error</html>", "no es JSON"),
    (json.dumps({"code": 200, "data": {"total": 1}}), "inesperada"),
    (urllib.error.URLError(TimeoutError("timed out")), "tiempo de espera"),
    (TimeoutError("timed out"), "tiempo de espera"),
    (urllib.error.URLError(f"no se pudo abrir {TOKEN}"), "sin conexión"),
    (ConnectionResetError(f"reset {MAC}"), "sin conexión"),
]


@pytest.mark.parametrize(("respuesta", "motivo"), FALLAS)
def test_fallas_se_vuelven_fuente_no_disponible(respuesta, motivo):
    f, _ = fuente(respuesta)
    with pytest.raises(FuenteNoDisponible, match=motivo) as error:
        f.historial(SENSOR, 1, 5)
    assert error.value.sensor_id == 1


LA_NUBE_RESPONDIO = ["code=500", SIN_DATOS, "inesperada"]


@pytest.mark.parametrize(
    ("respuesta", "respondio"), [(r, motivo in LA_NUBE_RESPONDIO) for r, motivo in FALLAS]
)
def test_distingue_si_la_nube_respondio(respuesta, respondio):
    f, _ = fuente(respuesta)
    with pytest.raises(FuenteNoDisponible) as error:
        f.historial(SENSOR, 1, 5)
    assert error.value.respondio is respondio


def test_error_http():
    url = f"https://ezdata2.m5stack.com/api/v2/{TOKEN}/history"
    f, _ = fuente(urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None))
    with pytest.raises(FuenteNoDisponible, match="HTTP 503"):
        f.historial(SENSOR, 1, 5)


# -- que no se filtren secretos ---------------------------------------------

SECRETOS = (MAC, TOKEN, "ezdata2.m5stack.com")
FALLAS_CON_SECRETOS = [
    urllib.error.HTTPError(
        f"https://ezdata2.m5stack.com/api/v2/{TOKEN}/history", 500, "x", {}, None
    ),
    urllib.error.URLError(f"no se pudo abrir https://ezdata2.m5stack.com/api/v2/{MAC}"),
    TimeoutError(f"timed out {TOKEN}"),
    OSError(f"socket {MAC}"),
]


@pytest.mark.parametrize("excepcion", FALLAS_CON_SECRETOS)
@pytest.mark.parametrize("operacion", ["historial", "ultima", "token"])
def test_ninguna_falla_deja_ver_url_mac_ni_token(excepcion, operacion, caplog):
    f, _ = fuente(excepcion)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(FuenteNoDisponible) as error:
            if operacion == "historial":
                f.historial(SENSOR, 1, 5)
            elif operacion == "ultima":
                f.ultima_lectura(SENSOR)
            else:
                f.obtener_token(MAC)
    e = error.value
    assert e.__context__ is None
    assert e.__cause__ is None
    for secreto in SECRETOS:
        assert secreto not in str(e)
        assert secreto not in repr(e)
        assert secreto not in caplog.text


def test_operacion_correcta_no_registra_secretos(caplog):
    f, _ = fuente(texto("historial_pagina.json"))
    with caplog.at_level(logging.DEBUG):
        f.historial(SENSOR, 1, 5)
    for secreto in SECRETOS:
        assert secreto not in caplog.text
