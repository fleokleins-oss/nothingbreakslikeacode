"""Produce a JSON-serializable book-surface payload for the HTML viz."""
from __future__ import annotations
import numpy as np

from ..market.surface import build_surface


def build_payload(prices: np.ndarray,
                  grid_t: int = 50,
                  grid_p: int = 30) -> dict:
    s = build_surface(prices, grid_t=grid_t, grid_p=grid_p)
    return {
        "t": list(map(int, s["t"].tolist())),
        "price_levels": list(map(float, s["price_levels"].tolist())),
        "mid_per_t": list(map(float, s["mid_per_t"].tolist())),
        "Z": [list(map(float, row)) for row in s["Z"].tolist()],
    }
