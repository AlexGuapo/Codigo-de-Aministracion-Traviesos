import dataclasses
import json
from datetime import date, datetime, timedelta

import pytest

from calculo.models import CausaRecalculo, MarcaRecalculo
from lecturas.huella import huella_valores
from lecturas.interpretacion import crudo_de, interpretar_valor
from lecturas.models import Lectura
from lecturas.services import Resultado, registrar_lectura
from recepcion.adapters.archivo import FuenteDeArchivo
from recepcion.ports import LecturaNormalizada, Ruta, SensorConsultado
from sensores.models import Sensor

HORA = datetime(2026, 9, 26, 12, 18, 11)


@pytest.fixture
def sensor(db):
    return Sensor.objects.create(
        nombre_corto="S-1",
        mac_cifrada="c",
        mac_huella="h" * 64,
        token_cifrado="t",
        lecturas_desde=date(2026, 9, 19),
    )


def normalizada(sensor_id, hora=HORA, pm25=12.6, intervalo_s=1800):
    return LecturaNormalizada(
        sensor_id=sensor_id,
        hora_local=hora,
        hora_nube=(hora + timedelta(hours=14)).strftime("%Y-%m-%d %H:%M:%S"),
        ruta=Ruta.HISTORIAL,
        crudo='{"sen55":{}}',
        intervalo_s=intervalo_s,
        pm1_0=10.0,
        pm2_5=pm25,
        pm4_0=13.0,
        pm10_0=13.5,
        co2=515.0,
        temperatura_sen55=20.1,
        humedad_sen55=50.2,
        temperatura_scd40=20.0,
        humedad_scd40=51.0,
        voc=None,
        nox=None,
    )


def test_guarda_una_lectura_nueva(sensor):
    registro = registrar_lectura(normalizada(sensor.pk))
    assert registro.resultado == Resultado.GUARDADA
    lectura = Lectura.objects.get(pk=registro.lectura_id)
    assert lectura.hora == HORA
    assert lectura.pm2_5 == 12.6
    assert lectura.voc is None
    assert lectura.ruta == "history"
    assert lectura.origen == "nube"
    assert lectura.copia_discrepante_de_id is None


def test_leer_dos_veces_la_misma_no_la_repite(sensor):
    registrar_lectura(normalizada(sensor.pk))
    assert registrar_lectura(normalizada(sensor.pk)).resultado == Resultado.REPETIDA
    assert Lectura.objects.count() == 1


def test_copia_identica_a_los_2_segundos_no_se_guarda(sensor):
    registrar_lectura(normalizada(sensor.pk))
    copia = normalizada(sensor.pk, hora=HORA + timedelta(seconds=2))
    assert registrar_lectura(copia).resultado == Resultado.COPIA_IDENTICA
    assert Lectura.objects.count() == 1


def test_copia_discrepante_se_guarda_ligada(sensor):
    primera = registrar_lectura(normalizada(sensor.pk, pm25=18.4))
    segunda = registrar_lectura(normalizada(sensor.pk, hora=HORA + timedelta(seconds=2), pm25=18.9))
    assert segunda.resultado == Resultado.COPIA_DISCREPANTE
    assert Lectura.objects.get(pk=segunda.lectura_id).copia_discrepante_de_id == primera.lectura_id


def test_la_copia_que_llega_primero_con_hora_posterior_tambien_se_liga(sensor):
    tardia = registrar_lectura(normalizada(sensor.pk, hora=HORA + timedelta(seconds=2), pm25=18.9))
    temprana = registrar_lectura(normalizada(sensor.pk, pm25=18.4))
    assert temprana.resultado == Resultado.COPIA_DISCREPANTE
    assert Lectura.objects.get(pk=temprana.lectura_id).copia_discrepante_de_id == tardia.lectura_id


def test_dos_valores_distintos_en_el_mismo_segundo(sensor):
    registrar_lectura(normalizada(sensor.pk, pm25=18.4))
    assert registrar_lectura(normalizada(sensor.pk, pm25=18.9)).resultado == (
        Resultado.COPIA_DISCREPANTE
    )


def test_a_los_45_segundos_ya_no_es_copia(sensor):
    registrar_lectura(normalizada(sensor.pk))
    otra = normalizada(sensor.pk, hora=HORA + timedelta(seconds=45))
    assert registrar_lectura(otra).resultado == Resultado.GUARDADA


def test_con_intervalo_de_10_s_dos_lecturas_reales_no_se_juntan(sensor):
    registrar_lectura(normalizada(sensor.pk, intervalo_s=10))
    siguiente = normalizada(sensor.pk, hora=HORA + timedelta(seconds=10), intervalo_s=10)
    assert registrar_lectura(siguiente).resultado == Resultado.GUARDADA


def test_antes_de_la_fecha_desde_no_se_guarda(sensor):
    vieja = normalizada(sensor.pk, hora=datetime(2026, 9, 18, 23, 59))
    assert registrar_lectura(vieja).resultado == Resultado.FUERA_DE_FECHA
    assert not Lectura.objects.exists()


def test_deja_marca_de_recalculo_de_su_hora(sensor):
    registrar_lectura(normalizada(sensor.pk))
    marca = MarcaRecalculo.objects.get()
    assert marca.hora == datetime(2026, 9, 26, 12, 0)
    assert marca.causa == CausaRecalculo.LECTURA_ATRASADA


def test_lectura_de_la_hora_en_curso_es_nueva(sensor):
    ahora = datetime.now().replace(microsecond=0)
    registrar_lectura(normalizada(sensor.pk, hora=ahora))
    assert MarcaRecalculo.objects.get().causa == CausaRecalculo.LECTURA_NUEVA


def test_la_muestra_completa_dos_veces_no_duplica(sensor):
    fuente = FuenteDeArchivo()
    consultado = SensorConsultado(id=sensor.pk, mac="AABBCCDDEEFF", token="archivo")
    pagina = fuente.historial(consultado, 1, 1000)
    primera = [registrar_lectura(lectura).resultado for lectura in pagina]
    segunda = [registrar_lectura(lectura).resultado for lectura in pagina]
    guardadas = Lectura.objects.count()
    assert guardadas == primera.count(Resultado.GUARDADA) + primera.count(
        Resultado.COPIA_DISCREPANTE
    )
    assert set(segunda) <= {Resultado.REPETIDA, Resultado.COPIA_IDENTICA}
    # La muestra trae 18 copias por reintento con los mismos valores
    assert primera.count(Resultado.COPIA_IDENTICA) == 18
    assert primera.count(Resultado.COPIA_DISCREPANTE) == 1


def test_la_huella_es_igual_con_el_firmware_viejo_y_el_nuevo():
    valor = {
        "sen55": {"pm1.0": 2.299999952316284, "pm2.5": 3.1, "voc": 0, "nox": None},
        "scd40": {"co2": 515},
        "rtc": {"sleep_interval": 1800},
    }

    def como_lectura(value):
        interpretado = interpretar_valor(value)
        return dataclasses.replace(
            normalizada(1),
            **{
                c: getattr(interpretado, c)
                for c in (
                    "pm1_0",
                    "pm2_5",
                    "pm4_0",
                    "pm10_0",
                    "co2",
                    "temperatura_sen55",
                    "humedad_sen55",
                    "temperatura_scd40",
                    "humedad_scd40",
                    "voc",
                    "nox",
                    "intervalo_s",
                )
            },
            crudo=crudo_de(value),
        )

    nueva = como_lectura(valor)
    vieja = como_lectura(json.dumps(valor))
    assert huella_valores(nueva) == huella_valores(vieja)


def test_la_huella_distingue_un_valor_distinto():
    assert huella_valores(normalizada(1, pm25=18.4)) != huella_valores(normalizada(1, pm25=18.9))


def test_sin_marca_de_recalculo_no_queda_la_lectura(sensor, monkeypatch):
    def falla(*args, **kwargs):
        raise RuntimeError("la base rechazó la marca")

    monkeypatch.setattr("lecturas.services.marcar_recalculo", falla)
    with pytest.raises(RuntimeError):
        registrar_lectura(normalizada(sensor.pk))
    assert not Lectura.objects.exists()
