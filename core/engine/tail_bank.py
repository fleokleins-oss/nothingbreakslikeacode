"""
Tail bank — the reef's memory of extreme outcomes.

Every death and every large drawdown is written here with the genome that
produced it. The fitness function samples this bank at distance to penalize
genomes that live near graveyard clusters. This prevents tail underfitting:
the cost of rare disasters accumulates locally instead of being averaged away
over many backtests.
"""
from __future__ import annotations
import json
import time
from pathlib import Path

from ..config import (TAIL_BANK_FILE, TAIL_BANK_MIN_EVENTS,
                      TAIL_DIST_THRESHOLD)
from ..creatures.genes import normalized_distance, GENE_BOUNDS


_CACHE: dict = {"mtime": None, "events": []}


def log_event(event: dict) -> None:
    """Append one event as JSONL. Required keys: type, genes; recommended:
    severity_decimal (fractional loss), ts_ms, genome_id."""
    event.setdefault("ts_ms", int(time.time() * 1000))
    TAIL_BANK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TAIL_BANK_FILE, "a") as f:
        f.write(json.dumps(event, default=str) + "\n")


def load(refresh: bool = False) -> list[dict]:
    """Load the bank, cached by mtime for cheap re-reads inside a loop."""
    global _CACHE
    if not TAIL_BANK_FILE.exists():
        return []
    mt = TAIL_BANK_FILE.stat().st_mtime
    if not refresh and mt == _CACHE["mtime"]:
        return _CACHE["events"]
    events: list[dict] = []
    try:
        for line in TAIL_BANK_FILE.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return _CACHE["events"]
    _CACHE = {"mtime": mt, "events": events}
    return events


def tail_penalty(genes: dict,
                 bank: list[dict] | None = None,
                 threshold: float = TAIL_DIST_THRESHOLD) -> float:
    """
    Return decimal penalty (subtractable from log-growth) based on proximity
    to graveyard events. 0 when bank is small, or when genome is far from
    every event.

        penalty = Σ_events (1 - d/threshold) * severity
            for events with d < threshold
    """
    if bank is None:
        bank = load()
    if len(bank) < TAIL_BANK_MIN_EVENTS:
        return 0.0
    pen = 0.0
    for ev in bank:
        eg = ev.get("genes")
        if not isinstance(eg, dict):
            continue
        d = normalized_distance(genes, eg, GENE_BOUNDS)
        if d >= threshold or d == float("inf"):
            continue
        sev = float(ev.get("severity_decimal") or 0.0)
        if sev <= 0:
            continue
        pen += (1.0 - d / threshold) * sev
    return pen


def summarize(bank: list[dict] | None = None) -> dict:
    if bank is None:
        bank = load()
    deaths = sum(1 for e in bank if e.get("type") == "death")
    dds    = sum(1 for e in bank if e.get("type") == "drawdown")
    gains  = sum(1 for e in bank if e.get("type") == "gain")
    return {"total": len(bank), "deaths": deaths,
            "drawdowns": dds, "gains": gains}
