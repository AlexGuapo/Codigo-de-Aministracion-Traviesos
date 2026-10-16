from django.contrib.auth.backends import ModelBackend


class CuentaBackend(ModelBackend):
    """Autentica por correo y contraseña, sin importar mayúsculas ni espacios en el correo.

    `ModelBackend` ya tarda lo mismo cuando el correo no existe (así no se distingue por la
    demora) y rechaza las cuentas cuyo `is_active` es falso: por activar, bloqueadas, dadas de
    baja o suprimidas.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is not None:
            username = username.strip().lower()
        return super().authenticate(request, username=username, password=password, **kwargs)
