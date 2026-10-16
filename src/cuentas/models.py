from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower, Now


class Rol(models.TextChoices):
    ADMINISTRADOR = "administrador", "Administrador"
    VECINO_CON_SENSOR = "vecino_con_sensor", "Vecino con sensor"
    VECINO_SIN_SENSOR = "vecino_sin_sensor", "Vecino sin sensor"


class Estado(models.TextChoices):
    POR_ACTIVAR = "por_activar", "Por activar"
    POR_VALIDAR = "por_validar", "Por validar"
    VALIDADA = "validada", "Validada"
    BLOQUEADA = "bloqueada", "Bloqueada"
    DADA_DE_BAJA = "dada_de_baja", "Dada de baja"
    SUPRIMIDA = "suprimida", "Suprimida"


class Origen(models.TextChoices):
    REGISTRO_PROPIO = "registro_propio", "Registro propio"
    CREADA_POR_ADMIN = "creada_por_admin", "Creada por el Administrador"
    PRECARGA = "precarga", "Precargada"
    INSTALACION = "instalacion", "Creada al instalar el sistema"


# Una cuenta por validar sí entra: puede consultar, pero todavía no reportar.
ESTADOS_QUE_ENTRAN = (Estado.POR_VALIDAR, Estado.VALIDADA)


class CuentaManager(BaseUserManager):
    def get_by_natural_key(self, correo):
        return self.get(correo=(correo or "").strip().lower())


class Cuenta(AbstractBaseUser):
    """Persona que entra a SARRCA. Es el modelo de usuario de Django.

    Al suprimir sus datos personales, el correo y el nombre quedan vacíos y la fila se conserva,
    porque otras tablas la citan.
    """

    correo = models.EmailField(max_length=254, null=True, blank=True, unique=True)
    nombre = models.CharField(max_length=150, null=True, blank=True)
    colonia = models.ForeignKey(
        "sensores.Colonia", on_delete=models.PROTECT, null=True, blank=True, related_name="cuentas"
    )
    rol = models.CharField(max_length=20, choices=Rol.choices)
    estado = models.CharField(max_length=15, choices=Estado.choices)
    origen = models.CharField(max_length=20, choices=Origen.choices)
    aviso_privacidad_version = models.CharField(max_length=20, null=True, blank=True)
    aviso_privacidad_aceptado_en = models.DateTimeField(null=True, blank=True)
    creada_en = models.DateTimeField(db_default=Now())
    actualizada_en = models.DateTimeField(db_default=Now())

    objects = CuentaManager()

    USERNAME_FIELD = "correo"
    REQUIRED_FIELDS = ["nombre"]

    class Meta:
        db_table = "cuenta"
        constraints = [
            models.CheckConstraint(condition=Q(rol__in=Rol.values), name="cuenta_rol_ck"),
            models.CheckConstraint(condition=Q(estado__in=Estado.values), name="cuenta_estado_ck"),
            models.CheckConstraint(condition=Q(origen__in=Origen.values), name="cuenta_origen_ck"),
            models.CheckConstraint(
                condition=Q(correo=Lower("correo")), name="cuenta_correo_minusculas_ck"
            ),
            models.CheckConstraint(
                condition=Q(estado=Estado.SUPRIMIDA)
                | (Q(nombre__isnull=False) & Q(correo__isnull=False)),
                name="cuenta_datos_personales_ck",
            ),
            models.CheckConstraint(
                condition=Q(
                    aviso_privacidad_version__isnull=True, aviso_privacidad_aceptado_en__isnull=True
                )
                | Q(
                    aviso_privacidad_version__isnull=False,
                    aviso_privacidad_aceptado_en__isnull=False,
                ),
                name="cuenta_aviso_completo_ck",
            ),
            # Nunca puede haber dos Administradores vigentes; lo impide la base, no solo el código.
            models.UniqueConstraint(
                fields=["rol"],
                condition=Q(rol=Rol.ADMINISTRADOR)
                & ~Q(estado__in=[Estado.DADA_DE_BAJA, Estado.SUPRIMIDA]),
                name="cuenta_una_admin_uq",
            ),
        ]

    def __str__(self):
        return self.correo or f"cuenta {self.pk}"

    @property
    def is_active(self):
        return self.estado in ESTADOS_QUE_ENTRAN

    @property
    def es_administrador(self):
        return self.rol == Rol.ADMINISTRADOR

    def save(self, *args, **kwargs):
        if self.correo:
            self.correo = self.correo.strip().lower()
        super().save(*args, **kwargs)


class IntentoAcceso(models.Model):
    """Cada intento de inicio de sesión, con su correo tecleado y su IP.

    La pausa por intentos fallidos se calcula contando estas filas; no se guarda aparte. El
    correo es el que se tecleó, exista o no la cuenta, para no revelar qué correos existen.
    """

    correo_intentado = models.CharField(max_length=254)
    cuenta = models.ForeignKey(
        Cuenta, on_delete=models.PROTECT, null=True, blank=True, related_name="intentos_acceso"
    )
    ip = models.GenericIPAddressField()
    exito = models.BooleanField()
    ocurrido_en = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "intento_acceso"
        indexes = [
            models.Index(
                fields=["correo_intentado", "ip", "ocurrido_en"],
                name="intento_acceso_correo_ip_idx",
            )
        ]
