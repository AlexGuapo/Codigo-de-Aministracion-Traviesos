import csv
import os
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from cuentas.models import Cuenta, Estado, Origen, Rol
from sensores.models import Colonia


class Command(BaseCommand):
    help = "Crea las cuentas de los vecinos que van a hospedar un sensor, a partir de un CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "archivo",
            help="CSV con las columnas correo, nombre, municipio y colonia (las dos últimas "
            "pueden ir vacías). Lleva datos personales: no se guarda en el repositorio.",
        )

    def handle(self, *args, **opciones):
        """Crea cada cuenta validada, como vecino sin sensor; el alta del sensor le cambia el rol.

        Las cuentas que ya existen no se tocan, así que se puede correr varias veces. Sin
        `SARRCA_PRECARGA_CONTRASENA`, las cuentas quedan sin contraseña y no pueden entrar
        hasta que se les asigne una.
        """
        ruta = Path(opciones["archivo"])
        if not ruta.exists():
            raise CommandError(f"No existe el archivo {ruta}.")
        contrasena = os.environ.get("SARRCA_PRECARGA_CONTRASENA")

        with ruta.open(encoding="utf-8-sig", newline="") as archivo:
            filas = list(csv.DictReader(archivo))
        faltantes = {"correo", "nombre"} - set(filas[0] if filas else {})
        if faltantes:
            raise CommandError(f"Al CSV le faltan las columnas: {', '.join(sorted(faltantes))}.")

        creadas = existentes = 0
        with transaction.atomic():
            for numero, fila in enumerate(filas, start=2):
                correo = (fila.get("correo") or "").strip().lower()
                nombre = (fila.get("nombre") or "").strip()
                if not correo or not nombre:
                    raise CommandError(f"Línea {numero}: faltan el correo o el nombre.")
                if Cuenta.objects.filter(correo=correo).exists():
                    existentes += 1
                    continue
                cuenta = Cuenta(
                    correo=correo,
                    nombre=nombre,
                    colonia=self._colonia(fila, numero),
                    rol=Rol.VECINO_SIN_SENSOR,
                    estado=Estado.VALIDADA,
                    origen=Origen.PRECARGA,
                )
                if contrasena:
                    cuenta.set_password(contrasena)
                else:
                    cuenta.set_unusable_password()
                try:
                    cuenta.full_clean(exclude=["password", "creada_en", "actualizada_en"])
                except ValidationError as error:
                    raise CommandError(f"Línea {numero}: {'; '.join(error.messages)}") from None
                cuenta.save()
                creadas += 1
        self.stdout.write(f"Cuentas creadas: {creadas}. Ya existían: {existentes}.")

    @staticmethod
    def _colonia(fila, numero):
        nombre = (fila.get("colonia") or "").strip()
        if not nombre:
            return None
        municipio = (fila.get("municipio") or "").strip()
        colonias = Colonia.objects.filter(nombre__iexact=nombre)
        if municipio:
            colonias = colonias.filter(municipio__iexact=municipio)
        if colonias.count() != 1:
            raise CommandError(
                f"Línea {numero}: la colonia «{nombre}» no está en el catálogo o se repite; "
                "indique el municipio."
            )
        return colonias.get()
