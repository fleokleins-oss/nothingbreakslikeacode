"""Prepare trajectory payloads for the HTML renderer.
Each creature becomes a list of (x, y, z) points in WORLD coordinates,
plus a color keyed to fitness rank and an 'alive' flag."""
from __future__ import annotations
import json
from pathlib import Path

from ..config import CREATURES_FILE


def _read_creatures() -> list[dict]:
    if not CREATURES_FILE.exists():
        return []
    out = []
    for line in CREATURES_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def build_payload() -> dict:
    """
    Returns:
      {
        creatures: [
           {id, alive, fitness, metrics, points: [[x, y, z], ...]},
           ...
        ],
        stats: {tmin, tmax, ymin, ymax, zmin, zmax}
      }
    """
    rows = _read_creatures()
    creatures = []
    tmin = ymin = zmin = float("inf")
    tmax = ymax = zmax = float("-inf")

    for r in rows:
        pts = r.get("trajectory", [])
        if not pts:
            continue
        cleaned = []
        for p in pts:
            if not isinstance(p, (list, tuple)) or len(p) < 3:
                continue
            x, y, z = float(p[0]), float(p[1]), float(p[2])
            cleaned.append([x, y, z])
            tmin = min(tmin, x); tmax = max(tmax, x)
            ymin = min(ymin, y); ymax = max(ymax, y)
            zmin = min(zmin, z); zmax = max(zmax, z)
        if not cleaned:
            continue
        creatures.append({
            "id": r.get("genome_id", ""),
            "alive": bool(r.get("alive", False)),
            "fitness": float(r.get("fitness", 0.0)),
            "metrics": r.get("metrics", {}),
            "points": cleaned,
        })

    if tmin == float("inf"):
        tmin, tmax = 0.0, 1.0
        ymin, ymax = 0.0, 1.0
        zmin, zmax = 0.0, 1.0

    return {
        "creatures": creatures,
        "stats": {
            "tmin": tmin, "tmax": tmax,
            "ymin": ymin, "ymax": ymax,
            "zmin": zmin, "zmax": zmax,
        },
    }
