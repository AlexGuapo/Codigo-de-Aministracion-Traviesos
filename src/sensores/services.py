"""Alta de sensores desde la web.

La web no habla con la nube: deja una verificación pendiente que atiende el proceso de fondo y,
cuando el Administrador confirma el resumen, guarda todo en una transacción.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from cuentas.models import Cuenta, Estado, Rol
from recepcion.models import ConsultaNube, MotivoRelleno, SolicitudRelleno
from sensores.cifrado import Cifrador
from sensores.models import (
    Colonia,
    EstadoSensor,
    EstadoVerificacion,
    InicioResponsabilidad,
    Responsabilidad,
    Sensor,
    Ubicacion,
    VerificacionSensor,
)

VIGENCIA_VERIFICACION = timedelta(minutes=15)
ESTADOS_ACTIVOS = [EstadoVerificacion.PENDIENTE, EstadoVerificacion.EN_CURSO]


class AltaRechazada(Exception):
    """El alta no se puede guardar; el mensaje se muestra tal cual al Administrador."""


def responsables_disponibles():
    """Vecinos sin sensor que pueden recibir uno: con la cuenta vigente y sin sensor a su cargo."""
    con_sensor = Responsabilidad.objects.filter(vigente_hasta__isnull=True).values("cuenta_id")
    return (
        Cuenta.objects.filter(
            rol=Rol.VECINO_SIN_SENSOR, estado__in=[Estado.POR_VALIDAR, Estado.VALIDADA]
        )
        .exclude(pk__in=con_sensor)
        .select_related("colonia")
        .order_by("nombre")
    )


def inicio_del_dia(fecha: date) -> datetime:
    return datetime.combine(fecha, time.min)


def _revisar_administrador(cuenta: Cuenta) -> None:
    if not cuenta.es_administrador:
        raise AltaRechazada("Solo el Administrador registra sensores.")


def solicitar_verificacion(
    *,
    mac: str,
    datos: dict,
    sensor_existente: Sensor | None,
    administrador: Cuenta,
    cifrador: Cifrador | None = None,
) -> VerificacionSensor:
    """Deja la MAC lista para que el proceso de fondo la compruebe con la nube.

    Si ya hay una verificación en curso de esa MAC (un segundo clic), se reutiliza.
    """
    _revisar_administrador(administrador)
    cifrador = cifrador or Cifrador.desde_entorno()
    huella = cifrador.huella_mac(mac)
    activa = VerificacionSensor.objects.filter(mac_huella=huella, estado__in=ESTADOS_ACTIVOS)
    if (existente := activa.first()) is not None:
        return existente
    try:
        with transaction.atomic():
            return VerificacionSensor.objects.create(
                mac_cifrada=cifrador.cifrar(mac).decode("ascii"),
                mac_huella=huella,
                datos_alta=datos,
                sensor_existente=sensor_existente,
                solicitada_por=administrador,
            )
    except IntegrityError:
        return activa.get()


def vencida(verificacion: VerificacionSensor, ahora: datetime | None = None) -> bool:
    ahora = ahora or timezone.now()
    return (
        verificacion.estado == EstadoVerificacion.LISTA
        and verificacion.terminada_en is not None
        and verificacion.terminada_en < ahora - VIGENCIA_VERIFICACION
    )


def _ultimo_fin(consulta) -> datetime | None:
    return consulta.aggregate(fin=Max("vigente_hasta"))["fin"]


def _desde_sin_traslape(inicio: datetime, *periodos) -> datetime:
    """El inicio pedido, o el final del último periodo anterior si este lo alcanza."""
    fines = [fin for fin in (_ultimo_fin(p) for p in periodos) if fin is not None]
    return max([inicio, *fines])


def _revisar_datos(verificacion: VerificacionSensor, datos: dict) -> tuple[Cuenta, Colonia]:
    existente = verificacion.sensor_existente
    activo = Sensor.objects.filter(mac_huella=verificacion.mac_huella, estado=EstadoSensor.ACTIVO)
    if (sensor := activo.first()) is not None:
        raise AltaRechazada(f"Esa MAC ya pertenece al sensor {sensor.nombre_corto}.")

    repetido = Sensor.objects.filter(nombre_corto__iexact=datos["nombre_corto"])
    if existente is not None:
        repetido = repetido.exclude(pk=existente.pk)
    if repetido.exists():
        raise AltaRechazada("Ya hay un sensor con ese nombre corto.")

    responsable = Cuenta.objects.select_for_update().filter(pk=datos["responsable_id"]).first()
    if responsable is None or not responsables_disponibles().filter(pk=responsable.pk).exists():
        raise AltaRechazada("El responsable ya tiene un sensor o su cuenta no está vigente.")

    colonia = Colonia.objects.filter(pk=datos["colonia_id"], activa=True).first()
    if colonia is None:
        raise AltaRechazada("La colonia ya no está en el catálogo.")
    return responsable, colonia


def confirmar_alta(
    verificacion_id: int, administrador: Cuenta, ahora: datetime | None = None
) -> Sensor:
    """Guarda el alta que el Administrador confirmó, todo o nada.

    En una transacción: el sensor activo (o el dado de baja, reactivado con su historial), su
    ubicación y su responsable desde las 00:00 de la fecha elegida, la cuenta del responsable
    como Vecino con sensor (validada si estaba por validar), su estado de consulta a la nube y la
    solicitud de traer sus lecturas desde esa fecha.
    """
    _revisar_administrador(administrador)
    ahora = ahora or timezone.now()
    VerificacionSensor.objects.filter(
        pk=verificacion_id,
        estado=EstadoVerificacion.LISTA,
        terminada_en__lt=ahora - VIGENCIA_VERIFICACION,
    ).update(estado=EstadoVerificacion.VENCIDA)
    with transaction.atomic():
        verificacion = (
            VerificacionSensor.objects.select_for_update(of=("self",))
            .select_related("sensor_existente")
            .get(pk=verificacion_id)
        )
        if verificacion.estado == EstadoVerificacion.VENCIDA:
            raise AltaRechazada(
                "La verificación venció: pasaron más de 15 minutos sin confirmar. "
                "Vuelva a registrar el sensor."
            )
        if verificacion.estado != EstadoVerificacion.LISTA:
            raise AltaRechazada("Esta verificación ya no se puede confirmar.")

        datos = verificacion.datos_alta
        responsable, colonia = _revisar_datos(verificacion, datos)
        lecturas_desde = date.fromisoformat(datos["lecturas_desde"])
        sensor = verificacion.sensor_existente
        reactivacion = sensor is not None

        if reactivacion:
            sensor = Sensor.objects.select_for_update().get(pk=sensor.pk)
            sensor.estado = EstadoSensor.ACTIVO
            sensor.dado_de_baja_en = None
            sensor.token_cifrado = verificacion.token_cifrado
            sensor.apodo_cifrado = verificacion.apodo_cifrado
            sensor.lecturas_desde = min(sensor.lecturas_desde, lecturas_desde)
            sensor.actualizado_en = ahora
            sensor.save(
                update_fields=[
                    "estado",
                    "dado_de_baja_en",
                    "token_cifrado",
                    "apodo_cifrado",
                    "lecturas_desde",
                    "actualizado_en",
                ]
            )
            for abiertos in (sensor.ubicaciones, sensor.responsabilidades):
                abiertos.filter(vigente_hasta__isnull=True).update(vigente_hasta=ahora)
        else:
            sensor = Sensor.objects.create(
                nombre_corto=datos["nombre_corto"],
                mac_cifrada=verificacion.mac_cifrada,
                mac_huella=verificacion.mac_huella,
                token_cifrado=verificacion.token_cifrado,
                apodo_cifrado=verificacion.apodo_cifrado,
                lecturas_desde=lecturas_desde,
            )

        inicio = inicio_del_dia(lecturas_desde)
        Ubicacion.objects.create(
            sensor=sensor,
            colonia=colonia,
            direccion=datos["direccion"],
            latitud=Decimal(datos["latitud"]),
            longitud=Decimal(datos["longitud"]),
            vigente_desde=_desde_sin_traslape(inicio, sensor.ubicaciones.all()),
            registrada_por=administrador,
        )
        Responsabilidad.objects.create(
            sensor=sensor,
            cuenta=responsable,
            inicio=(
                InicioResponsabilidad.REACTIVACION if reactivacion else InicioResponsabilidad.ALTA
            ),
            vigente_desde=_desde_sin_traslape(
                inicio,
                sensor.responsabilidades.all(),
                Responsabilidad.objects.filter(cuenta=responsable),
            ),
            registrada_por=administrador,
        )

        responsable.rol = Rol.VECINO_CON_SENSOR
        if responsable.estado == Estado.POR_VALIDAR:
            responsable.estado = Estado.VALIDADA
        responsable.actualizada_en = ahora
        responsable.save(update_fields=["rol", "estado", "actualizada_en"])

        ConsultaNube.objects.get_or_create(sensor=sensor)
        SolicitudRelleno.objects.create(
            sensor=sensor,
            desde=inicio,
            motivo=MotivoRelleno.REACTIVACION if reactivacion else MotivoRelleno.ALTA,
            solicitada_por=administrador,
        )

        verificacion.estado = EstadoVerificacion.CONFIRMADA
        verificacion.sensor = sensor
        verificacion.save(update_fields=["estado", "sensor"])
    return sensor
