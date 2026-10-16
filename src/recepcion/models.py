from django.db import models
from django.db.models import Q
from django.db.models.functions import Now


class MotivoRelleno(models.TextChoices):
    ALTA = "alta", "Alta del sensor"
    REACTIVACION = "reactivacion", "Reactivación"
    MANUAL = "manual", "Manual"


class EstadoRelleno(models.TextChoices):
    PENDIENTE = "pendiente", "Pendiente"
    EN_CURSO = "en_curso", "En curso"
    TERMINADA = "terminada", "Terminada"
    FALLIDA = "fallida", "Fallida"


class SolicitudRelleno(models.Model):
    """Pedido de traer el historial de un sensor desde una fecha.

    Lo atiende el proceso de fondo.
    """

    sensor = models.ForeignKey(
        "sensores.Sensor", on_delete=models.PROTECT, related_name="solicitudes_relleno"
    )
    desde = models.DateTimeField()
    motivo = models.CharField(max_length=15, choices=MotivoRelleno.choices)
    estado = models.CharField(
        max_length=15, choices=EstadoRelleno.choices, db_default=EstadoRelleno.PENDIENTE
    )
    solicitada_por = models.ForeignKey(
        "cuentas.Cuenta", on_delete=models.PROTECT, related_name="rellenos_solicitados"
    )
    solicitada_en = models.DateTimeField(db_default=Now())
    tomada_en = models.DateTimeField(null=True, blank=True)
    terminada_en = models.DateTimeField(null=True, blank=True)
    lecturas_nuevas = models.IntegerField(null=True, blank=True)
    error = models.CharField(max_length=300, null=True, blank=True)

    class Meta:
        db_table = "solicitud_relleno"
        constraints = [
            models.CheckConstraint(
                condition=Q(motivo__in=MotivoRelleno.values), name="solicitud_relleno_motivo_ck"
            ),
            models.CheckConstraint(
                condition=Q(estado__in=EstadoRelleno.values), name="solicitud_relleno_estado_ck"
            ),
            models.CheckConstraint(
                condition=Q(lecturas_nuevas__gte=0), name="solicitud_relleno_lecturas_ck"
            ),
            models.UniqueConstraint(
                fields=["sensor"],
                condition=Q(estado__in=[EstadoRelleno.PENDIENTE, EstadoRelleno.EN_CURSO]),
                name="solicitud_relleno_una_activa_uq",
            ),
        ]


class ConsultaNube(models.Model):
    """Cómo le fue a la última consulta a la nube de cada sensor: una fila por sensor.

    `ultimo_error` nunca lleva la MAC, el token ni la dirección consultada.
    """

    sensor = models.OneToOneField(
        "sensores.Sensor", on_delete=models.PROTECT, primary_key=True, related_name="consulta_nube"
    )
    ultima_lectura_descargada_en = models.DateTimeField(null=True, blank=True)
    ultimo_intento_en = models.DateTimeField(null=True, blank=True)
    ultimo_exito_en = models.DateTimeField(null=True, blank=True)
    ultimo_error = models.CharField(max_length=300, null=True, blank=True)
    fallas_seguidas = models.IntegerField(db_default=0)
    ultimo_recorrido_completo_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "consulta_nube"
        constraints = [
            models.CheckConstraint(
                condition=Q(fallas_seguidas__gte=0), name="consulta_nube_fallas_ck"
            ),
        ]
