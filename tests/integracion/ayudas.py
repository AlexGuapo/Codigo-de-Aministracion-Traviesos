"""Piezas comunes de las pruebas de integración: sensores, lecturas que entran por el registro
real y sesión del Administrador."""

from datetime import date, datetime, timedelta

from django.urls import reverse

from calculo.services import procesar_cola
from cuentas.services import crear_administrador
from lecturas.services import registrar_lectura
from recepcion.ports import LecturaNormalizada, Ruta
from sensores.models import Sensor

CONTRASENA = "contrasena-de-prueba"
TODO_EL_DIA = tuple(range(24))


def crear_sensor(nombre="S-1", desde=date(2025, 1, 1)):
    return Sensor.objects.create(
        nombre_corto=nombre,
        mac_cifrada="c",
        mac_huella=nombre.ljust(64, "x"),
        token_cifrado="t",
        lecturas_desde=desde,
    )


def llega(sensor, hora, pm25=None, pm10=None, intervalo_s=1800, co2=None):
    """Una lectura que llega de la nube y pasa por `registrar_lectura`, como en operación."""
    return registrar_lectura(
        LecturaNormalizada(
            sensor_id=sensor.pk,
            hora_local=hora,
            hora_nube=(hora + timedelta(hours=14)).strftime("%Y-%m-%d %H:%M:%S"),
            ruta=Ruta.HISTORIAL,
            crudo="{}",
            intervalo_s=intervalo_s,
            pm1_0=None,
            pm2_5=pm25,
            pm4_0=None,
            pm10_0=pm10,
            co2=co2,
            temperatura_sen55=None,
            humedad_sen55=None,
            temperatura_scd40=None,
            humedad_scd40=None,
            voc=None,
            nox=None,
        )
    )


def dia_completo(sensor, dia, pm25, pm10=None, horas=TODO_EL_DIA):
    """Dos lecturas por hora (:05 y :35) en las horas pedidas, más la anterior de las 23:35."""
    inicio = datetime.combine(dia, datetime.min.time())
    llega(sensor, inicio - timedelta(minutes=25), pm25, pm10)
    for hora in horas:
        llega(sensor, inicio + timedelta(hours=hora, minutes=5), pm25, pm10)
        llega(sensor, inicio + timedelta(hours=hora, minutes=35), pm25, pm10)


def calcular(ahora):
    """Vacía la cola de recálculo como lo haría el proceso de fondo."""
    while procesar_cola(ahora=ahora):
        pass


def sesion_de_administrador(client):
    admin = crear_administrador("doctora@ejemplo.mx", "Doctora", CONTRASENA)
    client.post(reverse("cuentas:entrar"), {"correo": admin.correo, "contrasena": CONTRASENA})
    return admin
