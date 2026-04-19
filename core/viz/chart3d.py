"""
Render a single standalone HTML file with three.js from unpkg.
No Python 3D dep required — opens in any browser.

Layout:
  X axis = tick
  Y axis = capital (USD)
  Z axis = execution pressure (decimal drag, bigger = more lossy paths)

Each creature is a polyline. Color: green→red mapped by fitness rank.
Dead creatures faded. Book surface rendered as a wireframe below the
creatures (same X axis, Y = mid_price level, vertical Z separation).
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np

from ..config import VIZ_HTML
from . import trajectory, book_surface


HTML_TEMPLATE = """<!doctype html>
<html><head>
<meta charset="utf-8">
<title>Encruzilhada3D — Reef</title>
<style>
  body { margin:0; background:#070a0f; color:#cfd6dd; font-family: ui-monospace, monospace; }
  #info { position:absolute; top:10px; left:10px; padding:8px 12px;
          background:rgba(0,0,0,0.55); border:1px solid #2a3340; max-width:360px;
          font-size: 12px; line-height: 1.5; z-index:2; }
  #info b { color:#7fe3ff; }
  #hud  { position:absolute; bottom:10px; left:10px; padding:6px 10px;
          background:rgba(0,0,0,0.55); border:1px solid #2a3340;
          font-size: 11px; z-index:2; }
  canvas { display:block; }
</style>
</head><body>
<div id="info">
  <b>Encruzilhada3D — Reef</b><br>
  X = tick &nbsp; Y = capital (USD) &nbsp; Z = exec pressure<br>
  <span id="creature-count"></span><br>
  <span id="champion"></span>
</div>
<div id="hud">mouse: drag=rotate · right-drag=pan · wheel=zoom</div>
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
const surface = payload.surface || null;
const champion = payload.champion || null;

document.getElementById('creature-count').textContent =
  `creatures: ${creatures.length}  alive: ${creatures.filter(c=>c.alive).length}`;
if (champion) {
  document.getElementById('champion').textContent =
    `champion: ${champion.genome?.genome_id || '?'}  fit=${(champion.fitness||0).toFixed(3)}  ` +
    `cap=${(champion.metrics?.final_capital||0).toFixed(2)}  ` +
    `trades=${champion.metrics?.n_trades||0}`;
}

const W = window.innerWidth, H = window.innerHeight;
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x070a0f);
const camera = new THREE.PerspectiveCamera(55, W/H, 0.1, 10000);
camera.position.set(60, 40, 60);
const renderer = new THREE.WebGLRenderer({antialias:true});
renderer.setSize(W, H);
document.body.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

// Axes (50-unit world cube centered at origin)
const S = 50;
function axes() {
  const mat = new THREE.LineBasicMaterial({color:0x444d57});
  for (let i=-S; i<=S; i+=10) {
    const g = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-S,0,i), new THREE.Vector3(S,0,i)]);
    scene.add(new THREE.Line(g, mat));
    const g2 = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(i,0,-S), new THREE.Vector3(i,0,S)]);
    scene.add(new THREE.Line(g2, mat));
  }
  const arrow = (from, to, color) => {
    scene.add(new THREE.ArrowHelper(
      to.clone().sub(from).normalize(),
      from, from.distanceTo(to), color, 2, 1));
  };
  arrow(new THREE.Vector3(-S,0,-S), new THREE.Vector3(S,0,-S), 0xff5555); // X
  arrow(new THREE.Vector3(-S,0,-S), new THREE.Vector3(-S,S,-S), 0x55ff7f); // Y
  arrow(new THREE.Vector3(-S,0,-S), new THREE.Vector3(-S,0,S), 0x55a0ff); // Z
}
axes();

// Normalize (x, y, z) into [-S, S]
function mapX(x) { return ((x - stats.tmin) / Math.max(1e-9, stats.tmax-stats.tmin) - 0.5) * 2*S; }
function mapY(y) { return ((y - stats.ymin) / Math.max(1e-9, stats.ymax-stats.ymin)) * S; }
function mapZ(z) { return ((z - stats.zmin) / Math.max(1e-9, stats.zmax-stats.zmin) - 0.5) * 2*S; }

// Rank creatures by fitness for coloring
const sorted = [...creatures].sort((a,b)=>b.fitness - a.fitness);
const rankOf = new Map();
sorted.forEach((c,i)=>rankOf.set(c.id, i));

function colorFor(c) {
  const r = rankOf.get(c.id) ?? 0;
  const t = creatures.length > 1 ? r/(creatures.length-1) : 0; // 0=best, 1=worst
  // best = green, worst = red, linear in HSL
  const h = (1 - t) * 0.33; // 0.33 green .. 0 red
  const col = new THREE.Color();
  col.setHSL(h, 0.9, c.alive ? 0.55 : 0.25);
  return col;
}

for (const c of creatures) {
  const pts = c.points.map(p => new THREE.Vector3(mapX(p[0]), mapY(p[1]), mapZ(p[2])));
  const geo = new THREE.BufferGeometry().setFromPoints(pts);
  const col = colorFor(c);
  const mat = new THREE.LineBasicMaterial({color: col,
     transparent:true, opacity: c.alive ? 0.9 : 0.35});
  scene.add(new THREE.Line(geo, mat));
  // Death marker
  if (!c.alive && pts.length) {
    const last = pts[pts.length-1];
    const sp = new THREE.Mesh(
      new THREE.SphereGeometry(0.6, 8, 8),
      new THREE.MeshBasicMaterial({color: 0xff2a3f}));
    sp.position.copy(last);
    scene.add(sp);
  }
}

// Book surface (optional)
if (surface) {
  const nt = surface.t.length, np = surface.price_levels.length;
  const verts = [];
  for (let ti=0; ti<nt; ti++) {
    for (let pi=0; pi<np; pi++) {
      const t = surface.t[ti];
      const midRel = surface.price_levels[pi];
      const mid = surface.mid_per_t[ti] * (1 + midRel);
      const z = surface.Z[ti][pi];
      verts.push(mapX(t), mapY(mid), mapZ(stats.zmin + (z/6)*(stats.zmax-stats.zmin)));
    }
  }
  const idx = [];
  for (let ti=0; ti<nt-1; ti++) {
    for (let pi=0; pi<np-1; pi++) {
      const a = ti*np + pi;
      const b = (ti+1)*np + pi;
      const c = (ti+1)*np + (pi+1);
      const d = ti*np + (pi+1);
      idx.push(a,b,c, a,c,d);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  const m = new THREE.MeshBasicMaterial({color:0x1a4a7a, wireframe:true, transparent:true, opacity:0.25});
  scene.add(new THREE.Mesh(g, m));
}

window.addEventListener('resize', ()=>{
  camera.aspect = window.innerWidth/window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
function loop() {
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(loop);
}
loop();
</script>
</body></html>
"""


def render(prices: np.ndarray | None = None,
           champion: dict | None = None,
           out_path: Path | None = None) -> Path:
    out_path = out_path or VIZ_HTML
    payload = trajectory.build_payload()
    if prices is not None and len(prices) > 100:
        payload["surface"] = book_surface.build_payload(prices)
    if champion is not None:
        payload["champion"] = champion
    html = HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, default=str))
    out_path.write_text(html)
    return out_path
