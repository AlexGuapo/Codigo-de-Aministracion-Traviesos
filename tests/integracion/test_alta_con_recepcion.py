"""El alta de un sensor de punta a punta, con la muestra de S-1 en lugar de la nube."""

from datetime import datetime, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from calculo.models import Periodo, ValorCalculado
from cuentas.models import Cuenta, Estado, Origen, Rol
from lecturas.models import Lectura
from recepcion.adapters.archivo import FuenteDeArchivo
from recepcion.alta import atender_rellenos, atender_verificaciones
from recepcion.models import ConsultaNube, EstadoRelleno, SolicitudRelleno
from recepcion.ports import FuenteNoDisponible, SensorConsultado
from recepcion.services import Lector, sondear
from sensores.cifrado import Cifrador, generar_clave
from sensores.models import Colonia, EstadoVerificacion, Sensor, VerificacionSensor
from tests.integracion.ayudas import calcular, sesion_de_administrador


@pytest.fixture
def cifrador(monkeypatch):
    clave = generar_clave()
    monkeypatch.setenv("SARRCA_CLAVE_SECRETOS", clave)
    return Cifrador(clave)


@pytest.fixture
def ahora():
    return timezone.now().replace(microsecond=0)


@pytest.fixture
def fuente(ahora):
    return FuenteDeArchivo(terminar_en=ahora - timedelta(minutes=5))


@pytest.fixture
def datos(db):
    colonia = Colonia.objects.create(nombre="Las Flores", municipio="Zacatecas")
    vecina = Cuenta.objects.create(
        correo="vecina@ejemplo.mx",
        nombre="Vecina Uno",
        rol=Rol.VECINO_SIN_SENSOR,
        estado=Estado.POR_VALIDAR,
        origen=Origen.PRECARGA,
    )
    return colonia, vecina


def test_alta_completa_con_la_muestra(client, cifrador, fuente, datos, ahora):
    colonia, vecina = datos
    sesion_de_administrador(client)
    desde = (ahora - timedelta(days=3)).date()

    # 1. La Administradora llena el formulario.
    client.post(
        reverse("sensores:nuevo"),
        {
            "nombre_corto": "S-1",
            "mac": "aa:bb:cc:dd:ee:01",
            "lecturas_desde": desde.isoformat(),
            "responsable": vecina.pk,
            "colonia": colonia.pk,
            "direccion": "Calle Hidalgo 123",
            "latitud": "22.770900",
            "longitud": "-102.583200",
        },
    )
    verificacion = VerificacionSensor.objects.get()

    # 2. El proceso de fondo la atiende y la pantalla muestra el resumen.
    atender_verificaciones(fuente, cifrador)
    verificacion.refresh_from_db()
    assert verificacion.estado == EstadoVerificacion.LISTA
    url_estado = reverse("sensores:estado_verificacion", args=[verificacion.pk])
    resumen = client.get(url_estado, HTTP_HX_REQUEST="true")
    assert resumen.status_code == 286
    assert "Confirmar y guardar" in resumen.content.decode()

    # 3. Confirma, y el proceso de fondo trae las lecturas desde la fecha elegida.
    client.post(reverse("sensores:confirmar", args=[verificacion.pk]))
    sensor = Sensor.objects.get()
    lector = Lector(fuente, cifrador, dormir=lambda _s: None)
    assert atender_rellenos(lector) == 1
    relleno = SolicitudRelleno.objects.get(sensor=sensor)
    assert relleno.estado == EstadoRelleno.TERMINADA

    inicio = datetime.combine(desde, datetime.min.time())
    consultado = SensorConsultado(id=sensor.pk, mac="AABBCCDDEE01", token="archivo")
    en_la_muestra = {
        lectura.hora_local
        for pagina in range(1, 11)
        for lectura in fuente.historial(consultado, pagina, 50)
        if lectura.hora_local >= inicio
    }
    guardadas = set(Lectura.objects.filter(sensor=sensor).values_list("hora", flat=True))
    assert guardadas <= en_la_muestra
    assert relleno.lecturas_nuevas == len(guardadas) > 0
    assert min(guardadas) >= inicio
    assert ConsultaNube.objects.get(sensor=sensor).ultimo_exito_en is not None

    vecina.refresh_from_db()
    assert vecina.rol == Rol.VECINO_CON_SENSOR
    assert vecina.estado == Estado.VALIDADA

    # 4. El sondeo no repite nada y el cálculo ya tiene las horas.
    assert sondear(lector)[sensor.pk].nuevas == 0
    assert Lectura.objects.filter(sensor=sensor).count() == len(guardadas)
    calcular(ahora)
    assert ValorCalculado.objects.filter(sensor=sensor, periodo=Periodo.HORA).exists()


def test_la_mac_que_la_nube_no_conoce_no_registra_nada(client, cifrador, datos):
    colonia, vecina = datos
    sesion_de_administrador(client)

    class NubeSinEsaMac(FuenteDeArchivo):
        def obtener_token(self, mac):
            raise FuenteNoDisponible("la nube respondió sin datos", respondio=True)

    client.post(
        reverse("sensores:nuevo"),
        {
            "nombre_corto": "S-1",
            "mac": "AABBCCDDEE02",
            "lecturas_desde": timezone.now().date().isoformat(),
            "responsable": vecina.pk,
            "colonia": colonia.pk,
            "direccion": "Calle Hidalgo 123",
            "latitud": "22.770900",
            "longitud": "-102.583200",
        },
    )
    atender_verificaciones(NubeSinEsaMac(), cifrador)
    verificacion = VerificacionSensor.objects.get()
    html = client.get(reverse("sensores:estado_verificacion", args=[verificacion.pk])).content
    assert "La nube no tiene datos de esa MAC" in html.decode()
    assert client.post(reverse("sensores:confirmar", args=[verificacion.pk])).status_code == 409
    assert not Sensor.objects.exists()
