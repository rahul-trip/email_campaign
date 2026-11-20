"""What each paid call costs, in micro-dollars (1,000,000 = $1).

Prices are keyed ``"provider:operation"``. ``None`` means the vendor does not publish a price,
so the ledger records 0 and the report shows the call as "price unknown" rather than free.
Taken from vendor pages on 2026-10-16 and checked again on 2026-11-20 at the smallest pack or
plan each vendor sells, which is what a small install pays; a larger pack is cheaper. Confirm
before relying on them, and override with the ``PROVIDER_PRICES`` setting (or
``--prices FILE.json`` in the bake-off) once you know your plan's rates.
"""

from __future__ import annotations

DEFAULT_PRICES: dict[str, int | None] = {
    "hunter:find": 24_500,  # Starter: $49 / 2,000 credits, 1 credit per address found
    "hunter:verify": 12_250,  # assumed 0.5 credit; the verifier docs do not state a cost
    # 20 credits per address found: $0.39 at the $39 pack of 2,000 (its smallest), about $0.16
    # only on the annual plan (research report, 2026-11; not rechecked on its own pages).
    "zerobounce:find": 390_000,
    # Estimates from the vendors' public plans, charged only for an address found: set the real
    # price of your plan in PROVIDER_PRICES once you know it.
    "anymailfinder:find": 72_500,  # $29 a month for 400 credits, 1 per valid address ($49: 1,000)
    "prospeo:find": 39_000,  # about $39 for 1,000 credits, 1 per address found
    "icypeas:find": 19_000,  # $19 for 1,000 credits that do not expire, 1 per address found
    "generect:find": 20_000,  # $0.02 per valid address (its documented example)
    "zerobounce:verify": 8_000,  # $0.008; unknown results are free (billed=False)
    "myemailverifier:verify": 3_800,  # $4 for 1,050 after the 100 free requests a day
    # $39 for 10,000 credits that do not expire; catch-all and unknown are not charged
    # (billed=False), under a goodwill programme the vendor may end.
    "millionverifier:verify": 3_900,
    # 0.2 credit a check, charged for every answer: $0.003 at the $30 pack of 2,000 credits
    # ($0.0002 only at the 10-million pack).
    "orbisearch:verify": 3_000,
    "orbisearch:resolve": 3_000,  # the same check, asked of an address a verifier called catch-all
    # One credit a check. Its pricing page shows no dollar figure without a login: $50 for
    # 10,000 is the higher of the two figures seen elsewhere ($40 in the research report).
    "bounceban:resolve": 5_000,
    "enrichley:resolve": 11_800,  # about $0.0118 a credit
    "scrubby:resolve": None,  # pricing is not public
    "tavily:search": 8_000,  # $0.008 a credit, 1 credit for a basic search
    "tavily:extract": 8_000,  # 1 credit per 5 URLs; charged as one credit per call here
    "companies_house:lookup": 0,  # free, rate-limited
    "yc_directory:find": 0,  # the public yc-oss mirror: free, filtered locally
    "companies_house:find": 0,  # advanced search: free, rate-limited
    # One search plus up to two lookalike requests, each $0.005 for up to 25 results plus
    # $0.001 a page for its text: about $0.09 at most.
    "exa:find": 90_000,
}

# LLM prices per million tokens as ``(input, output)`` in micro-dollars. Unknown models cost 0
# in the ledger and are reported as unpriced; add the model here or in ``PROVIDER_PRICES``.
DEFAULT_LLM_PRICES: dict[str, tuple[int, int]] = {}


def price_of(prices: dict[str, int | None], provider: str, operation: str) -> int:
    """The price of one call, or 0 when it is free or unknown."""
    return prices.get(f"{provider}:{operation}") or 0


def llm_cost(
    prices: dict[str, tuple[int, int]], model: str, input_tokens: int, output_tokens: int
) -> int:
    """Cost of one model call, rounded up to a whole micro-dollar."""
    rate = prices.get(model)
    if rate is None:
        return 0
    per_input, per_output = rate
    return -(-(input_tokens * per_input + output_tokens * per_output) // 1_000_000)
