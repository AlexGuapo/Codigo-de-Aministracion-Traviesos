from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Now


class TipoParametro(models.TextChoices):
    LIMITE_24H = "limite_24h", "Límite de 24 h"
    LIMITE_ANUAL = "limite_anual", "Límite anual"
    BANDA_NOM172 = "banda_nom172", "Banda del índice"
    UMBRAL_NORMA_REBASADA = "umbral_norma_rebasada", "Umbral de norma rebasada"
    BANDERA = "bandera", "Valor de una bandera"
    MARGEN = "margen", "Margen"


class VariableCalculada(models.TextChoices):
    PM1 = "pm1", "PM1"
    PM25 = "pm25", "PM2.5"
    PM4 = "pm4", "PM4"
    PM10 = "pm10", "PM10"
    CO2 = "co2", "CO2"


class Periodo(models.TextChoices):
    HORA = "hora", "Hora"
    DIA = "dia", "Día"
    MES = "mes", "Mes"


class EstadoCalculo(models.TextChoices):
    PRELIMINAR = "preliminar", "Preliminar"
    CERRADO = "cerrado", "Cerrado"


class CausaRecalculo(models.TextChoices):
    LECTURA_NUEVA = "lectura_nueva", "Lectura nueva"
    LECTURA_ATRASADA = "lectura_atrasada", "Lectura atrasada"
    CATALOGACION = "catalogacion", "Catalogación"
    REVERSION = "reversion", "Reversión"
    MANUAL = "manual", "Manual"


class Parametro(models.Model):
    """Un límite o umbral con su vigencia. `vigente_hasta` es inclusivo.

    Nunca se edita: un cambio es una fila nueva con su propia vigencia, así los días anteriores
    se siguen comparando con el valor que regía entonces.
    """

    tipo = models.CharField(max_length=25, choices=TipoParametro.choices)
    norma = models.CharField(max_length=30)
    variable = models.CharField(max_length=20, null=True)
    categoria = models.CharField(max_length=30, null=True)
    clave = models.CharField(max_length=40, null=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    valor_hasta = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    unidad = models.CharField(max_length=15)
    vigente_desde = models.DateField()
    vigente_hasta = models.DateField(null=True)
    referencia = models.CharField(max_length=200, null=True)
    cargado_por = models.ForeignKey(
        "cuentas.Cuenta", on_delete=models.PROTECT, null=True, related_name="parametros_cargados"
    )
    cargado_en = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "parametro"
        constraints = [
            models.CheckConstraint(
                condition=Q(tipo__in=TipoParametro.values), name="parametro_tipo_ck"
            ),
            models.CheckConstraint(
                condition=Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gte=F("vigente_desde")),
                name="parametro_periodo_ck",
            ),
        ]
        indexes = [
            models.Index(
                "tipo", "variable", F("vigente_desde").desc(), name="parametro_busqueda_idx"
            )
        ]


class ValorCalculado(models.Model):
    """El resultado vigente de una hora, un día o un mes de un sensor y una variable.

    Se sobrescribe cada vez que se recalcula. Las columnas que no aplican a un periodo quedan
    vacías (por ejemplo, `cobertura_min` solo existe en las horas).
    """

    sensor = models.ForeignKey(
        "sensores.Sensor", on_delete=models.PROTECT, related_name="valores_calculados"
    )
    variable = models.CharField(max_length=10, choices=VariableCalculada.choices)
    periodo = models.CharField(max_length=10, choices=Periodo.choices)
    inicio = models.DateTimeField()
    cobertura_min = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    lecturas_contadas = models.SmallIntegerField(null=True)
    horas_validas = models.SmallIntegerField(null=True)
    dias_con_medicion = models.SmallIntegerField(null=True)
    dias_validos = models.SmallIntegerField(null=True)
    dias_excedencia = models.SmallIntegerField(null=True)
    es_valido = models.BooleanField()
    valor = models.DecimalField(max_digits=8, decimal_places=1, null=True)
    valor_entero = models.IntegerField(null=True)
    excedencia = models.BooleanField(null=True)
    parametro = models.ForeignKey(
        Parametro, on_delete=models.PROTECT, null=True, related_name="valores_calculados"
    )
    version_calculo = models.CharField(max_length=20)
    estado = models.CharField(max_length=10, choices=EstadoCalculo.choices)
    calculado_en = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "valor_calculado"
        constraints = [
            models.CheckConstraint(
                condition=Q(variable__in=VariableCalculada.values),
                name="valor_calculado_variable_ck",
            ),
            models.CheckConstraint(
                condition=Q(periodo__in=Periodo.values), name="valor_calculado_periodo_ck"
            ),
            models.CheckConstraint(
                condition=Q(estado__in=EstadoCalculo.values), name="valor_calculado_estado_ck"
            ),
            models.CheckConstraint(
                condition=Q(cobertura_min__range=(0, 60)), name="valor_calculado_cobertura_ck"
            ),
            models.CheckConstraint(
                condition=Q(lecturas_contadas__gte=0), name="valor_calculado_lecturas_ck"
            ),
            models.CheckConstraint(
                condition=Q(horas_validas__range=(0, 24)), name="valor_calculado_horas_ck"
            ),
            models.CheckConstraint(
                condition=Q(dias_con_medicion__range=(0, 31)),
                name="valor_calculado_dias_medicion_ck",
            ),
            models.CheckConstraint(
                condition=Q(dias_validos__range=(0, 31)), name="valor_calculado_dias_validos_ck"
            ),
            models.CheckConstraint(
                condition=Q(dias_excedencia__range=(0, 31)),
                name="valor_calculado_dias_excedencia_ck",
            ),
            models.UniqueConstraint(
                fields=["sensor", "variable", "periodo", "inicio"], name="valor_calculado_uq"
            ),
            models.CheckConstraint(
                condition=Q(es_valido=True) | Q(valor__isnull=True, valor_entero__isnull=True),
                name="valor_solo_si_valido_ck",
            ),
            models.CheckConstraint(
                condition=~Q(periodo=Periodo.HORA)
                | Q(
                    cobertura_min__isnull=False,
                    lecturas_contadas__isnull=False,
                    horas_validas__isnull=True,
                    dias_validos__isnull=True,
                    valor_entero__isnull=True,
                    excedencia__isnull=True,
                ),
                name="valor_hora_ck",
            ),
            models.CheckConstraint(
                condition=~Q(periodo=Periodo.DIA)
                | Q(
                    horas_validas__isnull=False,
                    cobertura_min__isnull=True,
                    dias_validos__isnull=True,
                ),
                name="valor_dia_ck",
            ),
            models.CheckConstraint(
                condition=~Q(periodo=Periodo.MES)
                | Q(
                    dias_validos__isnull=False,
                    dias_con_medicion__isnull=False,
                    cobertura_min__isnull=True,
                    horas_validas__isnull=True,
                    excedencia__isnull=True,
                ),
                name="valor_mes_ck",
            ),
            models.CheckConstraint(
                condition=Q(excedencia__isnull=True, dias_excedencia__isnull=True)
                | Q(variable__in=[VariableCalculada.PM25, VariableCalculada.PM10]),
                name="valor_excedencia_ck",
            ),
        ]
        indexes = [models.Index(fields=["periodo", "inicio"], name="valor_calculado_periodo_idx")]


class MarcaRecalculo(models.Model):
    """Una hora de un sensor que hay que volver a calcular.

    No tiene clave única a propósito: el proceso de fondo borra solo las marcas que tomó, así
    una marca que llega mientras calcula no se pierde.
    """

    sensor = models.ForeignKey(
        "sensores.Sensor", on_delete=models.PROTECT, related_name="marcas_recalculo"
    )
    hora = models.DateTimeField()
    causa = models.CharField(max_length=20, choices=CausaRecalculo.choices)
    creada_en = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "marca_recalculo"
        constraints = [
            models.CheckConstraint(
                condition=Q(causa__in=CausaRecalculo.values), name="marca_recalculo_causa_ck"
            ),
        ]
        indexes = [
            models.Index(fields=["id"], name="marca_recalculo_cola_idx"),
            models.Index(fields=["sensor", "hora"], name="marca_recalculo_sensor_idx"),
        ]
