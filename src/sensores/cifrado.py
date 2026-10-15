"""Cifrado de la MAC y del token de los sensores.

ADR «MAC y token protegidos» y RNF-SEG-04:

- La MAC y el token se guardan cifrados con Fernet. La clave es
  `SARRCA_CLAVE_SECRETOS`, en el .env del servidor, nunca en el repositorio.
- Para que la MAC sea única y se pueda buscar sin descifrarla se guarda
  también su huella: HMAC-SHA256 sobre la MAC normalizada. La clave del HMAC
  se deriva de la misma clave de secretos, separada con una etiqueta para no
  usar los mismos bytes en dos algoritmos.
- Ningún error ni repr lleva la clave, la MAC ni el token.

Aquí no se importa Django: el modelo y el servicio de `sensores` lo usan, y
también el worker (recepción) para descifrar antes de consultar la nube.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os

from cryptography.fernet import Fernet, InvalidToken

from sensores.validaciones import normalizar_mac

VARIABLE_CLAVE = "SARRCA_CLAVE_SECRETOS"
_ETIQUETA_HUELLA = b"sarrca:huella-mac:v1"


class ClaveNoConfigurada(RuntimeError):
    """Falta la clave de secretos o no es una clave de Fernet."""


class SecretoIlegible(ValueError):
    """El dato cifrado no se pudo descifrar con la clave actual."""


class Cifrador:
    """Cifra y descifra secretos y saca la huella de una MAC."""

    def __init__(self, clave: str | bytes) -> None:
        try:
            if isinstance(clave, str):
                clave = clave.strip().encode("ascii")
            self._fernet = Fernet(clave)
            bytes_clave = base64.urlsafe_b64decode(clave)
        except (ValueError, binascii.Error):
            raise ClaveNoConfigurada(
                f"{VARIABLE_CLAVE} no es una clave válida de Fernet."
            ) from None
        self._clave_huella = hmac.new(
            bytes_clave, _ETIQUETA_HUELLA, hashlib.sha256
        ).digest()

    @classmethod
    def desde_entorno(cls) -> Cifrador:
        clave = os.environ.get(VARIABLE_CLAVE, "")
        if not clave.strip():
            raise ClaveNoConfigurada(f"Falta {VARIABLE_CLAVE} en el .env.")
        return cls(clave)

    def __repr__(self) -> str:
        return "Cifrador(clave=****)"

    def cifrar(self, texto: str) -> bytes:
        return self._fernet.encrypt(texto.encode("utf-8"))

    def descifrar(self, cifrado: bytes) -> str:
        try:
            return self._fernet.decrypt(cifrado).decode("utf-8")
        except InvalidToken:
            raise SecretoIlegible(
                "No se pudo descifrar el dato con la clave actual."
            ) from None

    def huella_mac(self, mac: str) -> str:
        """Huella (64 hexadecimales) de la MAC ya normalizada.

        La misma MAC escrita con o sin «:» da la misma huella.
        """
        return hmac.new(
            self._clave_huella, normalizar_mac(mac).encode("ascii"), hashlib.sha256
        ).hexdigest()


def generar_clave() -> str:
    """Clave nueva para `SARRCA_CLAVE_SECRETOS` (se corre una sola vez)."""
    return Fernet.generate_key().decode("ascii")
