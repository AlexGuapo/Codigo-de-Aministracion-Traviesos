import getpass
import os

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from cuentas.services import AdministradorYaExiste, crear_administrador


class Command(BaseCommand):
    help = "Crea la única cuenta de Administrador al instalar el sistema."

    def add_arguments(self, parser):
        parser.add_argument("--correo", default=os.environ.get("SARRCA_ADMIN_CORREO"))
        parser.add_argument(
            "--nombre", default=os.environ.get("SARRCA_ADMIN_NOMBRE", "Administrador")
        )

    def handle(self, *args, **opciones):
        """La contraseña nunca va en la línea de comandos.

        Quedaría en el historial y en la lista de procesos: se pide dos veces por teclado o se
        toma de `SARRCA_ADMIN_CONTRASENA` solo para esa ejecución. Se puede repetir sin riesgo.
        """
        if not opciones["correo"]:
            raise CommandError("Falta el correo: use --correo o la variable SARRCA_ADMIN_CORREO.")
        contrasena = os.environ.get("SARRCA_ADMIN_CONTRASENA")
        if not contrasena:
            contrasena = getpass.getpass("Contraseña de la cuenta de Administrador: ")
            if contrasena != getpass.getpass("Repita la contraseña: "):
                raise CommandError("Las contraseñas no coinciden.")
        try:
            cuenta = crear_administrador(opciones["correo"], opciones["nombre"], contrasena)
        except AdministradorYaExiste:
            self.stdout.write("Ya existe una cuenta de Administrador; no se cambió nada.")
            return
        except ValidationError as error:
            raise CommandError("; ".join(error.messages)) from None
        self.stdout.write(self.style.SUCCESS(f"Cuenta de Administrador creada: {cuenta.correo}"))
