from datetime import date, datetime, timedelta

import pytest
from django.utils import timezone

from cuentas.services import crear_administrador
from lecturas.models import Lectura
from recepcion.alta import atender_rellenos, atender_verificaciones
from recepcion.models import ConsultaNube, EstadoRelleno, MotivoRelleno, SolicitudRelleno
from recepcion.ports import FuenteNoDisponible, ResultadoToken
from recepcion.services import Lector
from recepcion.tests.nube_falsa import INICIO, MAC, NubeFalsa, crear_sensor, lectura
from sensores.cifrado import Cifrador, generar_clave
from sensores.models import EstadoVerificacion, VerificacionSensor


class NubeDelAlta(NubeFalsa):
    def __init__(self, falla_token=None, apodo="aire-casa", **extra):
        super().__init__(**extra)
        self.falla_token = falla_token
        self.apodo = apodo
        self.macs = []

    def obtener_token(self, mac):
        self.macs.append(mac)
        if self.falla_token:
            raise self.falla_token
        return ResultadoToken(
            token=self.token, apodo=self.apodo, ultima=lectura(0, self.horas[0], pm25=18.4)
        )


@pytest.fixture
def cifrador():
    return Cifrador(generar_clave())


@pytest.fixture
def admin(db):
    return crear_administrador("doctora@ejemplo.mx", "Doctora", "contrasena-larga")


def crear_verificacion(cifrador, admin, **extra):
    return VerificacionSensor.objects.create(
        mac_cifrada=cifrador.cifrar(MAC).decode("ascii"),
        mac_huella=cifrador.huella_mac(MAC),
        datos_alta={"nombre_corto": "S-1"},
        solicitada_por=admin,
        **extra,
    )


# Verificación


def test_la_verificacion_queda_lista_con_token_cifrado_y_ultima_lectura(cifrador, admin):
    verificacion = crear_verificacion(cifrador, admin)
    nube = NubeDelAlta(cantidad=20)
    assert atender_verificaciones(nube, cifrador) == 1
    verificacion.refresh_from_db()
    assert nube.macs == [MAC]
    assert verificacion.estado == EstadoVerificacion.LISTA
    assert verificacion.tomada_en is not None
    assert verificacion.terminada_en is not None
    assert "token-1" not in verificacion.token_cifrado
    assert cifrador.descifrar(verificacion.token_cifrado.encode("ascii")) == "token-1"
    assert cifrador.descifrar(verificacion.apodo_cifrado.encode("ascii")) == "aire-casa"
    assert verificacion.ultima_lectura_en == INICIO + timedelta(minutes=30 * 19)
    assert verificacion.ultima_lectura_resumen["pm2_5"] == 18.4


def test_la_verificacion_dice_desde_cuando_conserva_la_nube(cifrador, admin):
    verificacion = crear_verificacion(cifrador, admin)
    atender_verificaciones(NubeDelAlta(cantidad=120), cifrador)
    verificacion.refresh_from_db()
    assert verificacion.nube_conserva_desde == INICIO


def test_mac_sin_datos_en_la_nube(cifrador, admin):
    verificacion = crear_verificacion(cifrador, admin)
    falla = FuenteNoDisponible("la nube respondió sin datos", respondio=True)
    atender_verificaciones(NubeDelAlta(falla_token=falla), cifrador)
    verificacion.refresh_from_db()
    assert verificacion.estado == EstadoVerificacion.SIN_DATOS
    assert verificacion.token_cifrado is None


def test_la_nube_no_responde(cifrador, admin):
    verificacion = crear_verificacion(cifrador, admin)
    falla = FuenteNoDisponible("tiempo de espera agotado")
    atender_verificaciones(NubeDelAlta(falla_token=falla), cifrador)
    verificacion.refresh_from_db()
    assert verificacion.estado == EstadoVerificacion.NUBE_NO_RESPONDE
    assert verificacion.terminada_en is not None


def test_si_el_historial_falla_la_verificacion_sigue_sin_esa_fecha(cifrador, admin):
    verificacion = crear_verificacion(cifrador, admin)
    nube = NubeDelAlta(fallas=[FuenteNoDisponible("tiempo de espera agotado")])
    atender_verificaciones(nube, cifrador)
    verificacion.refresh_from_db()
    assert verificacion.estado == EstadoVerificacion.LISTA
    assert verificacion.nube_conserva_desde is None


def test_no_vuelve_a_atender_una_que_ya_termino(cifrador, admin):
    crear_verificacion(cifrador, admin)
    nube = NubeDelAlta()
    atender_verificaciones(nube, cifrador)
    assert atender_verificaciones(nube, cifrador) == 0
    assert nube.macs == [MAC]


def test_una_lista_sin_confirmar_vence_a_los_15_minutos(cifrador, admin):
    verificacion = crear_verificacion(cifrador, admin)
    atender_verificaciones(NubeDelAlta(), cifrador)
    VerificacionSensor.objects.update(terminada_en=timezone.now() - timedelta(minutes=16))
    atender_verificaciones(NubeDelAlta(), cifrador)
    verificacion.refresh_from_db()
    assert verificacion.estado == EstadoVerificacion.VENCIDA


# Relleno


def crear_relleno(sensor, admin, desde):
    return SolicitudRelleno.objects.create(
        sensor=sensor, desde=desde, motivo=MotivoRelleno.ALTA, solicitada_por=admin
    )


def test_el_relleno_trae_el_historial_desde_la_fecha_elegida(cifrador, admin):
    sensor = crear_sensor(cifrador, desde=date(2026, 10, 3))
    solicitud = crear_relleno(sensor, admin, datetime(2026, 10, 3))
    nube = NubeFalsa(cantidad=500)
    assert atender_rellenos(Lector(nube, cifrador, dormir=lambda _s: None)) == 1
    solicitud.refresh_from_db()
    assert solicitud.estado == EstadoRelleno.TERMINADA
    assert solicitud.tomada_en is not None
    assert solicitud.terminada_en is not None
    # del 03/10 00:05 al 11/10 09:35, cada 30 min
    assert solicitud.lecturas_nuevas == 404
    assert Lectura.objects.filter(sensor=sensor).count() == 404
    assert len(nube.llamadas) == 9
    assert ConsultaNube.objects.get(sensor=sensor).ultimo_recorrido_completo_en is not None


def test_un_relleno_fallido_queda_con_su_error(cifrador, admin):
    sensor = crear_sensor(cifrador)
    solicitud = crear_relleno(sensor, admin, datetime(2026, 9, 1))
    falla = FuenteNoDisponible("sin conexión con la nube", sensor.pk)
    nube = NubeFalsa(fallas=[falla, falla])
    atender_rellenos(Lector(nube, cifrador, dormir=lambda _s: None))
    solicitud.refresh_from_db()
    assert solicitud.estado == EstadoRelleno.FALLIDA
    assert solicitud.error == "sin conexión con la nube"
    assert solicitud.lecturas_nuevas == 0


def test_un_relleno_terminado_no_se_repite(cifrador, admin):
    sensor = crear_sensor(cifrador)
    crear_relleno(sensor, admin, datetime(2026, 9, 1))
    lector = Lector(NubeFalsa(cantidad=10), cifrador, dormir=lambda _s: None)
    atender_rellenos(lector)
    assert atender_rellenos(lector) == 0
