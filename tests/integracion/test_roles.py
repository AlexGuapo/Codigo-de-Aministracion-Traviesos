"""Inicio de sesión junto con los permisos de cada rol, por las rutas reales."""

import pytest
from django.urls import reverse

from cuentas.models import Cuenta, Estado, Origen, Rol
from cuentas.services import crear_administrador

CONTRASENA = "contrasena-de-prueba"

RUTAS_DEL_ADMINISTRADOR = [
    reverse("reportes:panel_red"),
    reverse("reportes:diario"),
    reverse("reportes:mensual"),
    reverse("reportes:lamina"),
    reverse("sensores:nuevo"),
    reverse("sensores:estado_verificacion", args=[1]),
]


def vecino(rol, correo):
    cuenta = Cuenta(
        correo=correo,
        nombre="Persona de prueba",
        rol=rol,
        estado=Estado.VALIDADA,
        origen=Origen.PRECARGA,
    )
    cuenta.set_password(CONTRASENA)
    cuenta.save()
    return cuenta


@pytest.fixture
def admin(db):
    return crear_administrador("doctora@ejemplo.mx", "Doctora", CONTRASENA)


@pytest.fixture(params=[Rol.VECINO_CON_SENSOR, Rol.VECINO_SIN_SENSOR])
def otro_rol(request, db):
    return vecino(request.param, f"{request.param}@ejemplo.mx")


def entrar(client, cuenta):
    return client.post(
        reverse("cuentas:entrar"), {"correo": cuenta.correo, "contrasena": CONTRASENA}
    )


def test_el_administrador_entra_al_panel(client, admin):
    respuesta = entrar(client, admin)
    assert respuesta.status_code == 302
    assert respuesta.url == reverse("reportes:panel_red")


def test_un_vecino_entra_a_su_inicio(client, otro_rol):
    respuesta = entrar(client, otro_rol)
    assert respuesta.url == reverse("cuentas:inicio")
    assert client.get(respuesta.url).status_code == 200


@pytest.mark.parametrize("ruta", RUTAS_DEL_ADMINISTRADOR)
def test_otro_rol_recibe_403_en_las_rutas_del_administrador(client, otro_rol, ruta):
    entrar(client, otro_rol)
    respuesta = client.get(ruta)
    assert respuesta.status_code == 403
    assert "No tiene permiso" in respuesta.content.decode()


@pytest.mark.parametrize("ruta", RUTAS_DEL_ADMINISTRADOR)
def test_sin_sesion_lleva_a_iniciar_sesion(client, db, ruta):
    respuesta = client.get(ruta)
    assert respuesta.status_code == 302
    assert respuesta.url.startswith(reverse("cuentas:entrar"))


@pytest.mark.parametrize("ruta", RUTAS_DEL_ADMINISTRADOR[:5])
def test_el_administrador_si_pasa(client, admin, ruta):
    entrar(client, admin)
    assert client.get(ruta).status_code != 403


def test_al_salir_ya_no_entra_a_las_rutas_del_administrador(client, admin):
    entrar(client, admin)
    client.post(reverse("cuentas:salir"))
    respuesta = client.get(reverse("reportes:diario"))
    assert respuesta.status_code == 302
