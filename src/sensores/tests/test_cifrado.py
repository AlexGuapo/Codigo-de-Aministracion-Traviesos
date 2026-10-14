import pytest

from sensores.cifrado import (
    VARIABLE_CLAVE,
    Cifrador,
    ClaveNoConfigurada,
    SecretoIlegible,
    generar_clave,
)
from sensores.validaciones import MacInvalida

# MAC y token inventados para las pruebas
MAC = "A1B2C3D4E5F6"
TOKEN = "tokenDePrueba0123456789abcdef"


@pytest.fixture
def cifrador():
    return Cifrador(generar_clave())


def test_cifrar_y_descifrar_regresa_lo_mismo(cifrador):
    for secreto in (MAC, TOKEN):
        assert cifrador.descifrar(cifrador.cifrar(secreto)) == secreto


def test_lo_cifrado_no_contiene_el_secreto(cifrador):
    cifrado = cifrador.cifrar(TOKEN)
    assert TOKEN.encode() not in cifrado
    assert MAC.encode() not in cifrador.cifrar(MAC)


def test_cifrar_dos_veces_da_textos_distintos(cifrador):
    # Fernet usa un vector aleatorio: por eso la búsqueda va por la huella
    assert cifrador.cifrar(MAC) != cifrador.cifrar(MAC)


def test_con_otra_clave_no_se_puede_descifrar(cifrador):
    cifrado = cifrador.cifrar(TOKEN)
    otro = Cifrador(generar_clave())
    with pytest.raises(SecretoIlegible) as error:
        otro.descifrar(cifrado)
    assert TOKEN not in str(error.value)


def test_huella_es_estable_y_no_depende_de_como_se_escribio(cifrador):
    huella = cifrador.huella_mac(MAC)
    assert len(huella) == 64
    assert cifrador.huella_mac("a1:b2:c3:d4:e5:f6") == huella
    assert cifrador.huella_mac("A1-B2-C3-D4-E5-F6") == huella


def test_huella_no_contiene_la_mac(cifrador):
    assert MAC.lower() not in cifrador.huella_mac(MAC)


def test_huella_cambia_con_la_mac_y_con_la_clave(cifrador):
    huella = cifrador.huella_mac(MAC)
    assert cifrador.huella_mac("A1B2C3D4E5F7") != huella
    assert Cifrador(generar_clave()).huella_mac(MAC) != huella


def test_la_misma_clave_da_la_misma_huella():
    clave = generar_clave()
    assert Cifrador(clave).huella_mac(MAC) == Cifrador(clave).huella_mac(MAC)


def test_huella_de_mac_invalida_se_rechaza(cifrador):
    with pytest.raises(MacInvalida):
        cifrador.huella_mac("no es una mac")


@pytest.mark.parametrize("clave", ["", "corta", "ñ" * 44, "A" * 43])
def test_clave_invalida_se_rechaza_sin_mostrarla(clave):
    with pytest.raises(ClaveNoConfigurada) as error:
        Cifrador(clave)
    if clave:
        assert clave not in str(error.value)


def test_repr_no_muestra_la_clave():
    clave = generar_clave()
    assert clave not in repr(Cifrador(clave))


def test_desde_entorno_lee_la_variable(monkeypatch):
    clave = generar_clave()
    monkeypatch.setenv(VARIABLE_CLAVE, clave)
    assert Cifrador.desde_entorno().huella_mac(MAC) == Cifrador(clave).huella_mac(MAC)


def test_desde_entorno_sin_variable_avisa(monkeypatch):
    monkeypatch.delenv(VARIABLE_CLAVE, raising=False)
    with pytest.raises(ClaveNoConfigurada, match=VARIABLE_CLAVE):
        Cifrador.desde_entorno()
