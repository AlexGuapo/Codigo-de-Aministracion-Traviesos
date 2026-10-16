"""Adaptador de la nube EzData de M5Stack.

Es el único lugar del sistema que sabe cómo responde EzData. Reglas:

- Solo dos consultas GET: `{MAC}/dataMacByKey/raw` y `{token}/history`.
  Cualquier otra ruta se rechaza antes de conectarse.
- 45 s de espera por consulta, sin reintentos (los decide la ronda que llama).
- `code` distinto de 200 es falla aunque el HTTP haya sido 200.
- La hora de la lectura es `updateTime` (texto en hora de China o segundos
  Unix); `createTime` es el alta del sensor y se ignora.
- Ningún error ni log lleva la URL, la MAC ni el token.
"""

from __future__ import annotations

import http.client
import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, NoReturn
from zoneinfo import ZoneInfo

from lecturas.interpretacion import FormatoNoReconocido, crudo_de, interpretar_valor
from recepcion.ports import (
    FuenteNoDisponible,
    LecturaNormalizada,
    ResultadoToken,
    Ruta,
    SensorConsultado,
)

logger = logging.getLogger("recepcion.ezdata")

URL_OFICIAL = "https://ezdata2.m5stack.com/api/v2"
TIEMPO_ESPERA_S = 45.0

ZONA_NUBE = ZoneInfo("Asia/Shanghai")  # UTC+8
ZONA_LOCAL = ZoneInfo("America/Mexico_City")

RUTAS_PERMITIDAS = (
    re.compile(r"^[0-9A-F]{12}/dataMacByKey/raw$"),
    re.compile(r"^[0-9A-Za-z]{8,64}/history$"),
)
MAC_NORMALIZADA = re.compile(r"^[0-9A-F]{12}$")
UNIX = re.compile(r"^\d{9,14}(\.\d+)?$")
FORMATOS_HORA = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S")

SIN_DATOS = "la nube respondió sin datos"

# (url, segundos de espera) -> cuerpo de la respuesta
Obtener = Callable[[str, float], bytes]


def _obtener_con_urllib(url: str, espera: float) -> bytes:
    peticion = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "SARRCA"},
    )
    with urllib.request.urlopen(peticion, timeout=espera) as respuesta:
        return respuesta.read()


def a_hora_local(valor: Any) -> datetime | None:
    """Hora de EzData -> hora local de Zacatecas, sin zona.

    Texto 'AAAA-MM-DD hh:mm:ss' = hora de China. Número = segundos Unix
    (milisegundos si es muy grande).
    """
    if valor is None or isinstance(valor, bool):
        return None
    try:
        if isinstance(valor, (int, float)) or (
            isinstance(valor, str) and UNIX.match(valor.strip())
        ):
            segundos = float(valor)
            if segundos > 1e12:
                segundos /= 1000
            momento = datetime.fromtimestamp(segundos, tz=UTC)
        elif isinstance(valor, str):
            momento = None
            for formato in FORMATOS_HORA:
                try:
                    momento = datetime.strptime(valor.strip(), formato).replace(
                        tzinfo=ZONA_NUBE
                    )
                    break
                except ValueError:
                    continue
            if momento is None:
                return None
        else:
            return None
    except (OverflowError, OSError, ValueError):
        return None
    return momento.astimezone(ZONA_LOCAL).replace(tzinfo=None)


class FuenteEzData:
    """Implementa `FuenteDeLecturas` contra la nube real."""

    def __init__(
        self,
        base_url: str = URL_OFICIAL,
        espera_s: float = TIEMPO_ESPERA_S,
        obtener: Obtener | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._espera = espera_s
        self._obtener = obtener or _obtener_con_urllib

    # -- operaciones del puerto ---------------------------------------------

    def historial(
        self, sensor: SensorConsultado, pagina: int, tamano: int
    ) -> list[LecturaNormalizada]:
        if pagina < 1 or tamano < 1:
            raise ValueError("pagina y tamano deben ser 1 o más")
        datos = self._consultar(
            f"{sensor.token}/history",
            f"pageSize={tamano}&pageNum={pagina}",
            "historial",
            sensor.id,
        )
        filas = datos.get("rows") if isinstance(datos, dict) else None
        if not isinstance(filas, list):
            self._fallar("respuesta inesperada", "historial", sensor.id, respondio=True)
        lecturas = []
        for fila in filas:
            lectura = self._fila_a_lectura(fila, Ruta.HISTORIAL, sensor.id)
            if lectura is not None:
                lecturas.append(lectura)
        return lecturas

    def ultima_lectura(self, sensor: SensorConsultado) -> LecturaNormalizada:
        datos = self._consultar(
            f"{sensor.mac}/dataMacByKey/raw", None, "ultima", sensor.id
        )
        lectura = self._fila_a_lectura(datos, Ruta.ULTIMA, sensor.id)
        if lectura is None:
            self._fallar(
                "la última lectura no se pudo interpretar", "ultima", sensor.id
            )
        return lectura

    def obtener_token(self, mac: str) -> ResultadoToken:
        if not MAC_NORMALIZADA.match(mac):
            raise ValueError(
                "la MAC debe venir normalizada (12 hexadecimales en mayúsculas)"
            )
        datos = self._consultar(f"{mac}/dataMacByKey/raw", None, "token", None)
        token = datos.get("dataToken") if isinstance(datos, dict) else None
        if not isinstance(token, str) or not token:
            self._fallar("la nube no devolvió el token", "token", None, respondio=True)

        apodo = None
        try:
            apodo = interpretar_valor(datos.get("value")).apodo
        except FormatoNoReconocido:
            pass
        ultima = self._fila_a_lectura(datos, Ruta.ULTIMA, None)
        return ResultadoToken(token=token, apodo=apodo, ultima=ultima)

    # -- internos -----------------------------------------------------------

    def _consultar(
        self, ruta: str, consulta: str | None, nombre: str, sensor_id: int | None
    ) -> Any:
        """GET a una ruta permitida; regresa el campo `data` de la respuesta."""
        if not any(p.match(ruta) for p in RUTAS_PERMITIDAS):
            # error de programación, no de la nube; no se dice cuál ruta (lleva secretos)
            raise ValueError("ruta de EzData no permitida")
        url = f"{self._base}/{ruta}" + (f"?{consulta}" if consulta else "")

        inicio = time.monotonic()
        motivo = None
        try:
            cuerpo = self._obtener(url, self._espera)
        except urllib.error.HTTPError as e:
            motivo = f"error HTTP {e.code}"
        except urllib.error.URLError as e:
            motivo = (
                "tiempo de espera agotado"
                if isinstance(e.reason, TimeoutError)
                else "sin conexión con la nube"
            )
        except TimeoutError:
            motivo = "tiempo de espera agotado"
        except (OSError, http.client.HTTPException):
            motivo = "sin conexión con la nube"
        # se lanza fuera del except para no arrastrar la excepción original,
        # que puede traer la URL
        if motivo:
            self._fallar(motivo, nombre, sensor_id)

        try:
            respuesta = json.loads(cuerpo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            respuesta = None
        if not isinstance(respuesta, dict):
            self._fallar("la respuesta no es JSON", nombre, sensor_id)
        if respuesta.get("code") != 200:
            self._fallar(
                f"la nube respondió code={respuesta.get('code')}",
                nombre,
                sensor_id,
                respondio=True,
            )
        if respuesta.get("data") is None:
            self._fallar(SIN_DATOS, nombre, sensor_id, respondio=True)

        logger.debug(
            "sensor %s: %s en %.1f s", sensor_id, nombre, time.monotonic() - inicio
        )
        return respuesta["data"]

    def _fallar(
        self, motivo: str, nombre: str, sensor_id: int | None, *, respondio: bool = False
    ) -> NoReturn:
        logger.warning("sensor %s: %s falló: %s", sensor_id, nombre, motivo)
        raise FuenteNoDisponible(motivo, sensor_id, respondio=respondio)

    def _fila_a_lectura(
        self, fila: Any, ruta: Ruta, sensor_id: int | None
    ) -> LecturaNormalizada | None:
        """Una fila de EzData -> LecturaNormalizada, o None si no se puede leer.

        Una fila rara no tumba la página: se salta y queda el aviso en el log.
        """
        if not isinstance(fila, dict):
            logger.warning(
                "sensor %s: fila de %s que no es objeto, se salta", sensor_id, ruta
            )
            return None
        hora_nube = fila.get("updateTime")
        hora_local = a_hora_local(hora_nube)
        if hora_local is None:
            logger.warning(
                "sensor %s: fila de %s con hora no reconocida (%r), se salta",
                sensor_id,
                ruta,
                hora_nube,
            )
            return None
        value = fila.get("value")
        try:
            valor = interpretar_valor(value)
        except FormatoNoReconocido as e:
            logger.warning(
                "sensor %s: fila de %s del %s sin interpretar (%s), se salta",
                sensor_id,
                ruta,
                hora_nube,
                e,
            )
            return None

        return LecturaNormalizada(
            sensor_id=sensor_id if sensor_id is not None else 0,
            hora_local=hora_local,
            hora_nube=str(hora_nube),
            ruta=ruta,
            crudo=crudo_de(value),
            intervalo_s=valor.intervalo_s,
            pm1_0=valor.pm1_0,
            pm2_5=valor.pm2_5,
            pm4_0=valor.pm4_0,
            pm10_0=valor.pm10_0,
            co2=valor.co2,
            temperatura_sen55=valor.temperatura_sen55,
            humedad_sen55=valor.humedad_sen55,
            temperatura_scd40=valor.temperatura_scd40,
            humedad_scd40=valor.humedad_scd40,
            voc=valor.voc,
            nox=valor.nox,
        )
