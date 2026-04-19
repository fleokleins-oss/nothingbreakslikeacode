"""
Central configuration — COLONY-AWARE via env var.

Every colony (n1_darwin, n2_popper, n3_institutional) runs identical core
code but writes its state to a separate directory under STATE_ROOT/<colony>.
This is the single pivot that lets 2 (or 3) populations coexist on the
same data + engine without stomping each other.

Dimensional conventions (unchanged from enc_v2):
  - DECIMAL is the base unit (0.01 = 1%)
  - bps only appear in parquet labels / gauntlet reports

Environment variables:
  REEF_COLONY          colony name (default: "n1_darwin")
                       controls STATE_ROOT subdir and service id
  REEF_DATA_ROOT       parquet data directory
                       (also accepted: APEX_DATA_ROOT for compat)
  REEF_STATE_ROOT      state root (default: <pkg>/.state)
                       Each colony gets <root>/<colony>/ subdir.
  REEF_SEED            RNG seed (optional)

Operational defaults (all overridable via env):
  REEF_POP     default population per episode      (64)
  REEF_TICKS   default episode tick budget         (3000)
  REEF_GENS    default generations per cycle       (5)
  REEF_MAX_ROWS  parquet rows cap                  (20000)
  REEF_SYMBOLS comma-separated symbols list        ("ADAUSDT")
"""
from __future__ import annotations
import os
from pathlib import Path

# -----------------------------------------------------------------------------
# Colony identity
# -----------------------------------------------------------------------------
COLONY = os.getenv("REEF_COLONY", "n1_darwin")

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
# Data root (accepts old APEX_DATA_ROOT var for backwards compat)
_data_env = os.getenv("REEF_DATA_ROOT") or os.getenv("APEX_DATA_ROOT") or "./apex_data"
DATA_ROOT = Path(_data_env).expanduser().resolve()

# Per-colony state dir: <state_root>/<colony>/
_default_state_root = Path(__file__).resolve().parent.parent / ".state"
STATE_ROOT_ALL = Path(os.getenv("REEF_STATE_ROOT", str(_default_state_root))).expanduser().resolve()
STATE_ROOT = STATE_ROOT_ALL / COLONY
STATE_ROOT.mkdir(parents=True, exist_ok=True)

CREATURES_FILE = STATE_ROOT / "creatures.jsonl"
TAIL_BANK_FILE = STATE_ROOT / "tail_bank.jsonl"
CHAMPION_FILE  = STATE_ROOT / "champion.json"
HISTORY_FILE   = STATE_ROOT / "history.jsonl"
REPORT_FILE    = STATE_ROOT / "report.json"
VIZ_HTML       = STATE_ROOT / "reef3d.html"
GAUNTLET_FILE  = STATE_ROOT / "gauntlet.jsonl"  # N2 only: every attempt logged

# -----------------------------------------------------------------------------
# Economic invariants (single source of truth)
# -----------------------------------------------------------------------------
INITIAL_CAPITAL       = 100.0
DEATH_FRAC            = 0.50      # dies below INITIAL * DEATH_FRAC
DRAWDOWN_EVENT_FRAC   = 0.10
GAIN_EVENT_FRAC       = 0.20
KELLY_CAP             = 0.25
SLIPPAGE_K            = 0.5
DEPTH_PROXY_WINDOW    = 50
DECISION_DELAY_TICKS  = 1
CROWDING_HALF_LIFE    = 20
TRADING_DAYS_PER_YEAR = 365
TAIL_DIST_THRESHOLD   = 0.15
TAIL_BANK_MIN_EVENTS  = 10

# -----------------------------------------------------------------------------
# Engine defaults
# -----------------------------------------------------------------------------
DEFAULT_POPULATION    = int(os.getenv("REEF_POP", "64"))
DEFAULT_EPISODE_TICKS = int(os.getenv("REEF_TICKS", "3000"))
DEFAULT_GENERATIONS   = int(os.getenv("REEF_GENS", "5"))
DEFAULT_MAX_ROWS      = int(os.getenv("REEF_MAX_ROWS", "20000"))
DEFAULT_SYMBOLS       = os.getenv("REEF_SYMBOLS", "ADAUSDT").split(",")
RNG_SEED              = int(os.getenv("REEF_SEED", "0")) or None

# -----------------------------------------------------------------------------
# Colony-specific knobs (overridden by colonies/<name>/config.py)
# -----------------------------------------------------------------------------
# Default: N1 Darwin paradigm — no gauntlet gate, pure fitness ranking.
GAUNTLET_ENABLED = os.getenv("REEF_GAUNTLET", "0") == "1"
