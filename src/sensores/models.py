from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.db import models
from django.db.models import Func, Q
from django.db.models.functions import Length, Now, Upper

models.CharField.register_lookup(Length)


class TsTzRange(Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


def _sin_traslape(nombre, campo):
    """Impide que dos periodos [desde, hasta) del mismo `campo` se encimen."""
    return ExclusionConstraint(
        name=nombre,
        expressions=[
            (campo, RangeOperators.EQUAL),
            (TsTzRange("vigente_desde", "vigente_hasta", RangeBoundary()), RangeOperators.OVERLAPS),
        ],
    )


class Municipio(models.TextChoices):
    ZACATECAS = "Zacatecas", "Zacatecas"
    GUADALUPE = "Guadalupe", "Guadalupe"


class Colonia(models.Model):
    """Catálogo cerrado de colonias. El punto de referencia es un lugar público, nunca una casa."""

    nombre = models.CharField(max_length=80)
    municipio = models.CharField(max_length=20, choices=Municipio.choices)
    latitud_ref = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud_ref = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    activa = models.BooleanField(db_default=True)
    creada_en = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "colonia"
        ordering = ["municipio", "nombre"]
        constraints = [
            models.CheckConstraint(
                condition=Q(municipio__in=Municipio.values), name="colonia_municipio_ck"
            ),
            models.CheckConstraint(
                condition=Q(latitud_ref__range=(-90, 90)), name="colonia_latitud_ck"
            ),
            models.CheckConstraint(
                condition=Q(longitud_ref__range=(-180, 180)), name="colonia_longitud_ck"
            ),
            models.UniqueConstraint(
                fields=["municipio", "nombre"], name="colonia_nombre_municipio_uq"
            ),
            models.CheckConstraint(
                condition=Q(latitud_ref__isnull=True, longitud_ref__isnull=True)
                | Q(latitud_ref__isnull=False, longitud_ref__isnull=False),
                name="colonia_punto_completo_ck",
            ),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.municipio})"


class EstadoSensor(models.TextChoices):
    ACTIVO = "activo", "Activo"
    DADO_DE_BAJA = "dado_de_baja", "Dado de baja"


class Sensor(models.Model):
    """Un sensor de la red. La MAC, el token y el apodo van cifrados.

    `mac_huella` permite saber si una MAC ya está registrada sin descifrar ninguna.
    """

    nombre_corto = models.CharField(max_length=10)
    mac_cifrada = models.TextField()
    mac_huella = models.CharField(max_length=64, unique=True)
    token_cifrado = models.TextField()
    apodo_cifrado = models.TextField(null=True, blank=True)
    estado = models.CharField(
        max_length=15, choices=EstadoSensor.choices, db_default=EstadoSensor.ACTIVO
    )
    lecturas_desde = models.DateField()
    dado_de_alta_en = models.DateTimeField(db_default=Now())
    dado_de_baja_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(db_default=Now())
    actualizado_en = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "sensor"
        constraints = [
            models.CheckConstraint(
                condition=Q(nombre_corto__length__range=(2, 10)), name="sensor_nombre_corto_ck"
            ),
            models.CheckConstraint(
                condition=Q(estado__in=EstadoSensor.values), name="sensor_estado_ck"
            ),
            models.CheckConstraint(
                condition=Q(estado=EstadoSensor.DADO_DE_BAJA, dado_de_baja_en__isnull=False)
                | (~Q(estado=EstadoSensor.DADO_DE_BAJA) & Q(dado_de_baja_en__isnull=True)),
                name="sensor_baja_ck",
            ),
            models.UniqueConstraint(Upper("nombre_corto"), name="sensor_nombre_corto_uq"),
        ]

    def __str__(self):
        return self.nombre_corto


class Ubicacion(models.Model):
    """Dónde estuvo un sensor durante [vigente_desde, vigente_hasta).

    La colonia de una lectura se busca por esta vigencia, con la hora de la lectura.
    """

    sensor = models.ForeignKey(Sensor, on_delete=models.PROTECT, related_name="ubicaciones")
    colonia = models.ForeignKey(Colonia, on_delete=models.PROTECT, related_name="ubicaciones")
    direccion = models.CharField(max_length=250, null=True, blank=True)
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    vigente_desde = models.DateTimeField()
    vigente_hasta = models.DateTimeField(null=True, blank=True)
    registrada_por = models.ForeignKey(
        "cuentas.Cuenta", on_delete=models.PROTECT, related_name="ubicaciones_registradas"
    )
    creada_en = models.DateTimeField(db_default=Now())
    actualizada_en = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "ubicacion"
        constraints = [
            models.CheckConstraint(
                condition=Q(latitud__range=(-90, 90)), name="ubicacion_latitud_ck"
            ),
            models.CheckConstraint(
                condition=Q(longitud__range=(-180, 180)), name="ubicacion_longitud_ck"
            ),
            models.CheckConstraint(
                condition=Q(latitud__isnull=True, longitud__isnull=True)
                | Q(latitud__isnull=False, longitud__isnull=False),
                name="ubicacion_coordenadas_ck",
            ),
            models.CheckConstraint(
                condition=Q(vigente_hasta__isnull=True)
                | Q(vigente_hasta__gt=models.F("vigente_desde")),
                name="ubicacion_periodo_ck",
            ),
            _sin_traslape("ubicacion_sin_traslape_ex", "sensor"),
            models.UniqueConstraint(
                fields=["sensor"],
                condition=Q(vigente_hasta__isnull=True),
                name="ubicacion_una_vigente_uq",
            ),
        ]


class InicioResponsabilidad(models.TextChoices):
    ALTA = "alta", "Alta"
    PRESTAMO = "prestamo", "Préstamo"
    DEVOLUCION = "devolucion", "Devolución"
    REACTIVACION = "reactivacion", "Reactivación"
    CAMBIO = "cambio", "Cambio de responsable"


class Responsabilidad(models.Model):
    """Quién hospeda un sensor durante [vigente_desde, vigente_hasta).

    Un sensor no tiene dos responsables a la vez y una persona no hospeda dos sensores a la vez.
    """

    sensor = models.ForeignKey(Sensor, on_delete=models.PROTECT, related_name="responsabilidades")
    cuenta = models.ForeignKey(
        "cuentas.Cuenta", on_delete=models.PROTECT, related_name="responsabilidades"
    )
    inicio = models.CharField(max_length=15, choices=InicioResponsabilidad.choices)
    vigente_desde = models.DateTimeField()
    vigente_hasta = models.DateTimeField(null=True, blank=True)
    registrada_por = models.ForeignKey(
        "cuentas.Cuenta", on_delete=models.PROTECT, related_name="responsabilidades_registradas"
    )
    creada_en = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "responsabilidad"
        constraints = [
            models.CheckConstraint(
                condition=Q(inicio__in=InicioResponsabilidad.values),
                name="responsabilidad_inicio_ck",
            ),
            models.CheckConstraint(
                condition=Q(vigente_hasta__isnull=True)
                | Q(vigente_hasta__gt=models.F("vigente_desde")),
                name="responsabilidad_periodo_ck",
            ),
            _sin_traslape("responsabilidad_sensor_sin_traslape_ex", "sensor"),
            _sin_traslape("responsabilidad_cuenta_sin_traslape_ex", "cuenta"),
        ]


class EstadoVerificacion(models.TextChoices):
    PENDIENTE = "pendiente", "Pendiente"
    EN_CURSO = "en_curso", "En curso"
    LISTA = "lista", "Lista para confirmar"
    SIN_DATOS = "sin_datos", "La nube no tiene datos"
    NUBE_NO_RESPONDE = "nube_no_responde", "La nube no responde"
    VENCIDA = "vencida", "Vencida"
    CONFIRMADA = "confirmada", "Confirmada"


class VerificacionSensor(models.Model):
    """Consulta a la nube que pide el alta de un sensor.

    La web la crea y la consulta; el proceso de fondo la atiende. `datos_alta` lleva lo capturado
    en el formulario, nunca la MAC.
    """

    mac_cifrada = models.TextField()
    mac_huella = models.CharField(max_length=64)
    estado = models.CharField(
        max_length=20, choices=EstadoVerificacion.choices, db_default=EstadoVerificacion.PENDIENTE
    )
    datos_alta = models.JSONField()
    sensor_existente = models.ForeignKey(
        Sensor,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="verificaciones_de_reactivacion",
    )
    token_cifrado = models.TextField(null=True, blank=True)
    apodo_cifrado = models.TextField(null=True, blank=True)
    ultima_lectura_en = models.DateTimeField(null=True, blank=True)
    ultima_lectura_resumen = models.JSONField(null=True, blank=True)
    nube_conserva_desde = models.DateTimeField(null=True, blank=True)
    solicitada_por = models.ForeignKey(
        "cuentas.Cuenta", on_delete=models.PROTECT, related_name="verificaciones_solicitadas"
    )
    solicitada_en = models.DateTimeField(db_default=Now())
    tomada_en = models.DateTimeField(null=True, blank=True)
    terminada_en = models.DateTimeField(null=True, blank=True)
    sensor = models.ForeignKey(
        Sensor, on_delete=models.PROTECT, null=True, blank=True, related_name="verificaciones"
    )

    class Meta:
        db_table = "verificacion_sensor"
        constraints = [
            models.CheckConstraint(
                condition=Q(estado__in=EstadoVerificacion.values), name="verificacion_estado_ck"
            ),
            models.CheckConstraint(
                condition=~Q(estado__in=[EstadoVerificacion.LISTA, EstadoVerificacion.CONFIRMADA])
                | Q(token_cifrado__isnull=False),
                name="verificacion_lista_ck",
            ),
            models.CheckConstraint(
                condition=Q(estado=EstadoVerificacion.CONFIRMADA, sensor__isnull=False)
                | (~Q(estado=EstadoVerificacion.CONFIRMADA) & Q(sensor__isnull=True)),
                name="verificacion_confirmada_ck",
            ),
            models.CheckConstraint(
                condition=~Q(datos_alta__has_key="mac"), name="verificacion_datos_sin_mac_ck"
            ),
            models.UniqueConstraint(
                fields=["mac_huella"],
                condition=Q(estado__in=[EstadoVerificacion.PENDIENTE, EstadoVerificacion.EN_CURSO]),
                name="verificacion_una_activa_uq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["solicitada_en"],
                condition=Q(estado=EstadoVerificacion.PENDIENTE),
                name="verificacion_pendientes_idx",
            )
        ]
