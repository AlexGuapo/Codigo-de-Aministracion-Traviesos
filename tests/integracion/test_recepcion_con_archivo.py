"""La recepción de punta a punta con la muestra de S-1 en lugar de la nube.

Es la misma lista de la prueba real con EzData, salvo la consulta a la nube: el sondeo, el
historial diario y la conciliación pasan por el registro real y por la base.
"""

import json
from datetime import date, datetime, timedelta

import pytest

from lecturas.interpretacion import crudo_de
from lecturas.models import Lectura
from recepcion.adapters.archivo import FuenteDeArchivo
from recepcion.adapters.ezdata import a_hora_local
from recepcion.models import ConsultaNube
from recepcion.ports import SensorConsultado
from recepcion.services import Lector, conciliar, leer_historial_diario, sondear
from sensores.cifrado import Cifrador, generar_clave
from sensores.models import Sensor

FIN_DE_LA_MUESTRA = datetime(2026, 10, 15, 12, 0)


@pytest.fixture
def cifrador():
    return Cifrador(generar_clave())


@pytest.fixture
def fuente():
    return FuenteDeArchivo(terminar_en=FIN_DE_LA_MUESTRA)


@pytest.fixture
def sensor(db, cifrador):
    return Sensor.objects.create(
        nombre_corto="S-1",
        mac_cifrada=cifrador.cifrar("AABBCCDDEE01").decode("ascii"),
        mac_huella=cifrador.huella_mac("AABBCCDDEE01"),
        token_cifrado=cifrador.cifrar("archivo").decode("ascii"),
        lecturas_desde=date(2026, 9, 1),
    )


def lector(fuente, cifrador):
    return Lector(fuente, cifrador, dormir=lambda _s: None)


def toda_la_muestra(fuente, sensor):
    consultado = SensorConsultado(id=sensor.pk, mac="AABBCCDDEE01", token="archivo")
    return [
        lectura for pagina in range(1, 11) for lectura in fuente.historial(consultado, pagina, 50)
    ]


def test_el_sondeo_guarda_las_5_mas_recientes(sensor, fuente, cifrador):
    resumen = sondear(lector(fuente, cifrador))[sensor.pk]
    assert resumen.leidas == 5
    assert Lectura.objects.filter(sensor=sensor).count() == resumen.nuevas


def test_el_historial_diario_recupera_lo_que_el_sondeo_no_vio(sensor, fuente, cifrador):
    sondear(lector(fuente, cifrador))
    antes = Lectura.objects.count()
    resumen = leer_historial_diario(lector(fuente, cifrador))[sensor.pk]
    assert resumen.leidas == 100
    assert Lectura.objects.count() == antes + resumen.nuevas


def test_la_conciliacion_deja_el_100_por_ciento(sensor, fuente, cifrador):
    conciliar(lector(fuente, cifrador))
    segunda = conciliar(lector(fuente, cifrador))[sensor.pk]
    assert segunda.nuevas == 0
    assert segunda.ya_estaban == segunda.leidas - segunda.fuera_de_fecha
    assert ConsultaNube.objects.get(sensor=sensor).ultimo_recorrido_completo_en is not None


def test_leer_dos_veces_el_historial_no_cambia_el_conteo(sensor, fuente, cifrador):
    leer_historial_diario(lector(fuente, cifrador))
    conteo = Lectura.objects.count()
    leer_historial_diario(lector(fuente, cifrador))
    assert Lectura.objects.count() == conteo


def test_la_hora_guardada_es_la_local(sensor, fuente, cifrador):
    sondear(lector(fuente, cifrador))
    for lectura in Lectura.objects.filter(sensor=sensor):
        assert lectura.hora == a_hora_local(lectura.hora_nube_original)
        assert lectura.hora < FIN_DE_LA_MUESTRA + timedelta(seconds=1)


def test_el_crudo_es_el_valor_sin_el_token(sensor, fuente, cifrador):
    sondear(lector(fuente, cifrador))
    muestra = {lectura.hora_local: lectura for lectura in toda_la_muestra(fuente, sensor)}
    for lectura in Lectura.objects.filter(sensor=sensor):
        assert lectura.crudo == muestra[lectura.hora].crudo
        assert "archivo" not in lectura.crudo
        assert lectura.crudo == crudo_de(json.loads(lectura.crudo))


def test_sin_dato_nunca_se_guarda_como_cero(sensor, fuente, cifrador):
    conciliar(lector(fuente, cifrador))
    assert not Lectura.objects.filter(voc=0).exists()
    assert Lectura.objects.filter(voc__isnull=True).exists()


def test_el_estado_de_la_consulta_queda_al_dia(sensor, fuente, cifrador):
    sondear(lector(fuente, cifrador))
    consulta = ConsultaNube.objects.get(sensor=sensor)
    assert consulta.fallas_seguidas == 0
    assert consulta.ultima_lectura_descargada_en == max(
        lectura.hora_local for lectura in toda_la_muestra(fuente, sensor)
    )
