from datetime import date
from decimal import Decimal

from django.db import migrations

NORMA = "NOM-025-SSA1-2021"
UNIDAD = "µg/m³"

# La Tabla 1 de la norma solo da valores para los años 1, 3 y 5, contados desde su entrada en
# vigor (26/12/2021). Los años 2 y 4 usan los del año anterior, por eso cada escalón dura dos
# años. Antes del 26/12/2021 no hay fila: la norma no regía y esos días no se evalúan.
ESCALONES = [
    ("año 1", date(2021, 12, 26), date(2023, 12, 25), {"pm10": (70, 36), "pm25": (41, 10)}),
    ("año 3", date(2023, 12, 26), date(2025, 12, 25), {"pm10": (60, 28), "pm25": (33, 10)}),
    ("año 5", date(2025, 12, 26), None, {"pm10": (50, 20), "pm25": (25, 10)}),
]


def cargar_limites(apps, schema_editor):
    Parametro = apps.get_model("calculo", "Parametro")
    filas = []
    for anio, desde, hasta, limites in ESCALONES:
        for variable, (limite_24h, limite_anual) in limites.items():
            for tipo, valor in (("limite_24h", limite_24h), ("limite_anual", limite_anual)):
                filas.append(
                    Parametro(
                        tipo=tipo,
                        norma=NORMA,
                        variable=variable,
                        valor=Decimal(valor),
                        unidad=UNIDAD,
                        vigente_desde=desde,
                        vigente_hasta=hasta,
                        referencia=f"Tabla 1, {anio}",
                    )
                )
    Parametro.objects.bulk_create(filas)


def quitar_limites(apps, schema_editor):
    apps.get_model("calculo", "Parametro").objects.filter(
        norma=NORMA, tipo__in=["limite_24h", "limite_anual"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("calculo", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(cargar_limites, quitar_limites),
    ]
