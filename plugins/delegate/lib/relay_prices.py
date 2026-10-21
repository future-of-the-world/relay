"""Tokens to money. The price table is prices.toml at the repository root."""

import os

from relay_config import ROOT, read_toml

_TABLE = None


def table():
    global _TABLE
    if _TABLE is None:
        path = os.environ.get("RELAY_PRICES") or os.path.join(ROOT, "prices.toml")
        if not os.path.isfile(path):
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices.toml")
        _TABLE = read_toml(path)
    return _TABLE


def tier(model):
    """'opus', 'sonnet', 'haiku' or 'default' for a model id or alias."""
    name = (model or "").lower()
    keys = sorted((k for k in table()["models"] if k != "default"), key=len, reverse=True)
    for key in keys:
        if key in name:
            return key
    return "default"


def cost(model, usage):
    """USD for one usage dict (input_tokens, cache_creation_input_tokens, cache_read_input_tokens, output_tokens)."""
    rates = table()["models"][tier(model)]
    per = 1_000_000
    return (
        usage.get("input_tokens", 0) * rates["input"]
        + usage.get("cache_creation_input_tokens", 0) * rates["cache_write"]
        + usage.get("cache_read_input_tokens", 0) * rates["cache_read"]
        + usage.get("output_tokens", 0) * rates["output"]
    ) / per
