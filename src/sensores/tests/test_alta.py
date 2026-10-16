from datetime import date, datetime, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from cuentas.models import Cuenta, Estado, Origen, Rol
from cuentas.services import crear_administrador
from lecturas.models import Lectura
from recepcion.models import ConsultaNube, EstadoRelleno, MotivoRelleno, SolicitudRelleno
from sensores.cifrado import Cifrador, generar_clave
from sensores.models import (
    Colonia,
    EstadoSensor,
    EstadoVerificacion,
    InicioResponsabilidad,
    Responsabilidad,
    Sensor,
    Ubicacion,
    VerificacionSensor,
)
from sensores.services import AltaRechazada, confirmar_alta

MAC = "AABBCCDDEEFF"
TOKEN = "token-de-lectura-1"
CONTRASENA = "contrasena-larga"
URL_NUEVO = reverse("sensores:nuevo")


@pytest.fixture
def cifrador(monkeypatch):
    clave = generar_clave()
    monkeypatch.setenv("SARRCA_CLAVE_SECRETOS", clave)
    return Cifrador(clave)


@pytest.fixture
def admin(db):
    return crear_administrador("doctora@ejemplo.mx", "Doctora", CONTRASENA)


@pytest.fixture
def colonia(db):
    return Colonia.objects.create(nombre="Las Flores", municipio="Zacatecas")


def crear_vecino(correo="vecina@ejemplo.mx", nombre="María Pérez Solís", **extra):
    datos = dict(
        correo=correo,
        nombre=nombre,
        rol=Rol.VECINO_SIN_SENSOR,
        estado=Estado.VALIDADA,
        origen=Origen.PRECARGA,
    )
    datos.update(extra)
    cuenta = Cuenta(**datos)
    cuenta.set_password(CONTRASENA)
    cuenta.save()
    return cuenta


@pytest.fixture
def vecina(db):
    return crear_vecino()


def entrar(client, cuenta):
    client.post(reverse("cuentas:entrar"), {"correo": cuenta.correo, "contrasena": CONTRASENA})
    return client


@pytest.fixture
def cliente(client, admin):
    return entrar(client, admin)


def formulario(vecina, colonia, **cambios):
    datos = {
        "nombre_corto": "S-1",
        "mac": "aa:bb:cc:dd:ee:ff",
        "lecturas_desde": (timezone.now().date() - timedelta(days=3)).isoformat(),
        "responsable": vecina.pk,
        "colonia": colonia.pk,
        "direccion": "Calle Hidalgo 123",
        "latitud": "22.770900",
        "longitud": "-102.583200",
    }
    datos.update(cambios)
    return datos


def lista(verificacion, cifrador, terminada_en=None):
    """Lo que deja el proceso de fondo cuando la nube reconoce la MAC."""
    verificacion.estado = EstadoVerificacion.LISTA
    verificacion.token_cifrado = cifrador.cifrar(TOKEN).decode("ascii")
    verificacion.ultima_lectura_en = datetime(2026, 10, 15, 9, 30)
    verificacion.ultima_lectura_resumen = {"pm2_5": 18.4, "pm10_0": 30.1}
    verificacion.terminada_en = terminada_en or timezone.now()
    verificacion.save()
    return verificacion


def pedir_alta(cliente, vecina, colonia, **cambios):
    respuesta = cliente.post(URL_NUEVO, formulario(vecina, colonia, **cambios))
    return respuesta, VerificacionSensor.objects.order_by("-pk").first()


# Formulario


def test_el_formulario_crea_una_verificacion_pendiente_sin_la_mac(
    cliente, vecina, colonia, cifrador
):
    respuesta, verificacion = pedir_alta(cliente, vecina, colonia)
    assert respuesta.status_code == 302
    assert respuesta.url == reverse("sensores:estado_verificacion", args=[verificacion.pk])
    assert verificacion.estado == EstadoVerificacion.PENDIENTE
    assert verificacion.mac_huella == cifrador.huella_mac(MAC)
    assert cifrador.descifrar(verificacion.mac_cifrada.encode("ascii")) == MAC
    assert "mac" not in verificacion.datos_alta
    assert MAC not in str(verificacion.datos_alta)
    assert not Sensor.objects.exists()


def test_un_segundo_clic_reutiliza_la_verificacion(cliente, vecina, colonia, cifrador):
    pedir_alta(cliente, vecina, colonia)
    pedir_alta(cliente, vecina, colonia)
    assert VerificacionSensor.objects.count() == 1


@pytest.mark.parametrize(
    ("cambios", "campo", "mensaje"),
    [
        ({"mac": "AABBCCDDEE"}, "mac", "12 caracteres"),
        ({"nombre_corto": "Sensor-1234"}, "nombre_corto", "de 2 a 10"),
        ({"nombre_corto": "S-Perez"}, "nombre_corto", "responsable"),
        ({"nombre_corto": "Hidalgo"}, "nombre_corto", "dirección"),
        ({"lecturas_desde": "2099-01-01"}, "lecturas_desde", "futura"),
        ({"latitud": "95"}, "latitud", ""),
        ({"direccion": ""}, "direccion", ""),
    ],
)
def test_datos_que_se_rechazan(cliente, vecina, colonia, cifrador, cambios, campo, mensaje):
    respuesta, verificacion = pedir_alta(cliente, vecina, colonia, **cambios)
    assert respuesta.status_code == 200
    errores = respuesta.context["formulario"].errors[campo]
    assert mensaje in " ".join(errores)
    assert verificacion is None


def sensor_existente(cifrador, nombre="G3", mac=MAC, **extra):
    return Sensor.objects.create(
        nombre_corto=nombre,
        mac_cifrada=cifrador.cifrar(mac).decode("ascii"),
        mac_huella=cifrador.huella_mac(mac),
        token_cifrado=cifrador.cifrar("t").decode("ascii"),
        lecturas_desde=date(2026, 9, 1),
        **extra,
    )


def test_la_mac_de_un_sensor_activo_se_rechaza(cliente, vecina, colonia, cifrador):
    sensor_existente(cifrador)
    respuesta, _ = pedir_alta(cliente, vecina, colonia)
    assert "Esa MAC ya pertenece al sensor G3." in respuesta.context["formulario"].errors["mac"]


def test_un_nombre_corto_repetido_se_rechaza(cliente, vecina, colonia, cifrador):
    sensor_existente(cifrador, nombre="s-1", mac="112233445566")
    respuesta, _ = pedir_alta(cliente, vecina, colonia)
    assert "Ya hay un sensor" in respuesta.context["formulario"].errors["nombre_corto"][0]


def test_quien_ya_tiene_sensor_no_aparece_como_responsable(
    cliente, vecina, colonia, cifrador, admin
):
    sensor = sensor_existente(cifrador, mac="112233445566")
    Responsabilidad.objects.create(
        sensor=sensor,
        cuenta=vecina,
        inicio=InicioResponsabilidad.ALTA,
        vigente_desde=datetime(2026, 9, 1),
        registrada_por=admin,
    )
    respuesta, _ = pedir_alta(cliente, vecina, colonia, nombre_corto="S-2")
    assert "responsable" in respuesta.context["formulario"].errors


def test_otro_rol_no_puede_registrar_sensores(client, vecina):
    assert entrar(client, vecina).get(URL_NUEVO).status_code == 403


def test_el_formulario_propone_la_fecha_de_hoy(cliente, cifrador):
    respuesta = cliente.get(URL_NUEVO)
    assert respuesta.context["formulario"].initial["lecturas_desde"] == timezone.now().date()


# Estado de la verificación


def estado(cliente, verificacion, htmx=True):
    url = reverse("sensores:estado_verificacion", args=[verificacion.pk])
    cabeceras = {"HTTP_HX_REQUEST": "true", "HTTP_X_CONSULTA_AUTOMATICA": "1"} if htmx else {}
    return cliente.get(url, **cabeceras)


def test_mientras_espera_la_pantalla_sigue_consultando(cliente, vecina, colonia, cifrador):
    _, verificacion = pedir_alta(cliente, vecina, colonia)
    respuesta = estado(cliente, verificacion)
    assert respuesta.status_code == 200
    assert 'hx-trigger="every 2s"' in respuesta.content.decode()


def test_al_quedar_lista_responde_286_con_el_resumen(cliente, vecina, colonia, cifrador):
    _, verificacion = pedir_alta(cliente, vecina, colonia)
    lista(verificacion, cifrador)
    respuesta = estado(cliente, verificacion)
    html = respuesta.content.decode()
    assert respuesta.status_code == 286
    assert "hx-trigger" not in html
    assert "15/10/2026 09:30" in html
    assert "Confirmar y guardar" in html
    assert MAC not in html and TOKEN not in html


def test_si_nadie_la_atiende_en_60_s_avisa(cliente, vecina, colonia, cifrador):
    _, verificacion = pedir_alta(cliente, vecina, colonia)
    VerificacionSensor.objects.update(solicitada_en=timezone.now() - timedelta(seconds=61))
    respuesta = estado(cliente, verificacion)
    assert respuesta.status_code == 286
    assert "El proceso de fondo no responde" in respuesta.content.decode()


def test_mac_sin_datos_en_la_nube(cliente, vecina, colonia, cifrador):
    _, verificacion = pedir_alta(cliente, vecina, colonia)
    VerificacionSensor.objects.update(estado=EstadoVerificacion.SIN_DATOS)
    respuesta = estado(cliente, verificacion, htmx=False)
    assert "La nube no tiene datos de esa MAC" in respuesta.content.decode()


def test_avisa_las_coordenadas_fuera_de_la_zona(cliente, vecina, colonia, cifrador):
    _, verificacion = pedir_alta(cliente, vecina, colonia, latitud="21.881800")
    lista(verificacion, cifrador)
    assert "fuera de Zacatecas y Guadalupe" in estado(cliente, verificacion).content.decode()


def test_avisa_si_la_nube_empieza_despues_de_la_fecha(cliente, vecina, colonia, cifrador):
    _, verificacion = pedir_alta(cliente, vecina, colonia)
    verificacion.nube_conserva_desde = timezone.now() - timedelta(days=1)
    lista(verificacion, cifrador)
    assert "La nube conserva lecturas desde" in estado(cliente, verificacion).content.decode()


# Confirmación


def confirmar(cliente, verificacion):
    return cliente.post(reverse("sensores:confirmar", args=[verificacion.pk]))


def test_confirmar_guarda_todo_el_alta(cliente, vecina, colonia, cifrador, admin):
    _, verificacion = pedir_alta(cliente, vecina, colonia)
    lista(verificacion, cifrador)
    respuesta = confirmar(cliente, verificacion)
    assert respuesta.status_code == 302

    sensor = Sensor.objects.get()
    desde = timezone.now().date() - timedelta(days=3)
    inicio = datetime.combine(desde, datetime.min.time())
    assert sensor.nombre_corto == "S-1"
    assert sensor.estado == EstadoSensor.ACTIVO
    assert sensor.lecturas_desde == desde
    assert sensor.mac_huella == cifrador.huella_mac(MAC)
    assert cifrador.descifrar(sensor.token_cifrado.encode("ascii")) == TOKEN

    ubicacion = Ubicacion.objects.get(sensor=sensor)
    assert ubicacion.colonia == colonia
    assert ubicacion.vigente_desde == inicio
    assert ubicacion.vigente_hasta is None
    responsabilidad = Responsabilidad.objects.get(sensor=sensor)
    assert responsabilidad.cuenta == vecina
    assert responsabilidad.vigente_desde == inicio

    vecina.refresh_from_db()
    assert vecina.rol == Rol.VECINO_CON_SENSOR
    assert ConsultaNube.objects.filter(sensor=sensor).exists()
    relleno = SolicitudRelleno.objects.get(sensor=sensor)
    assert relleno.desde == inicio
    assert relleno.motivo == MotivoRelleno.ALTA
    assert relleno.estado == EstadoRelleno.PENDIENTE

    verificacion.refresh_from_db()
    assert verificacion.estado == EstadoVerificacion.CONFIRMADA
    assert verificacion.sensor == sensor
    assert "Sensor registrado" in estado(cliente, verificacion, htmx=False).content.decode()


def test_una_cuenta_por_validar_queda_validada(cliente, colonia, cifrador):
    vecina = crear_vecino(estado=Estado.POR_VALIDAR)
    _, verificacion = pedir_alta(cliente, vecina, colonia)
    lista(verificacion, cifrador)
    confirmar(cliente, verificacion)
    vecina.refresh_from_db()
    assert vecina.estado == Estado.VALIDADA
    assert vecina.rol == Rol.VECINO_CON_SENSOR


def test_no_se_confirma_antes_de_que_la_nube_responda(cliente, vecina, colonia, cifrador):
    _, verificacion = pedir_alta(cliente, vecina, colonia)
    assert confirmar(cliente, verificacion).status_code == 409
    assert not Sensor.objects.exists()


def test_una_verificacion_de_mas_de_15_minutos_vence(cliente, vecina, colonia, cifrador):
    _, verificacion = pedir_alta(cliente, vecina, colonia)
    lista(verificacion, cifrador, terminada_en=timezone.now() - timedelta(minutes=16))
    respuesta = confirmar(cliente, verificacion)
    assert respuesta.status_code == 409
    assert "venció" in respuesta.content.decode()
    verificacion.refresh_from_db()
    assert verificacion.estado == EstadoVerificacion.VENCIDA
    assert not Sensor.objects.exists()


def test_si_el_responsable_recibio_otro_sensor_mientras_tanto_se_rechaza(
    cliente, vecina, colonia, cifrador, admin
):
    _, verificacion = pedir_alta(cliente, vecina, colonia)
    lista(verificacion, cifrador)
    otro = sensor_existente(cifrador, nombre="S-9", mac="112233445566")
    Responsabilidad.objects.create(
        sensor=otro,
        cuenta=vecina,
        inicio=InicioResponsabilidad.ALTA,
        vigente_desde=datetime(2026, 9, 1),
        registrada_por=admin,
    )
    with pytest.raises(AltaRechazada, match="ya tiene un sensor"):
        confirmar_alta(verificacion.pk, admin)
    assert Sensor.objects.count() == 1


def test_solo_el_administrador_confirma(vecina, colonia, cifrador, admin):
    verificacion = VerificacionSensor.objects.create(
        mac_cifrada="x", mac_huella="h" * 64, datos_alta={}, solicitada_por=admin
    )
    with pytest.raises(AltaRechazada, match="Solo el Administrador"):
        confirmar_alta(verificacion.pk, vecina)


def test_reactivar_un_sensor_dado_de_baja_conserva_su_historial(cliente, vecina, colonia, cifrador):
    viejo = sensor_existente(
        cifrador, estado=EstadoSensor.DADO_DE_BAJA, dado_de_baja_en=datetime(2026, 9, 20)
    )
    Lectura.objects.create(
        sensor=viejo,
        hora=datetime(2026, 9, 10, 12, 0),
        hora_nube_original="2026-09-11 02:00:00",
        ruta="history",
        origen="nube",
        pm2_5=10.0,
        huella_valores="x" * 64,
        crudo="{}",
    )
    _, verificacion = pedir_alta(cliente, vecina, colonia, nombre_corto="")
    assert verificacion.sensor_existente == viejo
    assert verificacion.datos_alta["nombre_corto"] == "G3"
    lista(verificacion, cifrador)
    assert "dado de baja" in estado(cliente, verificacion).content.decode()

    confirmar(cliente, verificacion)
    viejo.refresh_from_db()
    assert Sensor.objects.count() == 1
    assert viejo.estado == EstadoSensor.ACTIVO
    assert viejo.dado_de_baja_en is None
    assert viejo.lecturas_desde == date(2026, 9, 1)
    assert Lectura.objects.filter(sensor=viejo).count() == 1
    assert Responsabilidad.objects.get(sensor=viejo).inicio == InicioResponsabilidad.REACTIVACION
    assert SolicitudRelleno.objects.get(sensor=viejo).motivo == MotivoRelleno.REACTIVACION
