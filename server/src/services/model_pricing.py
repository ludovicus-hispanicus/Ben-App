"""
Approximate API prices, used to show an estimated cost in the Usage tab.

USD per 1M tokens, standard (live) rates. Batch API usage (recorded by the
usage tracker as "<model> (batch)") is billed at 50% of these rates by all
three providers. Prices change often: this is an estimate, the provider's
billing page is authoritative. Update PRICES_AS_OF when editing the table.

Sources (checked 2026-09-29):
  Gemini  https://ai.google.dev/gemini-api/docs/pricing  (page updated 2026-09-24)
  OpenAI  https://developers.openai.com/api/docs/pricing
  Claude  Anthropic model table (claude-api reference, 2026-06-24)

Not modelled: long-prompt tiers (>200K tokens), cached-input discounts, Grok.
"""

import re
from typing import Optional, Tuple

PRICES_AS_OF = "2026-09-29"
BATCH_DISCOUNT = 0.5
BATCH_SUFFIX = " (batch)"

# model id -> list of (effective_from_date, input_per_1m, output_per_1m), oldest first
_PRICES = {
    # ── Gemini ──
    "gemini-3.8-flash": [("2000-01-01", 0.75, 3.75), ("2027-01-01", 1.50, 7.50)],
    "gemini-3.7-flash": [("2000-01-01", 0.75, 3.75), ("2027-01-01", 1.50, 7.50)],
    "gemini-3.6-flash": [("2000-01-01", 0.75, 3.75), ("2027-01-01", 1.50, 7.50)],
    "gemini-3.5-flash": [("2000-01-01", 1.50, 9.00)],
    "gemini-3.5-flash-lite": [("2000-01-01", 0.30, 2.50)],
    "gemini-3.1-flash-lite": [("2000-01-01", 0.25, 1.50)],
    "gemini-3.1-pro": [("2000-01-01", 2.00, 12.00)],
    "gemini-2.5-pro": [("2000-01-01", 1.25, 10.00)],
    "gemini-2.5-flash": [("2000-01-01", 0.30, 2.50)],
    "gemini-2.5-flash-lite": [("2000-01-01", 0.10, 0.40)],
    # ── OpenAI ──
    "gpt-5.6-sol": [("2000-01-01", 4.00, 20.00)],
    "gpt-5.6-terra": [("2000-01-01", 2.00, 12.00)],
    "gpt-5.6-luna": [("2000-01-01", 0.20, 1.20)],
    "gpt-5.5": [("2000-01-01", 5.00, 30.00)],
    "gpt-5.4": [("2000-01-01", 2.50, 15.00)],
    "gpt-5.4-mini": [("2000-01-01", 0.75, 4.50)],
    "gpt-5.4-nano": [("2000-01-01", 0.20, 1.25)],
    "gpt-5.2": [("2000-01-01", 1.75, 14.00)],
    "gpt-5.1": [("2000-01-01", 1.25, 10.00)],
    "gpt-5": [("2000-01-01", 1.25, 10.00)],
    "gpt-5-mini": [("2000-01-01", 0.25, 2.00)],
    "gpt-5-nano": [("2000-01-01", 0.05, 0.40)],
    "gpt-4.1": [("2000-01-01", 2.00, 8.00)],
    "gpt-4.1-mini": [("2000-01-01", 0.40, 1.60)],
    "gpt-4.1-nano": [("2000-01-01", 0.10, 0.40)],
    "gpt-4o": [("2000-01-01", 2.50, 10.00)],
    "gpt-4o-mini": [("2000-01-01", 0.15, 0.60)],
    "o3": [("2000-01-01", 2.00, 8.00)],
    "o4-mini": [("2000-01-01", 1.10, 4.40)],
    # ── Claude ──
    "claude-fable-5-1": [("2000-01-01", 10.00, 50.00)],
    "claude-fable-5": [("2000-01-01", 10.00, 50.00)],
    "claude-opus-5-5": [("2000-01-01", 4.00, 20.00)],
    "claude-opus-5": [("2000-01-01", 5.00, 25.00)],
    "claude-opus-4-8": [("2000-01-01", 5.00, 25.00)],
    "claude-opus-4-7": [("2000-01-01", 5.00, 25.00)],
    "claude-opus-4-6": [("2000-01-01", 5.00, 25.00)],
    "claude-sonnet-5": [("2000-01-01", 2.00, 10.00)],
    "claude-sonnet-4-6": [("2000-01-01", 3.00, 15.00)],
    "claude-haiku-4-5": [("2000-01-01", 1.00, 5.00)],
}

# Dated snapshots and release channels share their base model's price:
# claude-haiku-4-5-20251001, gpt-4o-2024-08-06, gemini-3.1-pro-preview, ...
_SUFFIXES = re.compile(r"(-\d{4}-\d{2}-\d{2}|-\d{8}|-preview(-\d{2}-\d{4})?|-latest|-exp)$")


def _base_model(model: str) -> str:
    model = model.strip().lower()
    while True:
        stripped = _SUFFIXES.sub("", model)
        if stripped == model:
            return model
        model = stripped


def price_for(model: str, day: str) -> Optional[Tuple[float, float]]:
    """(input, output) USD per 1M tokens for a usage-tracker model key on ``day``
    (ISO date), batch discount applied. None if the model isn't in the table."""
    is_batch = model.endswith(BATCH_SUFFIX)
    if is_batch:
        model = model[: -len(BATCH_SUFFIX)]
    periods = _PRICES.get(_base_model(model))
    if not periods:
        return None
    _, inp, out = [p for p in periods if p[0] <= day][-1]
    factor = BATCH_DISCOUNT if is_batch else 1.0
    return inp * factor, out * factor


def estimate_cost(model: str, day: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    """Estimated USD cost, or None if the model's price is unknown."""
    price = price_for(model, day)
    if price is None:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000
