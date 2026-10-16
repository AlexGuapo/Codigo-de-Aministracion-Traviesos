from datetime import date, timedelta
from decimal import Decimal

from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from cuentas.models import Cuenta, Rol
from cuentas.permisos import rol_requerido
from sensores.forms import AltaSensorForm
from sensores.models import Colonia, EstadoVerificacion, VerificacionSensor
from sensores.services import (
    AltaRechazada,
    confirmar_alta,
    inicio_del_dia,
    solicitar_verificacion,
    vencida,
)
from sensores.validaciones import fuera_de_la_zona

# Si en este tiempo nadie toma la verificación, el proceso de fondo no está corriendo.
ESPERA_DEL_PROCESO_DE_FONDO = timedelta(seconds=60)
TERMINADA_HTMX = 286  # HTMX deja de consultar al recibir este código

EN_ESPERA = (EstadoVerificacion.PENDIENTE, EstadoVerificacion.EN_CURSO)


@rol_requerido(Rol.ADMINISTRADOR)
@require_http_methods(["GET", "POST"])
def nuevo(request):
    formulario = AltaSensorForm(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        try:
            verificacion = solicitar_verificacion(
                mac=formulario.cleaned_data["mac"],
                datos=formulario.datos_alta(),
                sensor_existente=formulario.sensor_existente,
                administrador=request.user,
            )
        except AltaRechazada as error:
            formulario.add_error(None, str(error))
        else:
            return redirect("sensores:estado_verificacion", pk=verificacion.pk)
    return render(request, "sensores/nuevo.html", {"formulario": formulario, "seccion": "sensores"})


def _contexto(verificacion: VerificacionSensor) -> dict:
    datos = verificacion.datos_alta
    ahora = timezone.now()
    desde = inicio_del_dia(date.fromisoformat(datos["lecturas_desde"]))
    sin_atender = (
        verificacion.estado == EstadoVerificacion.PENDIENTE
        and verificacion.solicitada_en < ahora - ESPERA_DEL_PROCESO_DE_FONDO
    )
    return {
        "verificacion": verificacion,
        "datos": datos,
        "en_espera": verificacion.estado in EN_ESPERA and not sin_atender,
        "sin_atender": sin_atender,
        "vencida": vencida(verificacion, ahora)
        or verificacion.estado == EstadoVerificacion.VENCIDA,
        "colonia": Colonia.objects.filter(pk=datos["colonia_id"]).first(),
        "responsable": Cuenta.objects.filter(pk=datos["responsable_id"]).first(),
        "lecturas_desde": desde,
        "nube_empieza_despues": verificacion.nube_conserva_desde is not None
        and verificacion.nube_conserva_desde > desde,
        "fuera_de_zona": fuera_de_la_zona(
            float(Decimal(datos["latitud"])), float(Decimal(datos["longitud"]))
        ),
        "ultima": verificacion.ultima_lectura_resumen or {},
        "seccion": "sensores",
    }


@rol_requerido(Rol.ADMINISTRADOR)
@require_GET
def estado_verificacion(request, pk):
    """La página de la verificación; con HTMX, solo el bloque del estado.

    Mientras el proceso de fondo trabaja, la pantalla pide este bloque cada 2 s. Al terminar
    responde 286 para que HTMX deje de pedirlo.
    """
    verificacion = get_object_or_404(VerificacionSensor, pk=pk)
    contexto = _contexto(verificacion)
    if request.headers.get("HX-Request") == "true":
        estado = 200 if contexto["en_espera"] else TERMINADA_HTMX
        return render(request, "sensores/_estado_verificacion.html", contexto, status=estado)
    return render(request, "sensores/verificacion.html", contexto)


@rol_requerido(Rol.ADMINISTRADOR)
@require_POST
def confirmar(request, pk):
    verificacion = get_object_or_404(VerificacionSensor, pk=pk)
    try:
        confirmar_alta(verificacion.pk, request.user)
    except AltaRechazada as error:
        verificacion.refresh_from_db()
        contexto = _contexto(verificacion) | {"error": str(error)}
        return render(request, "sensores/verificacion.html", contexto, status=409)
    return redirect("sensores:estado_verificacion", pk=verificacion.pk)
