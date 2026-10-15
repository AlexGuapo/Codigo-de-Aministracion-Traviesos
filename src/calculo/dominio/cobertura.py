"""Cuántos minutos de una hora cubren sus lecturas, y si con eso la hora es válida.

Cada lectura cubre su intervalo de medición, pero nunca más del tiempo que pasó desde la
lectura anterior del mismo sensor: si el aparato se reinició y midió a los 3 minutos, esa
lectura cubre 3 minutos, no 30. La hora es válida con 45 minutos cubiertos o más (el 75 %).
"""

from __future__ import annotations

from collections.abc import Sequence

from calculo.dominio.tipos import LecturaParaCalculo

MINIMO_HORA_VALIDA_S = 45 * 60
TOPE_HORA_S = 60 * 60


def cobertura_s(
    lecturas: Sequence[LecturaParaCalculo],
    anterior: LecturaParaCalculo | None,
) -> int:
    """Segundos cubiertos por las lecturas de una hora, con tope de 3600.

    `lecturas` son las de la hora, sin copias. `anterior` es la última lectura del sensor antes
    de la hora, o None si el sensor no tiene ninguna antes. Las lecturas que no cuentan (sin
    valor o anómalas) no suman, pero sí sirven de «anterior» para la siguiente. Una lectura sin
    intervalo de medición no suma minutos.
    """
    ordenadas = sorted(lecturas, key=lambda lectura: lectura.hora)
    previa = anterior
    total = 0
    for lectura in ordenadas:
        if lectura.cuenta and lectura.intervalo_s is not None:
            if previa is None:
                desde_anterior = lectura.intervalo_s
            else:
                desde_anterior = int((lectura.hora - previa.hora).total_seconds())
            total += max(0, min(lectura.intervalo_s, desde_anterior))
        previa = lectura
    return min(total, TOPE_HORA_S)


def es_hora_valida(segundos_cubiertos: int) -> bool:
    return segundos_cubiertos >= MINIMO_HORA_VALIDA_S
