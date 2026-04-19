"""N2 Popper config — champion só é champion se passar 5 gates.

Gauntlet (Popperian: a edge só existe se sobrevive à falsificação):
  1. N trades ≥ MIN_TRADES
  2. net_bps_per_day ≥ MIN_NET_BPS_DAY
  3. OOS sharpe / train sharpe ≥ MIN_OOS_RATIO
  4. Calmar-like (final_equity/max_dd) ≥ MIN_CALMAR_LIKE
  5. Distinct regimes ≥ MIN_DISTINCT_REGIMES

Gates mais duros que N1 por design — N2 existe pra filtrar sorte.
"""
import os

COLONY_NAME = "n2_popper"
PARADIGM = "popperian_gauntlet"

# Gauntlet enabled
GAUNTLET_ENABLED = True
REQUIRE_GAUNTLET_FOR_EMPEROR = True

# Gate thresholds (same as motor_feynman_v3 defaults — proven)
FEE_BPS_ROUNDTRIP = 20.0
MIN_TRADES         = int(os.getenv("N2_MIN_TRADES", "30"))
MIN_NET_BPS_DAY    = float(os.getenv("N2_MIN_NET_BPS_DAY", "5.0"))
MIN_OOS_RATIO      = float(os.getenv("N2_MIN_OOS_RATIO", "0.5"))
MIN_CALMAR_LIKE    = float(os.getenv("N2_MIN_CALMAR", "2.0"))
MIN_DISTINCT_REGIMES = int(os.getenv("N2_MIN_REGIMES", "2"))

# OOS split — last 30% of ticks are OOS
OOS_SPLIT_FRAC = 0.30

# N2 defaults — same pop/ticks/gens as N1 by default (same compute budget
# for fair comparison). Differ from N1 only via gates.
DEFAULT_POP   = int(os.getenv("N2_POP", "96"))
DEFAULT_TICKS = int(os.getenv("N2_TICKS", "50000"))
DEFAULT_GENS  = int(os.getenv("N2_GENS", "20"))
DEFAULT_SEED  = int(os.getenv("N2_SEED", "13"))   # different seed from N1

SYMBOLS = os.getenv("N2_SYMBOLS", "ADAUSDT,INJUSDT,OPUSDT").split(",")
CYCLE_PAUSE_SEC = int(os.getenv("N2_CYCLE_PAUSE", "60"))
