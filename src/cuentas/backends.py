"""Provisional: autenticación por omisión de Django."""

from django.contrib.auth.backends import ModelBackend


class CuentaBackend(ModelBackend):
    """Autentica por correo y contraseña."""
