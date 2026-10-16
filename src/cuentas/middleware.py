import time

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect

from cuentas.permisos import es_consulta_automatica
from cuentas.services import CLAVE_ULTIMA_ACTIVIDAD, cerrar_sesion


class SesionPorInactividad:
    """Cierra la sesión tras `SARRCA_INACTIVIDAD_MAX_SEG` sin actividad.

    Las consultas automáticas de HTMX no cuentan como actividad: si contaran, una pestaña abierta
    mantendría viva la sesión para siempre. A una petición de HTMX con la sesión vencida se le
    responde con `HX-Redirect`, para que la página completa vaya al inicio de sesión.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            ahora = time.time()
            ultima = request.session.get(CLAVE_ULTIMA_ACTIVIDAD)
            if ultima is None or ahora - ultima > settings.SARRCA_INACTIVIDAD_MAX_SEG:
                cerrar_sesion(request, expirada=True)
                if request.headers.get("HX-Request"):
                    return HttpResponse(status=401, headers={"HX-Redirect": settings.LOGIN_URL})
                return redirect(settings.LOGIN_URL)
            if not es_consulta_automatica(request):
                request.session[CLAVE_ULTIMA_ACTIVIDAD] = ahora
        return self.get_response(request)
