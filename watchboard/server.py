"""
Reef Citadel Watchboard — FastAPI dashboard on port 8090.

Serves a minimal HTML dashboard + JSON endpoints comparing N1/N2/N3:

  GET /                — HTML dashboard (dark neon theme)
  GET /api/status      — health + uptime of each colony
  GET /api/champions   — current champion per colony
  GET /api/emperors    — current emperors (joias) per colony
  GET /api/gauntlet    — last 50 N2 gauntlet attempts
  GET /api/verdicts    — last 50 N3 verdicts
  GET /reef3d          — proxy to unified reef3d HTML

No auth. Binds 127.0.0.1:8090 by default (LAN access via Tailscale).
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from typing import Optional

# Import with graceful fallback so the file can be imported without fastapi
try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config import STATE_ROOT_ALL


PORT = int(os.getenv("REEF_WATCHBOARD_PORT", "8090"))
HOST = os.getenv("REEF_WATCHBOARD_HOST", "127.0.0.1")
COLONIES = ("n1_darwin", "n2_popper", "n3_institutional")


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.load(open(path))
    except Exception:
        return None


def _tail_jsonl(path: Path, n: int = 50) -> list:
    if not path.exists():
        return []
    try:
        lines = path.read_text().splitlines()
        out = []
        for ln in lines[-n:]:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return out
    except Exception:
        return []


def status() -> dict:
    result = {}
    for c in COLONIES:
        root = STATE_ROOT_ALL / c
        champ_f = root / "champion.json"
        rep_f = root / "report.json"
        mtime = None
        if rep_f.exists():
            mtime = rep_f.stat().st_mtime
        elif champ_f.exists():
            mtime = champ_f.stat().st_mtime
        result[c] = {
            "exists": root.exists(),
            "last_report_ts": mtime,
            "age_sec": (time.time() - mtime) if mtime else None,
            "has_champion": champ_f.exists(),
        }
    return result


def champions() -> dict:
    out = {}
    for c in COLONIES:
        champ = _read_json(STATE_ROOT_ALL / c / "champion.json")
        if champ:
            out[c] = {
                "fitness": champ.get("fitness"),
                "genome_id": champ.get("genome", {}).get("genome_id"),
                "metrics": champ.get("metrics"),
                "genes": champ.get("genome", {}).get("genes"),
                "components": champ.get("components"),
            }
        else:
            out[c] = None
    return out


def emperors() -> dict:
    out = {}
    for c in COLONIES:
        emps_f = STATE_ROOT_ALL / c / "joias" / "emperors.json"
        data = _read_json(emps_f)
        out[c] = data if data else {}
    return out


def gauntlet_audit() -> list:
    return _tail_jsonl(STATE_ROOT_ALL / "n2_popper" / "gauntlet.jsonl", n=50)


def verdicts_n3() -> list:
    return _tail_jsonl(STATE_ROOT_ALL / "n3_institutional" / "verdicts.jsonl", n=50)


# ─── HTML dashboard ────────────────────────────────────────────────────

DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>Reef Citadel — Watchboard</title>
<style>
  :root { --bg:#070a0f; --fg:#cfd6dd; --grid:#1a2030; --accent:#7fe3ff;
          --n1:#6fff9a; --n2:#6fc3ff; --n3:#ffd267; --warn:#ff6b6b; }
  * { box-sizing: border-box; }
  body { margin:0; background: var(--bg); color: var(--fg);
         font-family: ui-monospace, SFMono-Regular, monospace; font-size:13px;
         padding: 16px; }
  h1 { color: var(--accent); font-size: 16px; margin: 0 0 12px; letter-spacing: 0.1em; }
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
  .card { border: 1px solid var(--grid); padding: 12px 14px; background: rgba(255,255,255,0.02); }
  .card h2 { margin: 0 0 8px; font-size: 13px; letter-spacing: 0.05em; }
  .n1 h2 { color: var(--n1); }
  .n2 h2 { color: var(--n2); }
  .n3 h2 { color: var(--n3); }
  .kv { display: grid; grid-template-columns: 130px 1fr; gap: 4px 12px; font-size: 12px; }
  .kv dt { color: #8799ab; }
  .kv dd { margin: 0; font-variant-numeric: tabular-nums; }
  .dead { color: var(--warn); }
  .alive { color: var(--n1); }
  .pass { color: var(--n2); }
  .fail { color: var(--warn); }
  .row { display: flex; gap: 16px; margin-top: 12px; align-items: center; }
  .stale { color: #8799ab; font-size: 11px; }
  table { border-collapse: collapse; width: 100%; margin-top: 8px; font-size: 11px; }
  th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--grid); }
  th { color: #8799ab; font-weight: normal; }
  a { color: var(--accent); text-decoration: none; }
  .bar { height: 6px; background: var(--grid); margin-top: 8px; position: relative; }
  .bar > div { position: absolute; top: 0; left: 0; height: 100%; }
</style>
</head><body>
<h1>◆ REEF CITADEL — N1 vs N2 vs N3</h1>
<div class="row">
  <a href="/reef3d">open 3D unified view →</a>
  <a href="/api/status">status json</a>
  <a href="/api/gauntlet">gauntlet audit</a>
  <a href="/api/verdicts">N3 verdicts</a>
  <span class="stale" id="updated"></span>
</div>

<div class="grid" id="grid" style="margin-top:12px;"></div>

<script>
async function refresh() {
  const [status, champs, emps] = await Promise.all([
    fetch('/api/status').then(r=>r.json()),
    fetch('/api/champions').then(r=>r.json()),
    fetch('/api/emperors').then(r=>r.json()),
  ]);
  const grid = document.getElementById('grid');
  grid.innerHTML = '';
  for (const col of ['n1_darwin', 'n2_popper', 'n3_institutional']) {
    const s = status[col] || {};
    const c = champs[col];
    const e = emps[col] || {};
    const cls = col === 'n1_darwin' ? 'n1' : col === 'n2_popper' ? 'n2' : 'n3';
    const age = s.age_sec == null ? 'never' :
      s.age_sec < 60 ? `${Math.floor(s.age_sec)}s ago` :
      s.age_sec < 3600 ? `${Math.floor(s.age_sec/60)}m ago` :
      `${Math.floor(s.age_sec/3600)}h ago`;
    const chTxt = c ? `
      <dl class="kv">
        <dt>fitness</dt><dd>${(c.fitness||0).toFixed(4)}</dd>
        <dt>genome</dt><dd>${(c.genome_id||'?').slice(0,12)}</dd>
        <dt>n_trades</dt><dd>${c.metrics?.n_trades||0}</dd>
        <dt>win_rate</dt><dd>${((c.metrics?.win_rate||0)*100).toFixed(0)}%</dd>
        <dt>alive</dt><dd class="${c.metrics?.alive?'alive':'dead'}">${c.metrics?.alive?'✓':'✗'}</dd>
        <dt>regimes</dt><dd>${(c.metrics?.regimes_seen||[]).join(', ')||'—'}</dd>
        <dt>size_frac</dt><dd>${(c.genes?.size_frac||0).toFixed(3)}</dd>
        <dt>max_dd</dt><dd>${((c.metrics?.max_drawdown_frac||0)*100).toFixed(1)}%</dd>
        ${col==='n2_popper'||col==='n3_institutional'?
          `<dt>gauntlet</dt><dd class="${c.metrics?.gauntlet_passed?'pass':'fail'}">${c.metrics?.gauntlet_passed?'PASSED':'not yet'}</dd>`:''}
      </dl>` : '<div class="stale">no champion yet</div>';
    const empsTxt = Object.keys(e).length ?
      `<table><thead><tr><th>throne</th><th>fitness</th><th>genome</th></tr></thead><tbody>` +
      Object.entries(e).map(([t, v]) =>
        `<tr><td>${t}</td><td>${v?(v.fitness||0).toFixed(3):'—'}</td><td>${v?(v.genome_id||'').slice(0,8):'VACANT'}</td></tr>`
      ).join('') + '</tbody></table>' :
      '<div class="stale">no joias state yet</div>';
    grid.insertAdjacentHTML('beforeend', `
      <div class="card ${cls}">
        <h2>${col.toUpperCase()}</h2>
        <div class="stale">last report: ${age}</div>
        ${chTxt}
        <div style="margin-top:10px;">
          <div style="color:#8799ab;font-size:11px;margin-bottom:4px;">Thrones</div>
          ${empsTxt}
        </div>
      </div>
    `);
  }
  document.getElementById('updated').textContent = 'refreshed ' + new Date().toISOString().slice(11,19);
}
refresh();
setInterval(refresh, 15000);
</script>
</body></html>
"""


# ─── FastAPI app ──────────────────────────────────────────────────────

if HAS_FASTAPI:
    app = FastAPI(title="Reef Citadel Watchboard", version="1.0")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return DASHBOARD_HTML

    @app.get("/api/status")
    async def api_status():
        return JSONResponse(status())

    @app.get("/api/champions")
    async def api_champions():
        return JSONResponse(champions())

    @app.get("/api/emperors")
    async def api_emperors():
        return JSONResponse(emperors())

    @app.get("/api/gauntlet")
    async def api_gauntlet():
        return JSONResponse(gauntlet_audit())

    @app.get("/api/verdicts")
    async def api_verdicts():
        return JSONResponse(verdicts_n3())

    @app.get("/reef3d", response_class=HTMLResponse)
    async def reef3d_proxy():
        html_path = STATE_ROOT_ALL / "reef3d_unified.html"
        if not html_path.exists():
            raise HTTPException(404,
                                "reef3d_unified.html not yet generated — "
                                "start the reef-viz service or run "
                                "`python -m reef3d.render`")
        return html_path.read_text()


def main():
    if not HAS_FASTAPI:
        print("[watchboard] ERROR: fastapi/uvicorn not installed")
        print("  pip install fastapi uvicorn")
        sys.exit(1)
    print(f"[watchboard] starting on http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
