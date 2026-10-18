"""What each paid call costs, in micro-dollars (1,000,000 = $1).

Prices are keyed ``"provider:operation"``. ``None`` means the vendor does not publish a price,
so the ledger records 0 and the report shows the call as "price unknown" rather than free.
Taken from vendor pages and the research report on 2026-10-16; confirm before relying on them,
and override with the ``PROVIDER_PRICES`` setting (or ``--prices FILE.json`` in the bake-off)
once you know your plan's rates.
"""

from __future__ import annotations

DEFAULT_PRICES: dict[str, int | None] = {
    "hunter:find": 24_500,  # Starter: $49 / 2,000 credits, 1 credit per address found
    "hunter:verify": 12_250,  # assumed 0.5 credit; the verifier docs do not state a cost
    "zerobounce:find": 160_000,  # 20 credits per address found at $0.008 a credit
    "zerobounce:verify": 8_000,  # $0.008; unknown results are free (billed=False)
    "myemailverifier:verify": 2_500,  # $0.0025 after the 100 free requests a day
    "orbisearch:verify": 200,  # 0.2 credit at $0.001 a credit
    "enrichley:resolve": 11_800,  # about $0.0118 a credit
    "scrubby:resolve": None,  # pricing is not public
    "tavily:search": 8_000,  # $0.008 a credit, 1 credit for a basic search
    "tavily:extract": 8_000,  # 1 credit per 5 URLs; charged as one credit per call here
    "companies_house:lookup": 0,  # free, rate-limited
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
