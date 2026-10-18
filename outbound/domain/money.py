"""Money is an integer count of micro-dollars (1 USD = 1,000,000), so sums never drift."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

MICRO = 1_000_000


def usd_to_micro(amount: str | int | Decimal) -> int:
    """Convert a dollar amount to micro-dollars. Floats are refused: pass a string or Decimal.

    ``usd_to_micro("0.0025")`` is 2500.
    """
    return int((Decimal(amount) * MICRO).to_integral_value(rounding=ROUND_HALF_UP))


def micro_to_usd(micro: int) -> Decimal:
    return Decimal(micro) / MICRO


def format_usd(micro: int, places: int = 4) -> str:
    return f"${micro_to_usd(micro):.{places}f}"
