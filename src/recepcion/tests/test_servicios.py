from datetime import date, datetime, timedelta

import pytest

from calculo.models import MarcaRecalculo
from lecturas.models import Lectura
from recepcion.adapters.archivo import FuenteDeArchivo
from recepcion.models import ConsultaNube
from recepcion.ports import FuenteNoDisponible
from recepcion.services import (
    Lector,
    Presupuesto,
    conciliar,
    leer_historial_diario,
    sondear,
)
from recepcion.tests.nube_falsa import INICIO, MAC, NubeFalsa, crear_sensor
from sensores.cifrado import Cifrador, generar_clave
from sensores.models import EstadoSensor


@pytest.fixture
def cifrador():
    return Cifrador(generar_clave())


@pytest.fixture
def sensor(db, cifrador):
    return crear_sensor(cifrador)


def lector(nube, cifrador):
    return Lector(nube, cifrador, dormir=lambda _s: None)


def test_el_sondeo_pide_la_primera_pagina_de_5_y_guarda(sensor, cifrador):
    nube = NubeFalsa()
    resumenes = sondear(lector(nube, cifrador))
    assert nube.llamadas == [("token-1", 1, 5)]
    assert resumenes[sensor.pk].nuevas == 5
    assert Lectura.objects.filter(sensor=sensor).count() == 5
    assert MarcaRecalculo.objects.filter(sensor=sensor).exists()


def test_el_sondeo_anota_el_exito_en_la_consulta_a_la_nube(sensor, cifrador):
    sondear(lector(NubeFalsa(), cifrador))
    consulta = ConsultaNube.objects.get(sensor=sensor)
    assert consulta.ultimo_exito_en is not None
    assert consulta.fallas_seguidas == 0
    assert consulta.ultimo_error is None
    assert consulta.ultima_lectura_descargada_en == INICIO + timedelta(minutes=30 * 9)


def test_leer_dos_veces_no_cambia_el_conteo(sensor, cifrador):
    sondear(lector(NubeFalsa(), cifrador))
    segundo = sondear(lector(NubeFalsa(), cifrador))
    assert segundo[sensor.pk].nuevas == 0
    assert segundo[sensor.pk].ya_estaban == 5
    assert Lectura.objects.count() == 5


def test_no_consulta_sensores_dados_de_baja(db, cifrador):
    crear_sensor(cifrador, estado=EstadoSensor.DADO_DE_BAJA, dado_de_baja_en=datetime(2026, 10, 1))
    nube = NubeFalsa()
    assert sondear(lector(nube, cifrador)) == {}
    assert nube.llamadas == []


def test_una_falla_se_reintenta_una_vez_despues_de_esperar(sensor, cifrador):
    nube = NubeFalsa(fallas=[FuenteNoDisponible("tiempo de espera agotado", sensor.pk)])
    esperas = []
    resumen = Lector(nube, cifrador, dormir=esperas.append).leer(sensor, paginas=1, tamano=5)
    assert esperas == [5]
    assert resumen.error is None
    assert resumen.nuevas == 5
    assert nube.tokens_pedidos == 0


def test_dos_fallas_seguidas_quedan_anotadas(sensor, cifrador):
    falla = FuenteNoDisponible("sin conexión con la nube", sensor.pk)
    nube = NubeFalsa(fallas=[falla, falla])
    resumen = lector(nube, cifrador).leer(sensor, paginas=1, tamano=5)
    assert resumen.error == "sin conexión con la nube"
    consulta = ConsultaNube.objects.get(sensor=sensor)
    assert consulta.fallas_seguidas == 1
    assert consulta.ultimo_error == "sin conexión con la nube"
    assert consulta.ultimo_exito_en is None
    assert Lectura.objects.count() == 0


def test_las_fallas_seguidas_se_acumulan_y_un_exito_las_borra(sensor, cifrador):
    falla = FuenteNoDisponible("sin conexión con la nube", sensor.pk)
    lector(NubeFalsa(fallas=[falla, falla]), cifrador).leer(sensor, paginas=1, tamano=5)
    lector(NubeFalsa(fallas=[falla, falla]), cifrador).leer(sensor, paginas=1, tamano=5)
    assert ConsultaNube.objects.get(sensor=sensor).fallas_seguidas == 2
    lector(NubeFalsa(), cifrador).leer(sensor, paginas=1, tamano=5)
    consulta = ConsultaNube.objects.get(sensor=sensor)
    assert consulta.fallas_seguidas == 0
    assert consulta.ultimo_error is None


def test_sin_presupuesto_no_se_reintenta(sensor, cifrador):
    nube = NubeFalsa(fallas=[FuenteNoDisponible("tiempo de espera agotado", sensor.pk)])
    poco_tiempo = Presupuesto(60)
    resumen = lector(nube, cifrador).leer(sensor, paginas=1, tamano=5, presupuesto=poco_tiempo)
    assert resumen.error == "tiempo de espera agotado"
    assert len(nube.llamadas) == 1


def test_si_se_acaba_la_ronda_los_demas_sensores_esperan(db, cifrador):
    crear_sensor(cifrador, "S-1")
    crear_sensor(cifrador, "S-2")
    reloj = iter([0, 0, 601, 601])
    presupuesto = Presupuesto(600, reloj=lambda: next(reloj))
    nube = NubeFalsa()
    resumenes = sondear(lector(nube, cifrador), presupuesto)
    assert len(resumenes) == 1
    assert len(nube.llamadas) == 1


def test_un_token_que_cambio_se_renueva_y_se_guarda_cifrado(sensor, cifrador):
    nube = NubeFalsa(token="token-2", token_nuevo="token-2")
    resumen = lector(nube, cifrador).leer(sensor, paginas=1, tamano=5)
    assert resumen.error is None
    assert resumen.nuevas == 5
    assert nube.tokens_pedidos == 1
    sensor.refresh_from_db()
    assert "token-2" not in sensor.token_cifrado
    assert cifrador.descifrar(sensor.token_cifrado.encode("ascii")) == "token-2"


def test_si_con_el_token_de_la_mac_sigue_fallando_cuenta_como_falla(sensor, cifrador):
    falla = FuenteNoDisponible("la nube respondió code=500", sensor.pk, respondio=True)
    nube = NubeFalsa(fallas=[falla, falla])
    resumen = lector(nube, cifrador).leer(sensor, paginas=1, tamano=5)
    assert nube.tokens_pedidos == 1
    assert resumen.error == "la nube respondió code=500"
    assert ConsultaNube.objects.get(sensor=sensor).fallas_seguidas == 1


def test_el_historial_diario_lee_dos_paginas_de_50(sensor, cifrador):
    nube = NubeFalsa(cantidad=120)
    resumenes = leer_historial_diario(lector(nube, cifrador))
    assert [(p, t) for _, p, t in nube.llamadas] == [(1, 50), (2, 50)]
    assert resumenes[sensor.pk].nuevas == 100


def test_una_pagina_incompleta_termina_la_lectura(sensor, cifrador):
    nube = NubeFalsa(cantidad=30)
    leer_historial_diario(lector(nube, cifrador))
    assert len(nube.llamadas) == 1
    assert Lectura.objects.count() == 30


def test_la_conciliacion_recupera_lo_que_falta_y_anota_el_recorrido(sensor, cifrador):
    sondear(lector(NubeFalsa(cantidad=200), cifrador))
    resumen = conciliar(lector(NubeFalsa(cantidad=200), cifrador))[sensor.pk]
    assert resumen.leidas == 200
    assert resumen.ya_estaban == 5
    assert resumen.nuevas == 195
    assert Lectura.objects.count() == 200
    assert ConsultaNube.objects.get(sensor=sensor).ultimo_recorrido_completo_en is not None


def test_la_conciliacion_no_pasa_de_la_fecha_del_sensor(db, cifrador):
    sensor = crear_sensor(cifrador, desde=date(2026, 10, 3))
    nube = NubeFalsa(cantidad=500)
    resumen = conciliar(lector(nube, cifrador))[sensor.pk]
    # 500 lecturas cada 30 min desde el 01/10: el 03/10 empieza en la página 9
    assert len(nube.llamadas) == 9
    assert resumen.fuera_de_fecha > 0
    assert not Lectura.objects.filter(hora__lt=datetime(2026, 10, 3)).exists()


def test_la_recepcion_funciona_con_la_fuente_de_archivo(sensor, cifrador):
    fuente = FuenteDeArchivo(terminar_en=datetime(2026, 10, 15, 12, 0))
    resumen = lector(fuente, cifrador).leer(sensor, paginas=10, tamano=50)
    assert resumen.error is None
    assert resumen.nuevas > 0
    assert Lectura.objects.filter(sensor=sensor).count() == resumen.nuevas


def test_ningun_log_lleva_la_mac_ni_el_token(sensor, cifrador, caplog):
    falla = FuenteNoDisponible("la nube respondió code=401", sensor.pk, respondio=True)
    nube = NubeFalsa(fallas=[falla], token_nuevo="token-nuevo-secreto")
    with caplog.at_level("DEBUG"):
        lector(nube, cifrador).leer(sensor, paginas=1, tamano=5)
        sondear(lector(nube, cifrador))
    assert MAC not in caplog.text
    assert "token-1" not in caplog.text
    assert "token-nuevo-secreto" not in caplog.text


def test_el_worker_registra_las_tareas_de_la_recepcion():
    from apscheduler.schedulers.background import BackgroundScheduler

    from recepcion import jobs

    programador = BackgroundScheduler()
    jobs.registrar(programador, "recepcion")
    tareas = {t.id: t for t in programador.get_jobs()}
    assert set(tareas) == {
        "sondeo",
        "historial_diario",
        "conciliacion",
        "verificaciones",
        "rellenos",
    }
    assert all(t.executor == "recepcion" for t in tareas.values())
    assert str(tareas["historial_diario"].trigger) == "cron[hour='2', minute='10']"
