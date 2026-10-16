"""Permiso por rol en cada vista."""

from __future__ import annotations

import logging
from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden

logger = logging.getLogger("cuentas")

CABECERA_AUTOMATICA = "X-Consulta-Automatica"


def es_consulta_automatica(request) -> bool:
    """Las consultas periódicas de HTMX mandan `X-Consulta-Automatica: 1`.

    Por ejemplo, el estado de la verificación del alta o la actualización del panel. No cuentan
    como actividad de la persona.
    """
    return request.headers.get(CABECERA_AUTOMATICA) == "1"


def rol_requerido(*roles):
    """Deja pasar solo a las cuentas con alguno de esos roles.

    Sin sesión, lleva al inicio de sesión. Con otro rol, responde 403. El servicio que escribe
    vuelve a revisar el rol: esto no lo sustituye.
    """

    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
            if request.user.rol not in roles:
                logger.warning(
                    "Acceso negado a %s para la cuenta %s", request.path, request.user.pk
                )
                return HttpResponseForbidden("No tiene permiso para ver esta página.")
            return vista(request, *args, **kwargs)

        return envoltura

    return decorador
