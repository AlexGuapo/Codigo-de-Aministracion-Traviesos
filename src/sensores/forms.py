from datetime import date

from django import forms
from django.utils import timezone

from cuentas.models import Cuenta
from sensores.cifrado import Cifrador
from sensores.models import Colonia, EstadoSensor, Sensor
from sensores.services import responsables_disponibles
from sensores.validaciones import (
    MacInvalida,
    NombreCortoInvalido,
    normalizar_mac,
    validar_nombre_corto,
)


class ResponsableChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, cuenta):
        if cuenta.colonia_id:
            return f"{cuenta.nombre} · {cuenta.colonia.nombre}"
        return cuenta.nombre


def _colonias_por_municipio():
    grupos: dict[str, list] = {}
    for colonia in Colonia.objects.filter(activa=True).order_by("municipio", "nombre"):
        grupos.setdefault(colonia.municipio, []).append((colonia.pk, colonia.nombre))
    return [("", "Elige la colonia"), *grupos.items()]


class AltaSensorForm(forms.Form):
    """Datos del alta de un sensor.

    Si la MAC es de un sensor dado de baja, el alta lo reactiva con su historial y conserva su
    nombre corto (queda en `sensor_existente`).
    """

    nombre_corto = forms.CharField(
        label="Nombre corto",
        max_length=40,
        required=False,
        help_text="De 2 a 10 caracteres. Sin el nombre del responsable ni la dirección: "
        "lo ve el público.",
        widget=forms.TextInput(attrs={"maxlength": 10, "autocomplete": "off"}),
    )
    mac = forms.CharField(
        label="MAC",
        max_length=40,
        help_text="12 caracteres, con o sin «:». El token de lectura lo obtiene el sistema.",
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
    )
    lecturas_desde = forms.DateField(
        label="Traer lecturas desde",
        help_text="La nube conserva las últimas ~500 lecturas (unos 10 días).",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    responsable = ResponsableChoiceField(
        label="Responsable",
        queryset=Cuenta.objects.none(),
        empty_label="Elige un vecino sin sensor",
        help_text="Obligatorio. Nadie tiene más de un sensor.",
    )
    colonia = forms.TypedChoiceField(label="Colonia", coerce=int)
    direccion = forms.CharField(label="Dirección", max_length=250)
    latitud = forms.DecimalField(
        label="Latitud", max_digits=9, decimal_places=6, min_value=-90, max_value=90
    )
    longitud = forms.DecimalField(
        label="Longitud", max_digits=9, decimal_places=6, min_value=-180, max_value=180
    )

    def __init__(self, *args, cifrador: Cifrador | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._cifrador = cifrador
        self.sensor_existente: Sensor | None = None
        self.fields["responsable"].queryset = responsables_disponibles()
        self.fields["colonia"].choices = _colonias_por_municipio()
        if not self.is_bound:
            self.initial.setdefault("lecturas_desde", timezone.now().date())

    def clean_mac(self):
        try:
            mac = normalizar_mac(self.cleaned_data["mac"])
        except MacInvalida as error:
            raise forms.ValidationError(str(error)) from None
        cifrador = self._cifrador or Cifrador.desde_entorno()
        sensor = Sensor.objects.filter(mac_huella=cifrador.huella_mac(mac)).first()
        if sensor is not None and sensor.estado == EstadoSensor.ACTIVO:
            raise forms.ValidationError(f"Esa MAC ya pertenece al sensor {sensor.nombre_corto}.")
        self.sensor_existente = sensor
        return mac

    def clean_lecturas_desde(self):
        fecha: date = self.cleaned_data["lecturas_desde"]
        if fecha > timezone.now().date():
            raise forms.ValidationError("La fecha no puede ser futura.")
        return fecha

    def clean_colonia(self):
        colonia = Colonia.objects.filter(pk=self.cleaned_data["colonia"], activa=True).first()
        if colonia is None:
            raise forms.ValidationError("Elige una colonia del catálogo.")
        return colonia

    def clean(self):
        datos = super().clean()
        if self.sensor_existente is not None:
            datos["nombre_corto"] = self.sensor_existente.nombre_corto
            return datos
        responsable = datos.get("responsable")
        if responsable is None:
            return datos
        try:
            nombre = validar_nombre_corto(
                datos.get("nombre_corto", ""),
                nombre_responsable=responsable.nombre,
                direccion=datos.get("direccion", ""),
            )
        except NombreCortoInvalido as error:
            self.add_error("nombre_corto", str(error))
            return datos
        if Sensor.objects.filter(nombre_corto__iexact=nombre).exists():
            self.add_error("nombre_corto", "Ya hay un sensor con ese nombre corto.")
        datos["nombre_corto"] = nombre
        return datos

    def datos_alta(self) -> dict:
        """Lo que se guarda en la verificación para crear el sensor al confirmar. Sin la MAC."""
        datos = self.cleaned_data
        return {
            "nombre_corto": datos["nombre_corto"],
            "responsable_id": datos["responsable"].pk,
            "colonia_id": datos["colonia"].pk,
            "direccion": datos["direccion"],
            "latitud": str(datos["latitud"]),
            "longitud": str(datos["longitud"]),
            "lecturas_desde": datos["lecturas_desde"].isoformat(),
        }
