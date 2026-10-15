#!/usr/bin/env python
"""Punto de entrada de Django (migrate, runserver, comandos de las apps)."""

import os
import sys
from pathlib import Path


def main() -> None:
    # Las apps viven en src/ y se importan sin el prefijo: `from recepcion.ports import ...`.
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
