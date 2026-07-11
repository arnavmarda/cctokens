"""Cost estimation for Claude Code usage.

Pure functions — no I/O. Rates are USD per 1,000,000 tokens, matching current
Anthropic API pricing. Models are matched by substring so future point releases
(e.g. ``claude-opus-4-9``) resolve without a code change.
"""

from __future__ import annotations

from dataclasses import dataclass

# Multipliers applied to the base *input* rate.
CACHE_READ_MULT = 0.10  # cached prefix served back
CACHE_WRITE_5M_MULT = 1.25  # 5-minute ephemeral cache write
CACHE_WRITE_1H_MULT = 2.00  # 1-hour ephemeral cache write


@dataclass(frozen=True)
class Rate:
    """Per-1M-token USD rates for a model family."""

    input: float
    output: float


# Ordered longest/most-specific first so substring matching is unambiguous.
_RATES: list[tuple[str, Rate]] = [
    ("fable", Rate(10.0, 50.0)),
    ("mythos", Rate(10.0, 50.0)),
    ("opus", Rate(5.0, 25.0)),
    ("sonnet", Rate(3.0, 15.0)),
    ("haiku", Rate(1.0, 5.0)),
]


def rate_for(model: str | None) -> Rate | None:
    """Return the :class:`Rate` for a model id, or ``None`` if unknown."""
    if not model:
        return None
    lowered = model.lower()
    for needle, rate in _RATES:
        if needle in lowered:
            return rate
    return None


def cost_for(
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int,
    cache_read_tokens: int,
    cache_creation_1h: int = 0,
    cache_creation_5m: int = 0,
) -> float | None:
    """Estimate USD cost for one usage record.

    Returns ``None`` for unknown models so callers can render ``n/a``.

    Cache-write pricing: when the transcript splits the creation bucket into
    1h/5m sub-buckets we price each at its own multiplier (2x / 1.25x of the
    input rate). When the split is unavailable (both sub-buckets zero but the
    aggregate is non-zero) we fall back to pricing the whole bucket at the 5m
    rate, which is Claude Code's default TTL.
    """
    rate = rate_for(model)
    if rate is None:
        return None

    per_token_in = rate.input / 1_000_000
    per_token_out = rate.output / 1_000_000

    cost = input_tokens * per_token_in + output_tokens * per_token_out
    cost += cache_read_tokens * per_token_in * CACHE_READ_MULT

    split_total = cache_creation_1h + cache_creation_5m
    if split_total > 0:
        cost += cache_creation_1h * per_token_in * CACHE_WRITE_1H_MULT
        cost += cache_creation_5m * per_token_in * CACHE_WRITE_5M_MULT
        # Any remainder not captured by the split (defensive) at the 5m rate.
        remainder = max(0, cache_creation_tokens - split_total)
        cost += remainder * per_token_in * CACHE_WRITE_5M_MULT
    else:
        cost += cache_creation_tokens * per_token_in * CACHE_WRITE_5M_MULT

    return cost
