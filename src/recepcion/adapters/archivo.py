"""Fuente de lecturas que lee un archivo en lugar de la nube.

Se usa en las pruebas de integración y en la demo cuando un sensor real no transmite. Lee la
muestra anonimizada del historial de un sensor (`tests/datos/muestra_S1_anonimizada.json`) y la
entrega igual que lo haría la nube: por páginas, de la más reciente a la más antigua, con la
hora en UTC+8 y el valor pasado por la misma interpretación que usa el adaptador de EzData.

Con `terminar_en` las horas se recorren para que la lectura más reciente caiga en ese momento;
así la muestra parece de hoy.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from lecturas.interpretacion import CAMPOS, crudo_de, interpretar_valor
from recepcion.adapters.ezdata import ZONA_LOCAL, ZONA_NUBE, a_hora_local
from recepcion.ports import (
    FuenteNoDisponible,
    LecturaNormalizada,
    ResultadoToken,
    Ruta,
    SensorConsultado,
)

MUESTRA = Path(__file__).resolve().parents[3] / "tests" / "datos" / "muestra_S1_anonimizada.json"
FORMATO_HORA_NUBE = "%Y-%m-%d %H:%M:%S"
TOKEN_DE_ARCHIVO = "archivo"


def _valor_del_sensor(registro: dict[str, Any]) -> dict[str, Any]:
    """Arma el objeto `value` como lo manda el firmware, a partir de un registro de la muestra."""
    valor: dict[str, Any] = {"sen55": {}, "scd40": {}}
    for campo, (bloque, clave) in CAMPOS.items():
        valor[bloque][clave] = registro["variables"].get(campo)
    if registro.get("sleep_interval_s") is not None:
        valor["rtc"] = {"sleep_interval": registro["sleep_interval_s"]}
    return valor


class FuenteDeArchivo:
    """Implementa `FuenteDeLecturas` con los registros de un archivo de muestra."""

    def __init__(self, ruta: Path = MUESTRA, terminar_en: datetime | None = None) -> None:
        try:
            datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
            registros = datos["registros"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise FuenteNoDisponible(
                f"no se pudo leer la muestra: {type(error).__name__}"
            ) from None

        horas = [datetime.strptime(r["hora_nube_utc8"], FORMATO_HORA_NUBE) for r in registros]
        desplazamiento = timedelta(0)
        if terminar_en is not None and horas:
            ultima_local = (
                max(horas).replace(tzinfo=ZONA_NUBE).astimezone(ZONA_LOCAL).replace(tzinfo=None)
            )
            desplazamiento = terminar_en - ultima_local

        filas = []
        for registro, hora in zip(registros, horas, strict=True):
            hora_nube = (hora + desplazamiento).strftime(FORMATO_HORA_NUBE)
            filas.append((hora_nube, _valor_del_sensor(registro)))
        # La nube entrega primero lo más reciente.
        filas.sort(key=lambda fila: fila[0], reverse=True)
        self._filas = filas

    def historial(
        self, sensor: SensorConsultado, pagina: int, tamano: int
    ) -> list[LecturaNormalizada]:
        if pagina < 1 or tamano < 1:
            raise ValueError("pagina y tamano deben ser 1 o más")
        inicio = (pagina - 1) * tamano
        return [
            self._a_lectura(hora, valor, Ruta.HISTORIAL, sensor.id)
            for hora, valor in self._filas[inicio : inicio + tamano]
        ]

    def ultima_lectura(self, sensor: SensorConsultado) -> LecturaNormalizada:
        if not self._filas:
            raise FuenteNoDisponible("la muestra no tiene lecturas", sensor.id)
        hora, valor = self._filas[0]
        return self._a_lectura(hora, valor, Ruta.HISTORIAL, sensor.id)

    def obtener_token(self, mac: str) -> ResultadoToken:
        ultima = None
        if self._filas:
            hora, valor = self._filas[0]
            ultima = self._a_lectura(hora, valor, Ruta.HISTORIAL, 0)
        return ResultadoToken(token=TOKEN_DE_ARCHIVO, apodo=None, ultima=ultima)

    @staticmethod
    def _a_lectura(
        hora_nube: str, valor: dict[str, Any], ruta: Ruta, sensor_id: int
    ) -> LecturaNormalizada:
        interpretado = interpretar_valor(valor)
        return LecturaNormalizada(
            sensor_id=sensor_id,
            hora_local=a_hora_local(hora_nube),
            hora_nube=hora_nube,
            ruta=ruta,
            crudo=crudo_de(valor),
            intervalo_s=interpretado.intervalo_s,
            pm1_0=interpretado.pm1_0,
            pm2_5=interpretado.pm2_5,
            pm4_0=interpretado.pm4_0,
            pm10_0=interpretado.pm10_0,
            co2=interpretado.co2,
            temperatura_sen55=interpretado.temperatura_sen55,
            humedad_sen55=interpretado.humedad_sen55,
            temperatura_scd40=interpretado.temperatura_scd40,
            humedad_scd40=interpretado.humedad_scd40,
            voc=interpretado.voc,
            nox=interpretado.nox,
        )
