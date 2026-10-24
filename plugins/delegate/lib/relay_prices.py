"""Tokens to money. The price table is prices.toml at the repository root.

Notional dollars: what the tokens would cost at Claude Code's list prices. Also
the estimate settings (output tokens per visible character, helper uplift)."""

from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import os
from typing import Any, Mapping

from relay_config import ROOT, read_toml

_TABLE: dict[str, Any] | None = None
PER = 1_000_000


def table() -> dict[str, Any]:
    global _TABLE
    if _TABLE is None:
        path = os.environ.get("RELAY_PRICES") or os.path.join(ROOT, "prices.toml")
        if not os.path.isfile(path):
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices.toml")
        _TABLE = read_toml(path)
    return _TABLE


def tier(model: str | None) -> str:
    """The price key for a model id or alias: 'opus', 'sonnet', 'haiku', 'haiku-4-5', 'fable' or 'default'."""
    name = (model or "").lower()
    keys: list[str] = sorted((k for k in table()["models"] if k != "default"), key=len, reverse=True)
    for key in keys:
        if key in name:
            return key
    return "default"


def family(model: str | None) -> str:
    """The coarse family ('opus', 'sonnet', 'haiku', 'fable', 'default'): haiku-4-5 counts as haiku."""
    key = tier(model)
    return key.split("-")[0] if key != "default" else key


def _bounded(value: Any, low: float, high: float, default: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return float(min(high, max(low, value)))


def output_per_char(model: str | None) -> float:
    """Output tokens per visible character for an agent answer of this model (bound 0.3-2.0)."""
    factors = table().get("estimate", {}).get("output_per_char", {})
    raw = factors.get(tier(model), factors.get(family(model), factors.get("default", 0.8)))
    return _bounded(raw, 0.3, 2.0, 0.8)


def helper_uplift() -> float:
    """Multiplier on agents' cost for Claude Code's hidden helper requests (bound 1.0-1.6)."""
    return _bounded(table().get("estimate", {}).get("helper_uplift", 1.23), 1.0, 1.6, 1.23)


def calibration_tolerance() -> float:
    return _bounded(table().get("estimate", {}).get("calibration_tolerance", 0.02), 0.005, 0.10, 0.02)


def is_before(model: str | None, when: str | None) -> bool:
    """True when the request time `when` (ISO text) is before the date up to which the model had earlier prices."""
    earlier = table()["models"][tier(model)].get("before")
    return bool(earlier and when and when[:10] < str(earlier["date"]))


def cost(model: str | None, usage: Mapping[str, Any], early_share: float = 0.0) -> float:
    """USD for one usage dict (input_tokens, cache_creation_input_tokens, cache_read_input_tokens,
    output_tokens). When usage.cache_creation splits the writes, 1-hour writes are priced at the
    1-hour rate; every other written token at the 5-minute rate. `early_share` (0-1) is the part of
    the usage from before the model's [before] date: its rates are blended with the earlier ones."""
    rates: dict[str, Any] = dict(table()["models"][tier(model)])
    earlier = rates.pop("before", None)
    if earlier and early_share:
        for key, old in earlier.items():
            if key != "date":
                rates[key] = old * early_share + rates[key] * (1 - early_share)
    created = int(usage.get("cache_creation_input_tokens") or 0)
    split = usage.get("cache_creation")
    one_hour = int(split.get("ephemeral_1h_input_tokens") or 0) if isinstance(split, dict) else 0
    one_hour = min(one_hour, created)
    total: float = (
        int(usage.get("input_tokens") or 0) * rates["input"]
        + (created - one_hour) * rates["cache_write"]
        + one_hour * rates.get("cache_write_1h", rates["cache_write"])
        + int(usage.get("cache_read_input_tokens") or 0) * rates["cache_read"]
        + int(usage.get("output_tokens") or 0) * rates["output"]
        + int(usage.get("web_search_requests") or 0) * table().get("web_search_per_1000", 10.0) * 1000
    ) / PER
    return total
