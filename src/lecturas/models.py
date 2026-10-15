from django.db import models
from django.db.models import Q
from django.db.models.functions import Now


class RutaLectura(models.TextChoices):
    HISTORIAL = "history", "Historial de la nube"
    ULTIMA = "dataMacByKey", "Última lectura de la nube"
    ARCHIVO = "archivo", "Archivo del histórico"


class OrigenLectura(models.TextChoices):
    NUBE = "nube", "Nube"
    HISTORICO = "historico", "Histórico de la investigadora"


RUTAS_DE_LA_NUBE = [RutaLectura.HISTORIAL, RutaLectura.ULTIMA]


class Lectura(models.Model):
    """Una medición tal como llegó. Nunca se edita ni se borra.

    Los campos de partículas se llaman como en la interpretación del valor (`pm2_5`) y sus
    columnas como en la base (`pm25`). Un valor nulo es «sin dato», nunca cero.
    """

    sensor = models.ForeignKey("sensores.Sensor", on_delete=models.PROTECT, related_name="lecturas")
    hora = models.DateTimeField()
    hora_nube_original = models.CharField(max_length=32)
    ruta = models.CharField(max_length=15, choices=RutaLectura.choices)
    origen = models.CharField(max_length=10, choices=OrigenLectura.choices)
    pm1_0 = models.FloatField(null=True, db_column="pm1")
    pm2_5 = models.FloatField(null=True, db_column="pm25")
    pm4_0 = models.FloatField(null=True, db_column="pm4")
    pm10_0 = models.FloatField(null=True, db_column="pm10")
    co2 = models.FloatField(null=True)
    temperatura_sen55 = models.FloatField(null=True)
    humedad_sen55 = models.FloatField(null=True)
    temperatura_scd40 = models.FloatField(null=True)
    humedad_scd40 = models.FloatField(null=True)
    voc = models.FloatField(null=True)
    nox = models.FloatField(null=True)
    intervalo_s = models.IntegerField(null=True)
    huella_valores = models.CharField(max_length=64)
    crudo = models.TextField()
    copia_discrepante_de = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, related_name="copias_discrepantes"
    )
    carga_historico_id = models.BigIntegerField(null=True)
    registrada_en = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "lectura"
        constraints = [
            models.CheckConstraint(
                condition=Q(ruta__in=RutaLectura.values), name="lectura_ruta_ck"
            ),
            models.CheckConstraint(
                condition=Q(origen__in=OrigenLectura.values), name="lectura_origen_ck"
            ),
            models.CheckConstraint(condition=Q(intervalo_s__gt=0), name="lectura_intervalo_ck"),
            models.CheckConstraint(
                condition=Q(origen=OrigenLectura.NUBE, ruta__in=RUTAS_DE_LA_NUBE)
                | (~Q(origen=OrigenLectura.NUBE) & ~Q(ruta__in=RUTAS_DE_LA_NUBE)),
                name="lectura_origen_ruta_ck",
            ),
            models.CheckConstraint(
                condition=Q(origen=OrigenLectura.HISTORICO, carga_historico_id__isnull=False)
                | (~Q(origen=OrigenLectura.HISTORICO) & Q(carga_historico_id__isnull=True)),
                name="lectura_carga_ck",
            ),
            models.UniqueConstraint(
                fields=["sensor", "hora", "huella_valores"], name="lectura_medicion_uq"
            ),
        ]
