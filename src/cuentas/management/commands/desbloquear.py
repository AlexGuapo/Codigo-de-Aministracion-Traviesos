from django.core.management.base import BaseCommand

from cuentas.services import desbloquear


class Command(BaseCommand):
    help = "Levanta la pausa por intentos fallidos de un correo (de todas sus IP, o de una)."

    def add_arguments(self, parser):
        parser.add_argument("correo")
        parser.add_argument("--ip", default=None)

    def handle(self, *args, **opciones):
        borrados = desbloquear(opciones["correo"], opciones["ip"])
        self.stdout.write(f"Intentos fallidos borrados: {borrados}")
