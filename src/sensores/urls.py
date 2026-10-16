"""Rutas de `sensores`."""

from django.urls import path

from sensores import views

app_name = "sensores"

urlpatterns = [
    path("nuevo/", views.nuevo, name="nuevo"),
    path(
        "verificaciones/<int:pk>/estado/",
        views.estado_verificacion,
        name="estado_verificacion",
    ),
    path("verificaciones/<int:pk>/confirmar/", views.confirmar, name="confirmar"),
]
