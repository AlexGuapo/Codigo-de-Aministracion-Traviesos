from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from cuentas.models import Cuenta, Estado, Origen, Rol
from sensores.models import Colonia

pytestmark = pytest.mark.django_db

EJEMPLO = Path(__file__).resolve().parents[3] / "tests" / "datos" / "precarga_cuentas_ejemplo.csv"


@pytest.fixture
def colonias():
    call_command("loaddata", "colonias", verbosity=0)


def test_el_catalogo_de_colonias_carga_completo(colonias):
    assert Colonia.objects.count() == 495
    assert Colonia.objects.filter(municipio="Guadalupe", nombre="Gardenias").exists()
    assert Colonia.objects.filter(municipio="Zacatecas").count() == 191


def test_nombres_repetidos_llevan_su_codigo_postal(colonias):
    assert Colonia.objects.filter(nombre__startswith="Las Flores (CP ").count() == 5


def test_precarga_crea_vecinos_sin_sensor_validados(colonias, monkeypatch):
    monkeypatch.setenv("SARRCA_PRECARGA_CONTRASENA", "contrasena-de-prueba")
    call_command("precargar_cuentas", str(EJEMPLO))
    cuentas = Cuenta.objects.order_by("correo")
    assert cuentas.count() == 3
    assert {c.rol for c in cuentas} == {Rol.VECINO_SIN_SENSOR}
    assert {c.estado for c in cuentas} == {Estado.VALIDADA}
    assert {c.origen for c in cuentas} == {Origen.PRECARGA}
    uno = Cuenta.objects.get(correo="vecina.uno@ejemplo.mx")
    assert uno.colonia.nombre == "Gardenias"
    assert uno.check_password("contrasena-de-prueba")
    assert Cuenta.objects.get(correo="vecina.tres@ejemplo.mx").colonia is None


def test_precarga_dos_veces_no_duplica(colonias, capsys):
    call_command("precargar_cuentas", str(EJEMPLO))
    call_command("precargar_cuentas", str(EJEMPLO))
    assert Cuenta.objects.count() == 3
    assert "Ya existían: 3" in capsys.readouterr().out


def test_sin_contrasena_no_pueden_entrar(colonias, monkeypatch):
    monkeypatch.delenv("SARRCA_PRECARGA_CONTRASENA", raising=False)
    call_command("precargar_cuentas", str(EJEMPLO))
    assert not Cuenta.objects.first().has_usable_password()


def test_colonia_que_no_existe(colonias, tmp_path):
    archivo = tmp_path / "cuentas.csv"
    archivo.write_text("correo,nombre,municipio,colonia\na@ejemplo.mx,A,Guadalupe,Inventada\n")
    with pytest.raises(CommandError, match="Línea 2"):
        call_command("precargar_cuentas", str(archivo))
    assert not Cuenta.objects.exists()


def test_archivo_que_no_existe():
    with pytest.raises(CommandError, match="No existe"):
        call_command("precargar_cuentas", "no_existe.csv")
