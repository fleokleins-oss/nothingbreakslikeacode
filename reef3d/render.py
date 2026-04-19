"""
Reef 3D unified renderer.

Reads creatures.jsonl from BOTH colonies (N1 + N2 on notebook, N3 if
present) and renders all trajectories in one HTML file. Each colony gets
a distinct color palette so you can see competition visually:

  N1 Darwin         — greens (pure fitness, no gauntlet)
  N2 Popper         — blues (gauntlet-validated)
  N3 Institutional  — golds (VPS-validated, harder gauntlet)

Dead creatures fade. Champions (top-1 per colony) render thicker.

Uses the same three.js HTML template as core.viz.chart3d but with
payload.creatures tagged by colony.
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path

from core.config import STATE_ROOT_ALL


OUTPUT_FILE = STATE_ROOT_ALL / "reef3d_unified.html"


HTML_TEMPLATE = """<!doctype html>
<html><head>
<meta charset="utf-8">
<title>Reef Citadel — N1/N2/N3</title>
<style>
  body { margin:0; background:#070a0f; color:#cfd6dd; font-family: ui-monospace, monospace; }
  #info { position:absolute; top:10px; left:10px; padding:10px 14px;
          background:rgba(0,0,0,0.70); border:1px solid #2a3340; max-width:420px;
          font-size: 12px; line-height: 1.6; z-index:2; }
  #info b.n1 { color:#6fff9a; }
  #info b.n2 { color:#6fc3ff; }
  #info b.n3 { color:#ffd267; }
  #hud  { position:absolute; bottom:10px; left:10px; padding:6px 10px;
          background:rgba(0,0,0,0.55); border:1px solid #2a3340;
          font-size: 11px; z-index:2; }
  canvas { display:block; }
</style>
</head><body>
<div id="info">
  <b>REEF CITADEL — UNIFIED VIEW</b><br>
  <span style="opacity:0.7">X = tick &nbsp; Y = capital (USD) &nbsp; Z = exec pressure</span><br>
  <b class="n1">N1 Darwin</b> (green): __N1_COUNT__<br>
  <b class="n2">N2 Popper</b> (blue):  __N2_COUNT__<br>
  <b class="n3">N3 Institutional</b> (gold): __N3_COUNT__<br>
  <span id="champions"></span>
</div>
<div id="hud">mouse: drag=rotate · right-drag=pan · wheel=zoom · updated __UPDATED__</div>
<script type="application/json" id="payload">__PAYLOAD__</script>
<script type="importmap">
{ "imports": {
  "three": "https://unpkg.com/three@0.161.0/build/three.module.js",
  "three/addons/": "https://unpkg.com/three@0.161.0/examples/jsm/"
}}
</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const payload = JSON.parse(document.getElementById('payload').textContent);
const creatures = payload.creatures || [];
const stats = payload.stats || {tmin:0,tmax:1,ymin:0,ymax:1,zmin:0,zmax:1};
const champions = payload.champions || {};

let champTxt = '';
for (const [col, ch] of Object.entries(champions)) {
  if (ch) {
    const cls = col === 'n1_darwin' ? 'n1' : col === 'n2_popper' ? 'n2' : 'n3';
    champTxt += `<b class="${cls}">${col}</b> champ: ${(ch.fitness||0).toFixed(3)} ` +
                `trades=${ch.n_trades||0}<br>`;
  }
}
document.getElementById('champions').innerHTML = champTxt;

const W = window.innerWidth, H = window.innerHeight;
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x070a0f);
const camera = new THREE.PerspectiveCamera(55, W/H, 0.1, 10000);
camera.position.set(80, 50, 80);
const renderer = new THREE.WebGLRenderer({antialias:true});
renderer.setSize(W, H);
document.body.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

const S = 50;
function axes() {
  const mat = new THREE.LineBasicMaterial({color:0x444d57});
  for (let i=-S; i<=S; i+=10) {
    const g1 = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-S,0,i), new THREE.Vector3(S,0,i)]);
    scene.add(new THREE.Line(g1, mat));
    const g2 = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(i,0,-S), new THREE.Vector3(i,0,S)]);
    scene.add(new THREE.Line(g2, mat));
  }
  const arrow = (from, to, color) => {
    scene.add(new THREE.ArrowHelper(to.clone().sub(from).normalize(), from, from.distanceTo(to), color, 2, 1));
  };
  arrow(new THREE.Vector3(-S,0,-S), new THREE.Vector3(S,0,-S), 0xff5555);
  arrow(new THREE.Vector3(-S,0,-S), new THREE.Vector3(-S,S,-S), 0x55ff7f);
  arrow(new THREE.Vector3(-S,0,-S), new THREE.Vector3(-S,0,S), 0x55a0ff);
}
axes();

function mapX(x) { return ((x - stats.tmin) / Math.max(1e-9, stats.tmax-stats.tmin) - 0.5) * 2*S; }
function mapY(y) { return ((y - stats.ymin) / Math.max(1e-9, stats.ymax-stats.ymin)) * S; }
function mapZ(z) { return ((z - stats.zmin) / Math.max(1e-9, stats.zmax-stats.zmin) - 0.5) * 2*S; }

const PALETTE = {
  n1_darwin:        {alive: 0x6fff9a, dead: 0x2d5038},
  n2_popper:        {alive: 0x6fc3ff, dead: 0x2d4a6b},
  n3_institutional: {alive: 0xffd267, dead: 0x6b5a2d},
};

for (const c of creatures) {
  const pal = PALETTE[c.colony] || PALETTE.n1_darwin;
  const color = c.alive ? pal.alive : pal.dead;
  const pts = c.points.map(p => new THREE.Vector3(mapX(p[0]), mapY(p[1]), mapZ(p[2])));
  const geo = new THREE.BufferGeometry().setFromPoints(pts);
  const mat = new THREE.LineBasicMaterial({color,
     transparent:true, opacity: c.alive ? (c.is_champion ? 1.0 : 0.75) : 0.20,
     linewidth: c.is_champion ? 3 : 1});
  scene.add(new THREE.Line(geo, mat));
  if (!c.alive && pts.length) {
    const last = pts[pts.length-1];
    const sp = new THREE.Mesh(new THREE.SphereGeometry(0.6, 8, 8),
                              new THREE.MeshBasicMaterial({color: 0xff2a3f}));
    sp.position.copy(last);
    scene.add(sp);
  }
  if (c.is_champion && pts.length) {
    const last = pts[pts.length-1];
    const cr = new THREE.Mesh(new THREE.ConeGeometry(1.2, 2.4, 8),
                              new THREE.MeshBasicMaterial({color}));
    cr.position.copy(last);
    cr.position.y += 2.5;
    scene.add(cr);
  }
}

window.addEventListener('resize', ()=>{
  camera.aspect = window.innerWidth/window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
function loop() { controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop); }
loop();
</script>
</body></html>
"""


def _load_colony_creatures(colony: str) -> tuple[list, dict | None]:
    """Return (creatures_list, champion_dict) for the colony."""
    state = STATE_ROOT_ALL / colony
    creatures_f = state / "creatures.jsonl"
    champion_f = state / "champion.json"
    creatures = []
    champ = None

    if creatures_f.exists():
        try:
            for line in creatures_f.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    creatures.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            print(f"[reef3d] err reading {creatures_f}: {e}")

    if champion_f.exists():
        try:
            champ = json.load(open(champion_f))
        except Exception:
            pass

    return creatures, champ


def build_payload() -> dict:
    payload_creatures = []
    champions = {}
    tmin = ymin = zmin = float("inf")
    tmax = ymax = zmax = float("-inf")

    for colony in ("n1_darwin", "n2_popper", "n3_institutional"):
        rows, champ = _load_colony_creatures(colony)
        if champ:
            champions[colony] = {
                "genome_id": champ.get("genome", {}).get("genome_id", "?"),
                "fitness": champ.get("fitness", 0),
                "n_trades": champ.get("metrics", {}).get("n_trades", 0),
            }
        champ_id = champ.get("genome", {}).get("genome_id") if champ else None

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
            gid = r.get("genome_id", "")
            payload_creatures.append({
                "id": gid,
                "colony": colony,
                "alive": bool(r.get("alive", False)),
                "fitness": float(r.get("fitness", 0.0)),
                "is_champion": gid == champ_id,
                "points": cleaned,
            })

    if tmin == float("inf"):
        tmin, tmax, ymin, ymax, zmin, zmax = 0.0, 1.0, 0.0, 1.0, 0.0, 1.0

    return {
        "creatures": payload_creatures,
        "stats": {"tmin": tmin, "tmax": tmax,
                  "ymin": ymin, "ymax": ymax,
                  "zmin": zmin, "zmax": zmax},
        "champions": champions,
    }


def render(output: Path | None = None) -> Path:
    output = output or OUTPUT_FILE
    payload = build_payload()
    n1 = sum(1 for c in payload["creatures"] if c["colony"] == "n1_darwin")
    n2 = sum(1 for c in payload["creatures"] if c["colony"] == "n2_popper")
    n3 = sum(1 for c in payload["creatures"] if c["colony"] == "n3_institutional")

    html = (HTML_TEMPLATE
            .replace("__PAYLOAD__", json.dumps(payload, default=str))
            .replace("__N1_COUNT__", str(n1))
            .replace("__N2_COUNT__", str(n2))
            .replace("__N3_COUNT__", str(n3))
            .replace("__UPDATED__", time.strftime("%Y-%m-%d %H:%M:%S")))
    output.write_text(html)
    return output


def service_loop(interval_sec: int = 600):
    """Run as systemd service: render every `interval_sec` seconds."""
    import signal
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *a: stop.__setitem__("flag", True))
    signal.signal(signal.SIGINT, lambda *a: stop.__setitem__("flag", True))

    print(f"[reef3d] starting — output={OUTPUT_FILE} interval={interval_sec}s")
    while not stop["flag"]:
        try:
            path = render()
            size = path.stat().st_size
            print(f"[reef3d] rendered {size} bytes → {path}")
        except Exception as e:
            print(f"[reef3d] render err: {e}")
        for _ in range(interval_sec):
            if stop["flag"]:
                break
            time.sleep(1)
    print("[reef3d] stopped")


if __name__ == "__main__":
    if os.getenv("REEF_VIZ_SERVICE", "0") == "1":
        service_loop(int(os.getenv("REEF_VIZ_INTERVAL", "600")))
    else:
        path = render()
        print(f"rendered → {path}")
