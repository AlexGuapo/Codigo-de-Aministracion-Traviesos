"""Rutas de SARRCA. Cada app declara las suyas en su `urls.py`."""

from django.urls import include, path

urlpatterns = [
    path("cuentas/", include("cuentas.urls")),
    path("sensores/", include("sensores.urls")),
    # Panel de la red (`/`) y reportes diario y mensual
    path("", include("reportes.urls")),
]
