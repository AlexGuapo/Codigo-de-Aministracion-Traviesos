import pytest

from sensores.validaciones import MacInvalida, normalizar_mac

# MAC inventada para las pruebas, no es la de ningún sensor real
MAC = "A1B2C3D4E5F6"


@pytest.mark.parametrize(
    "capturada",
    [
        "A1B2C3D4E5F6",
        "a1b2c3d4e5f6",
        "A1:B2:C3:D4:E5:F6",
        "a1-b2-c3-d4-e5-f6",
        "  A1:B2:C3:D4:E5:F6  ",
    ],
)
def test_formas_validas_dan_la_misma_mac(capturada):
    assert normalizar_mac(capturada) == MAC


@pytest.mark.parametrize(
    "capturada",
    [
        "",
        None,
        "A1B2C3D4E5",  # 10 caracteres
        "A1B2C3D4E5F6A7",  # 14 caracteres
        "G1B2C3D4E5F6",  # G no es hexadecimal
        "A1:B2-C3:D4-E5:F6",  # separadores mezclados
        "A1:B2C3:D4:E5:F6",  # le falta un separador
        "A1B:2C:3D:4E:5F:6",  # separadores fuera de lugar
        "A1 B2 C3 D4 E5 F6",  # espacios en medio
    ],
)
def test_formas_invalidas_se_rechazan(capturada):
    with pytest.raises(MacInvalida):
        normalizar_mac(capturada)


def test_el_error_no_repite_la_mac():
    capturada = "ZZ:B2:C3:D4:E5:F6"
    with pytest.raises(MacInvalida) as error:
        normalizar_mac(capturada)
    assert "B2" not in str(error.value)
