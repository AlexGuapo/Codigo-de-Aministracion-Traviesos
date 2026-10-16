from django.urls import path

from cuentas import views

app_name = "cuentas"

urlpatterns = [
    path("entrar/", views.entrar, name="entrar"),
    path("salir/", views.salir, name="salir"),
    path("inicio/", views.inicio, name="inicio"),
]
