import time
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import timezone

from cuentas.models import Cuenta, Estado, IntentoAcceso, Origen, Rol
from cuentas.permisos import rol_requerido
from cuentas.services import (
    CLAVE_ULTIMA_ACTIVIDAD,
    AdministradorYaExiste,
    crear_administrador,
    desbloquear,
    pausa_hasta,
)
from cuentas.views import MENSAJE_DATOS_INCORRECTOS, MENSAJE_PAUSA

pytestmark = pytest.mark.django_db

CONTRASENA = "contrasena-de-prueba"
URL_ENTRAR = "/cuentas/entrar/"


def nueva_cuenta(correo, rol=Rol.VECINO_SIN_SENSOR, estado=Estado.VALIDADA):
    cuenta = Cuenta(
        correo=correo, nombre="Persona de prueba", rol=rol, estado=estado, origen=Origen.PRECARGA
    )
    cuenta.set_password(CONTRASENA)
    cuenta.save()
    return cuenta


@pytest.fixture
def admin():
    return crear_administrador("doctora@ejemplo.mx", "Doctora", CONTRASENA)


def entrar(client, correo, contrasena=CONTRASENA, **extra):
    return client.post(URL_ENTRAR, {"correo": correo, "contrasena": contrasena}, **extra)


def envejecer_intentos(minutos):
    IntentoAcceso.objects.update(ocurrido_en=timezone.now() - timedelta(minutes=minutos))


# Cuenta de Administrador


def test_crear_administrador(admin):
    assert admin.rol == Rol.ADMINISTRADOR
    assert admin.estado == Estado.VALIDADA
    assert admin.origen == Origen.INSTALACION
    assert admin.check_password(CONTRASENA)


def test_no_puede_haber_dos_administradores(admin):
    with pytest.raises(AdministradorYaExiste):
        crear_administrador("otra@ejemplo.mx", "Otra", CONTRASENA)
    assert Cuenta.objects.filter(rol=Rol.ADMINISTRADOR).count() == 1


def test_contrasena_de_menos_de_8_caracteres():
    with pytest.raises(ValidationError):
        crear_administrador("doctora@ejemplo.mx", "Doctora", "corta")
    assert not Cuenta.objects.exists()


def test_comando_crear_admin(monkeypatch, capsys):
    monkeypatch.setenv("SARRCA_ADMIN_CONTRASENA", CONTRASENA)
    call_command("crear_admin", correo="Doctora@Ejemplo.mx", nombre="Doctora")
    call_command("crear_admin", correo="otra@ejemplo.mx", nombre="Otra")
    salida = capsys.readouterr().out
    assert "creada: doctora@ejemplo.mx" in salida
    assert "Ya existe" in salida
    assert Cuenta.objects.count() == 1


# Entrar


def test_la_administradora_entra_al_panel(client, admin):
    respuesta = entrar(client, "doctora@ejemplo.mx")
    assert respuesta.status_code == 302
    assert respuesta.url == "/"


def test_un_vecino_entra_a_su_inicio(client):
    nueva_cuenta("vecino@ejemplo.mx")
    respuesta = entrar(client, "vecino@ejemplo.mx")
    assert respuesta.url == "/cuentas/inicio/"


def test_el_correo_no_distingue_mayusculas_ni_espacios(client, admin):
    assert entrar(client, "  Doctora@Ejemplo.MX ").status_code == 302


@pytest.mark.parametrize("caso", ["contrasena_mala", "correo_inexistente", "por_activar", "baja"])
def test_mismo_mensaje_en_todos_los_rechazos(client, caso):
    nueva_cuenta("vecino@ejemplo.mx")
    nueva_cuenta("invitado@ejemplo.mx", estado=Estado.POR_ACTIVAR)
    nueva_cuenta("baja@ejemplo.mx", estado=Estado.DADA_DE_BAJA)
    correo, contrasena = {
        "contrasena_mala": ("vecino@ejemplo.mx", "otra-contrasena"),
        "correo_inexistente": ("nadie@ejemplo.mx", CONTRASENA),
        "por_activar": ("invitado@ejemplo.mx", CONTRASENA),
        "baja": ("baja@ejemplo.mx", CONTRASENA),
    }[caso]
    respuesta = entrar(client, correo, contrasena)
    assert respuesta.status_code == 200
    assert MENSAJE_DATOS_INCORRECTOS in respuesta.content.decode()
    assert "_auth_user_id" not in client.session


def test_la_contrasena_nunca_se_devuelve(client, admin):
    respuesta = entrar(client, "doctora@ejemplo.mx", "contrasena-equivocada")
    assert "contrasena-equivocada" not in respuesta.content.decode()


def test_next_a_otro_sitio_se_ignora(client, admin):
    respuesta = client.post(
        URL_ENTRAR + "?next=https://otro-sitio.com/",
        {
            "correo": "doctora@ejemplo.mx",
            "contrasena": CONTRASENA,
            "next": "https://otro-sitio.com/",
        },
    )
    assert respuesta.url == "/"


def test_cada_intento_queda_registrado(client, admin):
    entrar(client, "doctora@ejemplo.mx", "mala")
    entrar(client, "doctora@ejemplo.mx")
    assert list(IntentoAcceso.objects.order_by("id").values_list("exito", flat=True)) == [
        False,
        True,
    ]


# Pausa por intentos fallidos


def test_el_quinto_fallo_activa_la_pausa(client, admin):
    for _ in range(4):
        assert entrar(client, "doctora@ejemplo.mx", "mala").status_code == 200
    respuesta = entrar(client, "doctora@ejemplo.mx", "mala")
    assert respuesta.status_code == 429
    assert MENSAJE_PAUSA in respuesta.content.decode()


def test_en_pausa_ni_la_contrasena_correcta_entra(client, admin):
    for _ in range(5):
        entrar(client, "doctora@ejemplo.mx", "mala")
    assert entrar(client, "doctora@ejemplo.mx").status_code == 429


def test_la_pausa_es_por_correo_e_ip(client, admin):
    for _ in range(5):
        entrar(client, "doctora@ejemplo.mx", "mala")
    assert entrar(client, "doctora@ejemplo.mx", REMOTE_ADDR="203.0.113.7").status_code == 302


def test_la_pausa_termina_a_los_15_minutos(client, admin):
    for _ in range(5):
        entrar(client, "doctora@ejemplo.mx", "mala")
    envejecer_intentos(16)
    assert entrar(client, "doctora@ejemplo.mx").status_code == 302


def test_los_intentos_en_pausa_no_la_alargan(admin):
    inicio = timezone.now() - timedelta(minutes=10)
    for i in range(5):
        IntentoAcceso.objects.create(
            correo_intentado="doctora@ejemplo.mx",
            ip="127.0.0.1",
            exito=False,
            ocurrido_en=inicio + timedelta(seconds=i),
        )
    hasta = pausa_hasta("doctora@ejemplo.mx", "127.0.0.1")
    for i in range(3):
        IntentoAcceso.objects.create(
            correo_intentado="doctora@ejemplo.mx",
            ip="127.0.0.1",
            exito=False,
            ocurrido_en=inicio + timedelta(minutes=5 + i),
        )
    assert pausa_hasta("doctora@ejemplo.mx", "127.0.0.1") == hasta


def test_fallos_fuera_de_la_ventana_no_suman(admin):
    ahora = timezone.now()
    for minutos in (29, 20, 12, 6, 1):
        IntentoAcceso.objects.create(
            correo_intentado="doctora@ejemplo.mx",
            ip="127.0.0.1",
            exito=False,
            ocurrido_en=ahora - timedelta(minutes=minutos),
        )
    assert pausa_hasta("doctora@ejemplo.mx", "127.0.0.1") is None


def test_un_acceso_correcto_reinicia_el_conteo(client, admin):
    for _ in range(4):
        entrar(client, "doctora@ejemplo.mx", "mala")
    entrar(client, "doctora@ejemplo.mx")
    client.post("/cuentas/salir/")
    assert entrar(client, "doctora@ejemplo.mx", "mala").status_code == 200


def test_desbloquear_levanta_la_pausa(client, admin, capsys):
    for _ in range(5):
        entrar(client, "doctora@ejemplo.mx", "mala")
    call_command("desbloquear", "doctora@ejemplo.mx")
    assert "borrados: 5" in capsys.readouterr().out
    assert entrar(client, "doctora@ejemplo.mx").status_code == 302


def test_desbloquear_solo_una_ip(admin):
    for ip in ("127.0.0.1", "203.0.113.7"):
        IntentoAcceso.objects.create(correo_intentado="doctora@ejemplo.mx", ip=ip, exito=False)
    assert desbloquear("doctora@ejemplo.mx", "203.0.113.7") == 1
    assert IntentoAcceso.objects.count() == 1


# Sesión


def test_salir_cierra_la_sesion(client, admin):
    entrar(client, "doctora@ejemplo.mx")
    respuesta = client.post("/cuentas/salir/")
    assert respuesta.url == URL_ENTRAR
    assert "_auth_user_id" not in client.session


def test_salir_solo_por_post(client, admin):
    entrar(client, "doctora@ejemplo.mx")
    assert client.get("/cuentas/salir/").status_code == 405


def test_sesion_vencida_a_las_2_horas(client):
    nueva_cuenta("vecino@ejemplo.mx")
    entrar(client, "vecino@ejemplo.mx")
    sesion = client.session
    sesion[CLAVE_ULTIMA_ACTIVIDAD] = time.time() - 2 * 60 * 60 - 1
    sesion.save()
    respuesta = client.get("/cuentas/inicio/")
    assert respuesta.status_code == 302
    assert respuesta.url == URL_ENTRAR


def test_sesion_vencida_con_htmx_redirige_la_pagina(client):
    nueva_cuenta("vecino@ejemplo.mx")
    entrar(client, "vecino@ejemplo.mx")
    sesion = client.session
    sesion[CLAVE_ULTIMA_ACTIVIDAD] = time.time() - 3 * 60 * 60
    sesion.save()
    respuesta = client.get("/cuentas/inicio/", HTTP_HX_REQUEST="true")
    assert respuesta.status_code == 401
    assert respuesta["HX-Redirect"] == URL_ENTRAR


def test_la_consulta_automatica_no_cuenta_como_actividad(client):
    nueva_cuenta("vecino@ejemplo.mx")
    entrar(client, "vecino@ejemplo.mx")
    sesion = client.session
    hace_una_hora = time.time() - 60 * 60
    sesion[CLAVE_ULTIMA_ACTIVIDAD] = hace_una_hora
    sesion.save()
    client.get("/cuentas/inicio/", HTTP_X_CONSULTA_AUTOMATICA="1")
    assert client.session[CLAVE_ULTIMA_ACTIVIDAD] == hace_una_hora
    client.get("/cuentas/inicio/")
    assert client.session[CLAVE_ULTIMA_ACTIVIDAD] > hace_una_hora


def test_con_sesion_iniciada_entrar_lleva_a_su_pantalla(client, admin):
    entrar(client, "doctora@ejemplo.mx")
    assert client.get(URL_ENTRAR).url == "/"


# Permiso por rol


@rol_requerido(Rol.ADMINISTRADOR)
def vista_de_administrador(request):
    return HttpResponse("ok")


def test_rol_requerido_sin_sesion_lleva_a_entrar():
    peticion = RequestFactory().get("/reportes/diario/")
    peticion.user = type("Anonimo", (), {"is_authenticated": False})()
    respuesta = vista_de_administrador(peticion)
    assert respuesta.status_code == 302
    assert respuesta.url.startswith(URL_ENTRAR + "?next=")


def test_rol_requerido_niega_otro_rol():
    peticion = RequestFactory().get("/reportes/diario/")
    peticion.user = nueva_cuenta("vecino@ejemplo.mx")
    assert vista_de_administrador(peticion).status_code == 403


def test_rol_requerido_deja_pasar_al_administrador(admin):
    peticion = RequestFactory().get("/reportes/diario/")
    peticion.user = admin
    assert vista_de_administrador(peticion).status_code == 200
