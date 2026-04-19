"""N3 Institutional config — VPS-side, strictest gates."""
import os

COLONY_NAME = "n3_institutional"
PARADIGM = "institutional_hard_gauntlet"

GAUNTLET_ENABLED = True
REQUIRE_GAUNTLET_FOR_EMPEROR = True

# Institutional-grade thresholds (stricter than N2)
FEE_BPS_ROUNDTRIP       = 20.0
MIN_TRADES              = int(os.getenv("N3_MIN_TRADES", "60"))
MIN_NET_BPS_DAY         = float(os.getenv("N3_MIN_NET_BPS_DAY", "8.0"))
MIN_OOS_RATIO           = float(os.getenv("N3_MIN_OOS_RATIO", "0.7"))
MIN_CALMAR_LIKE         = float(os.getenv("N3_MIN_CALMAR", "3.0"))
MIN_DISTINCT_REGIMES    = int(os.getenv("N3_MIN_REGIMES", "3"))
OOS_SPLIT_FRAC          = 0.30

# N3 runs LESS frequently — its job is to VALIDATE, not explore.
# Slower cycle, larger tick budget (more data = stricter test).
DEFAULT_POP   = int(os.getenv("N3_POP", "64"))
DEFAULT_TICKS = int(os.getenv("N3_TICKS", "100000"))
DEFAULT_GENS  = int(os.getenv("N3_GENS", "10"))
DEFAULT_SEED  = int(os.getenv("N3_SEED", "31"))

SYMBOLS = os.getenv("N3_SYMBOLS", "ADAUSDT,INJUSDT,OPUSDT").split(",")
CYCLE_PAUSE_SEC = int(os.getenv("N3_CYCLE_PAUSE", "1800"))  # 30min between cycles

# Path where notebook → VPS sync drops champions for revalidation
# (rsync destination on VPS: ~/reef_citadel/.state/inbox/)
INBOX_DIR = os.getenv("N3_INBOX", "./reef_citadel/.state/inbox")
