"""Persistent aggregate usage counters for completed engine runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anyio

_PATH = Path.home() / ".tunapi" / "usage.json"
_LOCK = anyio.Lock()
_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "thinking_tokens",
    "cached_input_tokens",
    "cache_read_tokens",
    "cache_creation_input_tokens",
)


def _number(mapping: dict[str, Any], key: str) -> float:
    value = mapping.get(key, 0)
    return float(value) if isinstance(value, int | float) else 0.0


def _payload(usage: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(usage, dict):
        return {}
    nested = usage.get("usage")
    if isinstance(nested, dict):
        return usage | nested
    return usage


def _load() -> dict[str, Any]:
    try:
        data = json.loads(_PATH.read_text())
        return data if isinstance(data, dict) else {"version": 1, "engines": {}}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"version": 1, "engines": {}}


async def record_usage(
    engine: str, usage: dict[str, Any] | None, *, elapsed_seconds: float
) -> None:
    """Add one completed run to the aggregate counters."""
    values = _payload(usage)
    async with _LOCK:
        data = _load()
        engines = data.setdefault("engines", {})
        stats = engines.setdefault(engine, {})
        stats["runs"] = int(stats.get("runs", 0)) + 1
        stats["elapsed_seconds"] = float(stats.get("elapsed_seconds", 0)) + max(
            elapsed_seconds, 0
        )
        for key in _TOKEN_KEYS:
            amount = _number(values, key)
            if amount:
                stats[key] = float(stats.get(key, 0)) + amount
        total = _number(values, "total_tokens")
        if not total:
            total = _number(values, "input_tokens") + _number(values, "output_tokens")
        if total:
            stats["total_tokens"] = float(stats.get("total_tokens", 0)) + total
        cost = _number(values, "total_cost_usd") or _number(values, "cost_usd")
        if cost:
            stats["cost_usd"] = float(stats.get("cost_usd", 0)) + cost

        _PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = _PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        temporary.replace(_PATH)


async def usage_snapshot() -> dict[str, dict[str, Any]]:
    """Return a copy of the aggregate engine counters."""
    async with _LOCK:
        engines = _load().get("engines", {})
        if not isinstance(engines, dict):
            return {}
        return {
            str(engine): dict(stats)
            for engine, stats in engines.items()
            if isinstance(stats, dict)
        }
