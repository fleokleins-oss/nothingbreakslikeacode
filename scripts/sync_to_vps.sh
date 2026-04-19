#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# sync_to_vps.sh — rsync champion files from notebook's N1+N2 to VPS's N3 inbox.
#
# Runs hourly via cron OR systemd timer. Sends genomes that passed local
# gauntlets (or just looked good) to the VPS for revalidation on harder gates.
#
# Usage:
#   bash scripts/sync_to_vps.sh           # one-shot sync
#
# Env (edit defaults here or export):
#   VPS_HOST          SSH alias or user@host         (default: apex)
#   VPS_INBOX         remote inbox dir               (default: ~/reef_citadel/.state/inbox)
#   REEF_STATE_ROOT   local state root               (default: ~/reef_citadel/.state)
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

VPS_HOST="${VPS_HOST:-apex}"
VPS_INBOX="${VPS_INBOX:-reef_citadel/.state/inbox}"   # relative to VPS home
LOCAL_STATE="${REEF_STATE_ROOT:-$HOME/reef_citadel/.state}"
STAMP=$(date +%Y%m%d_%H%M%S)

if ! command -v rsync >/dev/null 2>&1; then
    echo "✗ rsync not installed" >&2
    exit 1
fi

# Ensure VPS inbox exists
ssh "$VPS_HOST" "mkdir -p \"$VPS_INBOX\"" || {
    echo "✗ cannot reach VPS $VPS_HOST — check SSH alias / network"
    exit 1
}

echo "▸ syncing champions from notebook → $VPS_HOST:$VPS_INBOX"

sent=0
for colony in n1_darwin n2_popper; do
    champ="$LOCAL_STATE/$colony/champion.json"
    if [ ! -f "$champ" ]; then
        continue
    fi

    # Skip if file hasn't changed since last sync
    last_sent_marker="$LOCAL_STATE/$colony/.last_sent_to_vps"
    if [ -f "$last_sent_marker" ]; then
        champ_mtime=$(stat -c%Y "$champ" 2>/dev/null || stat -f%m "$champ")
        sent_mtime=$(stat -c%Y "$last_sent_marker" 2>/dev/null || stat -f%m "$last_sent_marker")
        if [ "$champ_mtime" -le "$sent_mtime" ]; then
            echo "  = $colony: no change, skip"
            continue
        fi
    fi

    # Copy with a source-tagged name (VPS can tell which colony sent it)
    remote_name="${colony}_${STAMP}.json"
    if rsync -qz "$champ" "$VPS_HOST:$VPS_INBOX/$remote_name"; then
        echo "  ✓ $colony → $remote_name"
        touch "$last_sent_marker"
        sent=$((sent + 1))
    else
        echo "  ✗ $colony rsync failed"
    fi
done

echo "▸ sync complete — $sent champion(s) sent"
