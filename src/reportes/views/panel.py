"""Panel de la red. Provisional."""

from django.http import HttpResponse


def panel_red(request):
    return HttpResponse("En construcción", status=501)
