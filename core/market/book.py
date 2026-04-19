"""
Book ingestion — loads parquet trades files from APEX_DATA_ROOT / <symbol>.

We only have trade prints on disk, no L2 snapshots. We expose a `load()`
that returns a sorted (ts, price) numpy pair; the rest of the pipeline
treats this as mid. L2-like structure is *synthesized* in features.py and
simulator.py from local price dispersion — not faked, just derived.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

from ..config import DATA_ROOT, DEFAULT_MAX_ROWS


def _synth(symbol: str, n: int) -> pd.DataFrame:
    """Synthetic fallback when a symbol has no parquets. Lets the engine
    still run in environments without data. Clearly marked."""
    rng = np.random.default_rng(abs(hash(symbol)) % (2**32))
    drift = 0.00001
    vol = 0.002
    rets = rng.normal(drift, vol, size=n)
    prices = 100.0 * np.exp(np.cumsum(rets))
    ts = np.arange(n, dtype=np.int64) * 1000
    return pd.DataFrame({"ts": ts, "price": prices})


def load(symbol: str, max_rows: int = DEFAULT_MAX_ROWS) -> pd.DataFrame:
    """Return DataFrame with columns (ts int64 ms, price float), sorted by ts."""
    d: Path = DATA_ROOT / symbol
    frames = []
    if d.exists():
        for p in sorted(d.glob("trades_*.parquet")):
            try:
                frames.append(pd.read_parquet(p))
            except Exception:
                pass
    if frames:
        df = pd.concat(frames, ignore_index=True)
    else:
        df = _synth(symbol, max_rows)

    # Normalize column names
    if "price" not in df.columns:
        for cand in ("p", "close", "last"):
            if cand in df.columns:
                df = df.rename(columns={cand: "price"})
                break
    if "ts" not in df.columns:
        for cand in ("timestamp", "time", "T"):
            if cand in df.columns:
                df = df.rename(columns={cand: "ts"})
                break
    if "price" not in df.columns:
        raise RuntimeError(
            f"book.load({symbol}): missing 'price'; cols={list(df.columns)[:10]}"
        )
    if "ts" not in df.columns:
        df["ts"] = np.arange(len(df), dtype=np.int64) * 1000

    df = df.sort_values("ts").reset_index(drop=True)
    if len(df) > max_rows:
        step = max(1, len(df) // max_rows)
        df = df.iloc[::step].head(max_rows).reset_index(drop=True)
    return df[["ts", "price"]].copy()


def prices_array(df: pd.DataFrame) -> np.ndarray:
    return df["price"].to_numpy(dtype=float)
