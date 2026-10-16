"""Nube en memoria y datos comunes para las pruebas de la recepción."""

from datetime import date, datetime, timedelta

from recepcion.ports import FuenteNoDisponible, LecturaNormalizada, ResultadoToken, Ruta
from sensores.models import Sensor

MAC = "AABBCCDDEEFF"
INICIO = datetime(2026, 10, 1, 0, 5)


def lectura(sensor_id, hora, pm25=12.0):
    return LecturaNormalizada(
        sensor_id=sensor_id,
        hora_local=hora,
        hora_nube=(hora + timedelta(hours=14)).strftime("%Y-%m-%d %H:%M:%S"),
        ruta=Ruta.HISTORIAL,
        crudo="{}",
        intervalo_s=1800,
        pm1_0=None,
        pm2_5=pm25,
        pm4_0=None,
        pm10_0=None,
        co2=None,
        temperatura_sen55=None,
        humedad_sen55=None,
        temperatura_scd40=None,
        humedad_scd40=None,
        voc=None,
        nox=None,
    )


class NubeFalsa:
    """Historial en memoria: `horas` de la más reciente a la más antigua, una lectura cada 30 min.

    `fallas` es la lista de lo que pasa en cada llamada a `historial` antes de responder bien:
    una excepción o None (responde bien).
    """

    def __init__(self, cantidad=10, token="token-1", fallas=None, token_nuevo=None):
        self.horas = [INICIO + timedelta(minutes=30 * i) for i in range(cantidad)][::-1]
        self.token = token
        self.token_nuevo = token_nuevo
        self.fallas = list(fallas or [])
        self.llamadas = []
        self.tokens_pedidos = 0

    def historial(self, sensor, pagina, tamano):
        self.llamadas.append((sensor.token, pagina, tamano))
        if self.fallas:
            falla = self.fallas.pop(0)
            if falla is not None:
                raise falla
        if sensor.token != self.token:
            raise FuenteNoDisponible("la nube respondió code=401", sensor.id, respondio=True)
        inicio = (pagina - 1) * tamano
        return [lectura(sensor.id, h) for h in self.horas[inicio : inicio + tamano]]

    def ultima_lectura(self, sensor):
        raise NotImplementedError

    def obtener_token(self, mac):
        self.tokens_pedidos += 1
        if self.token_nuevo:
            self.token = self.token_nuevo
        return ResultadoToken(token=self.token, apodo=None, ultima=None)


def crear_sensor(cifrador, nombre="S-1", token="token-1", desde=date(2026, 9, 1), **extra):
    return Sensor.objects.create(
        nombre_corto=nombre,
        mac_cifrada=cifrador.cifrar(MAC).decode("ascii"),
        mac_huella=cifrador.huella_mac(MAC) if nombre == "S-1" else nombre.ljust(64, "x"),
        token_cifrado=cifrador.cifrar(token).decode("ascii"),
        lecturas_desde=desde,
        **extra,
    )
