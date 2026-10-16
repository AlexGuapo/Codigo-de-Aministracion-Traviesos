from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from cuentas.forms import AccesoForm
from cuentas.services import ResultadoAcceso, cerrar_sesion, destino_inicial, iniciar_sesion

# El mismo mensaje para un correo que no existe, una contraseña mala y una cuenta que no puede
# entrar: así no se revela qué correos están registrados.
MENSAJE_DATOS_INCORRECTOS = "Correo o contraseña incorrectos."
MENSAJE_PAUSA = (
    f"Demasiados intentos. Espere {settings.SARRCA_PAUSA_ACCESO_MIN} minutos "
    "para volver a intentar."
)


def _siguiente_seguro(request) -> str | None:
    siguiente = request.POST.get("next") or request.GET.get("next")
    if siguiente and url_has_allowed_host_and_scheme(
        siguiente, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return siguiente
    return None


@require_http_methods(["GET", "POST"])
def entrar(request):
    if request.user.is_authenticated:
        return redirect(destino_inicial(request.user))

    mensaje = None
    formulario = AccesoForm(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        resultado, cuenta = iniciar_sesion(
            request, formulario.cleaned_data["correo"], formulario.cleaned_data["contrasena"]
        )
        if resultado == ResultadoAcceso.ENTRO:
            return redirect(_siguiente_seguro(request) or destino_inicial(cuenta))
        mensaje = (
            MENSAJE_PAUSA if resultado == ResultadoAcceso.PAUSADO else MENSAJE_DATOS_INCORRECTOS
        )
        # La contraseña nunca se devuelve en el formulario.
        formulario = AccesoForm(initial={"correo": formulario.cleaned_data["correo"]})

    estado = 429 if mensaje == MENSAJE_PAUSA else 200
    contexto = {
        "formulario": formulario,
        "mensaje": mensaje,
        "siguiente": request.GET.get("next", ""),
    }
    return render(request, "cuentas/entrar.html", contexto, status=estado)


@require_POST
def salir(request):
    if request.user.is_authenticated:
        cerrar_sesion(request)
    return redirect("cuentas:entrar")


@login_required
def inicio(request):
    """Página inicial de los vecinos. En el MVP todavía no tiene funciones."""
    return render(request, "cuentas/inicio.html")
