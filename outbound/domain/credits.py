"""AI credits: the one unit a customer sees, plans allow and admins grant.

Vendors and the model bill the platform in dollars. The meter keeps that cost on every ledger row
for the platform's own books and turns it into AI credits at the platform's rate
(``credit_value_micro_usd``: how much vendor or model cost one credit stands for), set by a
superadmin. The credits are stamped on the row when the call is made, so a later change of rate
never rewrites what was already used.

A model call is the exception: a superadmin sets each model's charge directly in AI credits per
million input and output tokens (the Language model card in the console), and the call uses
exactly that. A model with no charge set falls back to its dollar price, if one is configured.

Credits are kept in thousandths (milli-credits) so a small model call is not rounded up to a whole
credit; plans and grants are whole credits.
"""

from __future__ import annotations

MILLI = 1000

# One AI credit stands for one US cent of vendor and model cost unless a superadmin changes it.
DEFAULT_CREDIT_VALUE_MICRO_USD = 10_000


def credits_for(cost_micro_usd: int, credit_value_micro_usd: int) -> int:
    """The milli-credits a call of this cost uses, rounded up: a paid call never costs nothing."""
    if cost_micro_usd <= 0:
        return 0
    value = max(1, credit_value_micro_usd)
    return -(-cost_micro_usd * MILLI // value)


def milli(credits: int) -> int:
    """Whole credits in milli-credits."""
    return credits * MILLI


def as_credits(milli_credits: int) -> float:
    """Milli-credits as credits, to one decimal place, for an API response."""
    return round(milli_credits / MILLI, 1)


def llm_credits(
    input_tokens: int, output_tokens: int, per_million_in: float, per_million_out: float
) -> int:
    """The milli-credits a model call uses at a charge per million tokens, rounded up."""
    exact = (input_tokens * per_million_in + output_tokens * per_million_out) * MILLI / 1_000_000
    whole = int(exact)
    return whole + (exact > whole)
