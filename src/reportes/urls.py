"""Rutas del panel de la red y de los reportes diario y mensual."""

from django.urls import path

from reportes.views import diario, mensual, panel

app_name = "reportes"

urlpatterns = [
    path("", panel.panel_red, name="panel_red"),
    path("reportes/diario/", diario.reporte_diario, name="diario"),
    path("reportes/mensual/", mensual.reporte_mensual, name="mensual"),
    path("reportes/mensual/lamina/", mensual.lamina, name="lamina"),
]
