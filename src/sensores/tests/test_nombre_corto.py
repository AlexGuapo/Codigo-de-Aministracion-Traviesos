import pytest

from sensores.validaciones import NombreCortoInvalido, validar_nombre_corto

# Datos inventados para las pruebas
RESPONSABLE = "María Pérez Solís"
DIRECCION = "Calle Hidalgo 123, Col. Las Flores"


def validar(nombre):
    return validar_nombre_corto(
        nombre, nombre_responsable=RESPONSABLE, direccion=DIRECCION
    )


@pytest.mark.parametrize("nombre", ["S-1", "S-12", "Norte", "Escuela 3", "SG-7"])
def test_nombres_sin_datos_personales_se_aceptan(nombre):
    assert validar(nombre) == nombre


def test_quita_espacios_alrededor():
    assert validar("  S-1  ") == "S-1"


@pytest.mark.parametrize("nombre", ["", "   ", None])
def test_nombre_vacio_se_rechaza(nombre):
    with pytest.raises(NombreCortoInvalido, match="Falta"):
        validar(nombre)


@pytest.mark.parametrize(
    "nombre", ["Maria", "S-Perez", "sPÉREZ", "Casa Solís", "S_maría_1"]
)
def test_con_el_nombre_del_responsable_se_rechaza(nombre):
    with pytest.raises(NombreCortoInvalido, match="responsable"):
        validar(nombre)


@pytest.mark.parametrize("nombre", ["Hidalgo", "S-Hidalgo1", "Flores", "LASFLORES"])
def test_con_la_direccion_se_rechaza(nombre):
    with pytest.raises(NombreCortoInvalido, match="dirección"):
        validar(nombre)


@pytest.mark.parametrize("nombre", ["S-123", "Calle 1", "Col-2"])
def test_numeros_y_palabras_comunes_de_la_direccion_no_cuentan(nombre):
    # «calle» y «col» no identifican a nadie; los números tampoco se revisan
    assert validar(nombre) == nombre


def test_el_error_no_repite_el_dato_personal():
    with pytest.raises(NombreCortoInvalido) as error:
        validar("S-Perez")
    assert "erez" not in str(error.value).lower()
