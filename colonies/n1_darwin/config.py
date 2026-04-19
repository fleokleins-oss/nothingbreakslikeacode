"""N1 Darwin config.

No gauntlet. Pure fitness. Serves as baseline / control group for the
Galápagos test vs N2 Popper.

Override defaults via env REEF_POP, REEF_TICKS, REEF_GENS, REEF_SYMBOLS.
"""
import os

# Identity
COLONY_NAME = "n1_darwin"
PARADIGM = "darwin_pure"

# Gauntlet DISABLED for N1 (that's the point)
GAUNTLET_ENABLED = False
REQUIRE_GAUNTLET_FOR_EMPEROR = False

# N1-specific defaults (can still be overridden by env)
DEFAULT_POP    = int(os.getenv("N1_POP", "96"))
DEFAULT_TICKS  = int(os.getenv("N1_TICKS", "50000"))
DEFAULT_GENS   = int(os.getenv("N1_GENS", "20"))
DEFAULT_SEED   = int(os.getenv("N1_SEED", "7"))

# Symbols rotation — N1 cycles through these
SYMBOLS = os.getenv("N1_SYMBOLS", "ADAUSDT,INJUSDT,OPUSDT").split(",")

# Pause between cycles (seconds) when running as service
CYCLE_PAUSE_SEC = int(os.getenv("N1_CYCLE_PAUSE", "60"))
