"""Redondeo de la norma: los 5 suben siempre.

`round()` de Python redondea al par (`round(2.5)` da 2), y la norma pide que 2.5 dé 3. Por eso
todo se redondea con `Decimal` y `ROUND_HALF_UP`.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

UN_DECIMAL = Decimal("0.1")
ENTERO = Decimal("1")


def a_decimal(valor: Decimal | float | int) -> Decimal:
    """Convierte sin arrastrar el ruido binario del flotante (`2.3` y no `2.2999999523…`)."""
    if isinstance(valor, Decimal):
        return valor
    return Decimal(repr(valor)) if isinstance(valor, float) else Decimal(valor)


def a_un_decimal(valor: Decimal | float | int) -> Decimal:
    return a_decimal(valor).quantize(UN_DECIMAL, rounding=ROUND_HALF_UP)


def a_entero(valor: Decimal | float | int) -> int:
    return int(a_decimal(valor).quantize(ENTERO, rounding=ROUND_HALF_UP))
