"""Consultas a la nube: sondeo, historial diario y conciliación.

Todas las lecturas pasan por `registrar_lectura`. Cada página se guarda en una transacción junto
con el estado de la consulta del sensor, así ese estado nunca dice que se descargó algo que no
quedó guardado.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from django.db import transaction
from django.db.models import F
from django.db.models.functions import Now
from django.utils import timezone

from lecturas.services import Resultado, registrar_lectura
from recepcion.models import ConsultaNube
from recepcion.ports import (
    FuenteDeLecturas,
    FuenteNoDisponible,
    LecturaNormalizada,
    SensorConsultado,
)
from sensores.cifrado import Cifrador
from sensores.models import EstadoSensor, Sensor

logger = logging.getLogger("recepcion")

VARIABLE_FUENTE = "SARRCA_FUENTE"
VARIABLE_FIN_ARCHIVO = "SARRCA_FUENTE_ARCHIVO_FIN"

TAMANO_SONDEO = 5
TAMANO_HISTORIAL = 50
PAGINAS_DIARIAS = 2
PAGINAS_RECORRIDO_COMPLETO = 10

PRESUPUESTO_RONDA_S = 10 * 60
MINIMO_PARA_REINTENTAR_S = 2 * 60
ESPERA_REINTENTO_S = 5

NUEVAS = {Resultado.GUARDADA, Resultado.COPIA_DISCREPANTE}
YA_ESTABAN = {Resultado.REPETIDA, Resultado.COPIA_IDENTICA}


def fuente_configurada() -> FuenteDeLecturas:
    """La nube real, o la muestra en archivo si `SARRCA_FUENTE=archivo` (pruebas y demo).

    Con el archivo, las horas se recorren para que la muestra termine en
    `SARRCA_FUENTE_ARCHIVO_FIN` (fecha y hora local, `2026-10-16T09:00`) o, si no está, en este
    momento. Con la fecha fija, reiniciar el worker no vuelve a guardar la muestra en otras horas.
    """
    if os.environ.get(VARIABLE_FUENTE, "ezdata").strip().lower() == "archivo":
        from recepcion.adapters.archivo import FuenteDeArchivo

        fin = os.environ.get(VARIABLE_FIN_ARCHIVO, "").strip()
        return FuenteDeArchivo(terminar_en=datetime.fromisoformat(fin) if fin else timezone.now())
    from recepcion.adapters.ezdata import FuenteEzData

    return FuenteEzData()


def secreto(cifrador: Cifrador, cifrado: str) -> str:
    return cifrador.descifrar(cifrado.encode("ascii"))


def cifrado(cifrador: Cifrador, texto: str) -> str:
    return cifrador.cifrar(texto).decode("ascii")


@dataclass
class Resumen:
    """Lo que dejó la lectura de un sensor."""

    leidas: int = 0
    nuevas: int = 0
    ya_estaban: int = 0
    fuera_de_fecha: int = 0
    error: str | None = None

    def sumar(self, otro: Resumen) -> None:
        self.leidas += otro.leidas
        self.nuevas += otro.nuevas
        self.ya_estaban += otro.ya_estaban
        self.fuera_de_fecha += otro.fuera_de_fecha


class Presupuesto:
    """Tiempo que le queda a una ronda de consultas."""

    def __init__(self, segundos: float | None, reloj: Callable[[], float] = time.monotonic):
        self._reloj = reloj
        self._limite = None if segundos is None else reloj() + segundos

    def restante(self) -> float:
        if self._limite is None:
            return float("inf")
        return self._limite - self._reloj()

    def agotado(self) -> bool:
        return self.restante() <= 0

    def alcanza_para_reintentar(self) -> bool:
        return self.restante() >= MINIMO_PARA_REINTENTAR_S


def _anotar_exito(sensor_id: int, lecturas: list[LecturaNormalizada]) -> None:
    consulta, _ = ConsultaNube.objects.select_for_update().get_or_create(sensor_id=sensor_id)
    consulta.ultimo_intento_en = consulta.ultimo_exito_en = timezone.now()
    consulta.ultimo_error = None
    consulta.fallas_seguidas = 0
    campos = ["ultimo_intento_en", "ultimo_exito_en", "ultimo_error", "fallas_seguidas"]
    if lecturas:
        mas_reciente = max(lectura.hora_local for lectura in lecturas)
        anterior = consulta.ultima_lectura_descargada_en
        if anterior is None or mas_reciente > anterior:
            consulta.ultima_lectura_descargada_en = mas_reciente
            campos.append("ultima_lectura_descargada_en")
    consulta.save(update_fields=campos)


def _anotar_falla(sensor_id: int, motivo: str) -> None:
    ConsultaNube.objects.get_or_create(sensor_id=sensor_id)
    ConsultaNube.objects.filter(sensor_id=sensor_id).update(
        ultimo_intento_en=timezone.now(),
        ultimo_error=motivo[:300],
        fallas_seguidas=F("fallas_seguidas") + 1,
    )


def anotar_recorrido_completo(sensor_id: int) -> None:
    ConsultaNube.objects.get_or_create(sensor_id=sensor_id)
    ConsultaNube.objects.filter(sensor_id=sensor_id).update(
        ultimo_recorrido_completo_en=timezone.now()
    )


def guardar_pagina(sensor_id: int, lecturas: list[LecturaNormalizada]) -> Resumen:
    resumen = Resumen(leidas=len(lecturas))
    with transaction.atomic():
        for lectura in lecturas:
            resultado = registrar_lectura(lectura).resultado
            if resultado in NUEVAS:
                resumen.nuevas += 1
            elif resultado in YA_ESTABAN:
                resumen.ya_estaban += 1
            else:
                resumen.fuera_de_fecha += 1
        _anotar_exito(sensor_id, lecturas)
    return resumen


class Lector:
    """Lee el historial de un sensor por páginas y guarda lo que traiga.

    Ante una falla reintenta una sola vez por lectura, y solo si el presupuesto lo permite.
    Si la nube contestó con error o sin datos, antes de reintentar pide el token con la MAC:
    si cambió, guarda el nuevo y reintenta con él.
    """

    def __init__(
        self,
        fuente: FuenteDeLecturas,
        cifrador: Cifrador | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._fuente = fuente
        self._cifrador = cifrador or Cifrador.desde_entorno()
        self._dormir = dormir

    def consultado(self, sensor: Sensor) -> SensorConsultado:
        return SensorConsultado(
            id=sensor.pk,
            mac=secreto(self._cifrador, sensor.mac_cifrada),
            token=secreto(self._cifrador, sensor.token_cifrado),
        )

    def leer(
        self,
        sensor: Sensor,
        *,
        paginas: int,
        tamano: int,
        hasta: datetime | None = None,
        presupuesto: Presupuesto | None = None,
    ) -> Resumen:
        """Lee hasta `paginas` páginas, de la más reciente a la más antigua.

        Se detiene antes si una página llega incompleta (ya no hay más) o si su lectura más
        antigua es anterior a `hasta`.
        """
        presupuesto = presupuesto or Presupuesto(None)
        resumen = Resumen()
        consultado = self.consultado(sensor)
        puede_reintentar = True
        for pagina in range(1, paginas + 1):
            try:
                lecturas = self._fuente.historial(consultado, pagina, tamano)
            except FuenteNoDisponible as falla:
                if not (puede_reintentar and presupuesto.alcanza_para_reintentar()):
                    return self._fallo(sensor, falla, resumen)
                puede_reintentar = False
                try:
                    consultado = self._antes_de_reintentar(sensor, consultado, falla)
                    lecturas = self._fuente.historial(consultado, pagina, tamano)
                except FuenteNoDisponible as otra:
                    return self._fallo(sensor, otra, resumen)

            resumen.sumar(guardar_pagina(sensor.pk, lecturas))
            if len(lecturas) < tamano:
                break
            if hasta is not None and min(lectura.hora_local for lectura in lecturas) < hasta:
                break
        return resumen

    def _antes_de_reintentar(
        self, sensor: Sensor, consultado: SensorConsultado, falla: FuenteNoDisponible
    ) -> SensorConsultado:
        if not falla.respondio:
            self._dormir(ESPERA_REINTENTO_S)
            return consultado
        nuevo = self._fuente.obtener_token(consultado.mac).token
        if nuevo != consultado.token:
            Sensor.objects.filter(pk=sensor.pk).update(
                token_cifrado=cifrado(self._cifrador, nuevo), actualizado_en=Now()
            )
            logger.info("Sensor %s: token renovado", sensor.pk)
        return SensorConsultado(id=consultado.id, mac=consultado.mac, token=nuevo)

    @staticmethod
    def _fallo(sensor: Sensor, falla: FuenteNoDisponible, resumen: Resumen) -> Resumen:
        _anotar_falla(sensor.pk, falla.motivo)
        resumen.error = falla.motivo
        return resumen


def inicio_del_dia(fecha: date) -> datetime:
    return datetime.combine(fecha, datetime.min.time())


def sensores_activos() -> list[Sensor]:
    return list(Sensor.objects.filter(estado=EstadoSensor.ACTIVO).order_by("pk"))


def sondear(lector: Lector, presupuesto: Presupuesto | None = None) -> dict[int, Resumen]:
    """Primera página del historial (5 lecturas) de cada sensor activo, uno tras otro.

    Si se acaba el presupuesto de la ronda, los sensores que faltan esperan a la siguiente.
    """
    presupuesto = presupuesto or Presupuesto(PRESUPUESTO_RONDA_S)
    resumenes: dict[int, Resumen] = {}
    for sensor in sensores_activos():
        if presupuesto.agotado():
            logger.warning("Sondeo: se acabó el tiempo de la ronda antes del sensor %s", sensor.pk)
            break
        resumenes[sensor.pk] = lector.leer(
            sensor, paginas=1, tamano=TAMANO_SONDEO, presupuesto=presupuesto
        )
    nuevas = sum(r.nuevas for r in resumenes.values())
    fallas = sum(1 for r in resumenes.values() if r.error)
    logger.info(
        "Sondeo: %d sensores, %d lecturas nuevas, %d con falla", len(resumenes), nuevas, fallas
    )
    return resumenes


def leer_historial_diario(lector: Lector) -> dict[int, Resumen]:
    """Dos páginas de 50 por sensor: lo que el sondeo haya dejado pasar en ~2 días."""
    resumenes = {
        sensor.pk: lector.leer(sensor, paginas=PAGINAS_DIARIAS, tamano=TAMANO_HISTORIAL)
        for sensor in sensores_activos()
    }
    nuevas = sum(r.nuevas for r in resumenes.values())
    logger.info("Historial diario: %d sensores, %d lecturas recuperadas", len(resumenes), nuevas)
    return resumenes


def conciliar(lector: Lector) -> dict[int, Resumen]:
    """Recorre todo lo que conserva la nube de cada sensor y guarda lo que falte.

    Al terminar, cada lectura de la nube desde la fecha del sensor ya está guardada; lo que se
    recuperó es la diferencia que había, y queda en el log.
    """
    resumenes = {}
    for sensor in sensores_activos():
        resumen = lector.leer(
            sensor,
            paginas=PAGINAS_RECORRIDO_COMPLETO,
            tamano=TAMANO_HISTORIAL,
            hasta=inicio_del_dia(sensor.lecturas_desde),
        )
        resumenes[sensor.pk] = resumen
        if resumen.error:
            logger.warning("Conciliación del sensor %s incompleta: %s", sensor.pk, resumen.error)
            continue
        anotar_recorrido_completo(sensor.pk)
        logger.info(
            "Conciliación del sensor %s: %d en la nube, %d ya estaban, %d recuperadas, "
            "%d anteriores a su fecha",
            sensor.pk,
            resumen.leidas,
            resumen.ya_estaban,
            resumen.nuevas,
            resumen.fuera_de_fecha,
        )
    return resumenes
