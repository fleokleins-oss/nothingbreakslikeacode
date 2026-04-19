#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# Reef Citadel installer — validates, tests, configures systemd.
#
# Usage:
#   bash install.sh                  # full install (prompts before systemd)
#   bash install.sh --smoke-only     # syntax + tests + render smoke
#   bash install.sh --no-systemd     # skip systemd install
#   bash install.sh --vps            # VPS mode (N3 service only)
#
# Env vars (all optional):
#   PROJECT_ROOT    where reef_citadel/ lives    (default: parent of this script)
#   PYTHON          python interpreter           (default: auto-detect)
#   REEF_DATA_ROOT  parquet data dir             (default: ~/apex_data)
#   REEF_STATE_ROOT state output dir             (default: ./reef_citadel/.state)
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; C='\033[0;36m'; N='\033[0m'
log()  { echo -e "${G}▸${N} $*"; }
warn() { echo -e "${Y}⚠${N} $*"; }
err()  { echo -e "${R}✗${N} $*" >&2; }
die()  { err "$*"; exit 1; }
hdr()  { echo -e "${C}═══${N} $*"; }

SMOKE_ONLY=0
NO_SYSTEMD=0
VPS_MODE=0
for arg in "$@"; do
    case "$arg" in
        --smoke-only) SMOKE_ONLY=1 ;;
        --no-systemd) NO_SYSTEMD=1 ;;
        --vps) VPS_MODE=1 ;;
        --help|-h)
            sed -n '3,14p' "$0"
            exit 0
            ;;
        *) warn "unknown arg: $arg" ;;
    esac
done

# Locate project root (where this script lives)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="${PROJECT_ROOT:-$SCRIPT_DIR}"
cd "$PROJECT_ROOT"

[ -d "core" ] || die "core/ not found — are you running from reef_citadel root?"

# ─── 1. Detect Python ──────────────────────────────────────────────────
hdr "1. Python"
pick_python() {
    for cand in "${PYTHON:-}" "$HOME/mfv3_venv/bin/python" "python3" "/usr/bin/python3"; do
        [ -z "$cand" ] && continue
        command -v "$cand" >/dev/null 2>&1 || [ -x "$cand" ] || continue
        if "$cand" -c 'import numpy, pandas, pyarrow' >/dev/null 2>&1; then
            echo "$cand"
            return 0
        fi
    done
    return 1
}
PY="$(pick_python)" || die "no python3 with numpy+pandas+pyarrow found"
log "python: $PY"
$PY --version

# ─── 2. Paths ──────────────────────────────────────────────────────────
hdr "2. Paths"
export REEF_DATA_ROOT="${REEF_DATA_ROOT:-$HOME/apex_data}"
export REEF_STATE_ROOT="${REEF_STATE_ROOT:-$PROJECT_ROOT/.state}"
log "PROJECT_ROOT=$PROJECT_ROOT"
log "REEF_DATA_ROOT=$REEF_DATA_ROOT  (exists: $([ -d "$REEF_DATA_ROOT" ] && echo yes || echo NO))"
log "REEF_STATE_ROOT=$REEF_STATE_ROOT"
mkdir -p "$REEF_STATE_ROOT"

if [ ! -d "$REEF_DATA_ROOT" ]; then
    warn "apex_data not found at $REEF_DATA_ROOT — engine will use synthetic tape"
fi

# ─── 3. Syntax check ───────────────────────────────────────────────────
hdr "3. Syntax check"
PYTHONPATH="$PROJECT_ROOT" $PY - << 'PYEOF'
import pathlib, py_compile, sys
errs = 0
py_files = [p for p in pathlib.Path(".").rglob("*.py") if ".state" not in str(p)]
for p in py_files:
    try:
        py_compile.compile(str(p), doraise=True)
    except py_compile.PyCompileError as e:
        print(f"SYNTAX ERROR: {p}")
        print(f"  {e}")
        errs += 1
print(f"✓ {len(py_files)} modules compiled cleanly")
sys.exit(1 if errs else 0)
PYEOF
log "syntax OK"

# ─── 4. Unit tests ─────────────────────────────────────────────────────
hdr "4. Unit tests"
PYTHONPATH="$PROJECT_ROOT" REEF_STATE_ROOT="/tmp/reef_install_tests_$$" \
    $PY -m unittest tests.test_core tests.test_colonies tests.test_viz_watchboard 2>&1 | tail -5
log "tests OK"

# ─── 5. Smoke run: tiny episode per colony ────────────────────────────
hdr "5. Smoke run (tiny episodes)"
if [ "$VPS_MODE" -eq 0 ]; then
    for colony in n1_darwin n2_popper; do
        log "smoke: $colony (pop=8 ticks=500 gens=1)"
        PYTHONPATH="$PROJECT_ROOT" \
        REEF_COLONY="$colony" \
        REEF_POP=8 REEF_TICKS=500 REEF_GENS=1 \
        REEF_STATE_ROOT="/tmp/reef_install_smoke_$$" \
        timeout 120 $PY - << PYEOF || warn "$colony smoke timeout/fail"
import os
os.environ["REEF_COLONY"] = "$colony"
# Import a minimal single-episode path
from core.engine.world3d import World3D
w = World3D(symbol="ADAUSDT", population=8, episode_ticks=500, seed=1)
evals = w.run_episode(gen=1)
print(f"  {len(evals)} creatures evaluated")
PYEOF
    done
    log "unified viz render..."
    PYTHONPATH="$PROJECT_ROOT" REEF_STATE_ROOT="/tmp/reef_install_smoke_$$" \
        $PY -m reef3d.render 2>&1 | tail -3
fi

[ $SMOKE_ONLY -eq 1 ] && { hdr "SMOKE-ONLY mode — done"; exit 0; }

# ─── 6. Systemd install ────────────────────────────────────────────────
hdr "6. Systemd"
if [ $NO_SYSTEMD -eq 1 ]; then
    warn "skipping systemd (--no-systemd)"
elif ! command -v systemctl >/dev/null 2>&1; then
    warn "systemctl not found — skipping"
else
    UNIT_DIR="$HOME/.config/systemd/user"
    mkdir -p "$UNIT_DIR"
    if [ "$VPS_MODE" -eq 1 ]; then
        UNITS=("reef-n3.service" "reef-viz.service" "reef-watchboard.service")
    else
        UNITS=("reef-n1.service" "reef-n2.service" "reef-joias.service"
               "reef-viz.service" "reef-watchboard.service")
    fi
    echo
    echo "Systemd units to install:"
    for u in "${UNITS[@]}"; do echo "  • $u"; done
    echo
    read -rp "Install and enable these? [y/N] " ans
    if [[ "$ans" =~ ^[Yy] ]]; then
        for u in "${UNITS[@]}"; do
            cp "systemd/$u" "$UNIT_DIR/"
            log "installed $u"
        done
        systemctl --user daemon-reload
        log "daemon-reload done"
        echo
        echo "To start:"
        for u in "${UNITS[@]}"; do
            echo "  systemctl --user enable --now $u"
        done
        echo
        echo "To monitor:"
        for u in "${UNITS[@]}"; do
            echo "  journalctl --user -u $u -f"
        done
    else
        warn "systemd skipped by user. Units available at systemd/ if you change your mind."
    fi
fi

# ─── 7. Summary ───────────────────────────────────────────────────────
hdr "INSTALLED"
echo
echo "Project:     $PROJECT_ROOT"
echo "State:       $REEF_STATE_ROOT"
echo "Data:        $REEF_DATA_ROOT"
echo
echo "Manual runs (for testing):"
echo "  PYTHONPATH=$PROJECT_ROOT $PY -m colonies.n1_darwin.run"
echo "  PYTHONPATH=$PROJECT_ROOT $PY -m colonies.n2_popper.run"
echo "  PYTHONPATH=$PROJECT_ROOT $PY -m reef3d.render"
echo "  PYTHONPATH=$PROJECT_ROOT $PY -m watchboard.server   # port 8090"
echo
echo "Dashboard (once running): http://127.0.0.1:8090"
echo
echo "Docs: CLAUDE.md  README.md"
