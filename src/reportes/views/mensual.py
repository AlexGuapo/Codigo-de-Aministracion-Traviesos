"""Reporte mensual. Provisional."""

from django.http import HttpResponse


def reporte_mensual(request):
    return HttpResponse("En construcción", status=501)


def lamina(request):
    return HttpResponse("En construcción", status=501)
