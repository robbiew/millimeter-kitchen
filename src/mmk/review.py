"""A static review page per export, and an index over all exports.

`out/<kitchen stem>/index.html` shows the drawings, renders, an embedded
3D viewer, the runs, the purchase pack and its assumptions for one layout.
`out/index.html` lists every exported layout. Both are regenerated on every
export and carry the source file's hash; in the browser they fetch the
source and flag themselves stale if it has changed since. No server logic:
serve the repository root with `python -m http.server` and open out/.
"""

from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .edit import runs_summary
from .model import Kitchen
from .purchase import PurchasePack
from .rules import validate

THREE_VERSION = "0.170.0"

STYLE = """
:root{--ink:#18212A;--muted:#5C6975;--line:#D3DAE0;--ground:#F3F5F6;--paper:#fff;--accent:#1D5DA6;--warn:#A9681C;--warn-soft:#FBF0DF;--ok:#2E7D4F}
@media (prefers-color-scheme:dark){:root{--ink:#E5EBF0;--muted:#98A5B1;--line:#2A3540;--ground:#0F151B;--paper:#161E26;--accent:#7AB0EA;--warn:#E0A75A;--warn-soft:#33261A;--ok:#7BC79A}}
*{box-sizing:border-box}body{margin:0;background:var(--ground);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding-inline:16px;padding-block:0 48px}
.page{max-width:1200px;margin:0 auto}header{padding-block:28px 12px}h1{font-size:28px;margin:0 0 4px}h2{font-size:20px;margin:0 0 10px}h3{font-size:16px;margin:16px 0 6px}
.meta{color:var(--muted);font-size:13px}.sheet{background:var(--paper);border:1px solid var(--line);padding:18px 20px;margin-top:16px}
.banner{display:none;background:var(--warn-soft);color:var(--warn);border-left:4px solid var(--warn);padding:10px 14px;margin-top:12px}.banner.show{display:block}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:16px}figure{margin:0}figure img{width:100%;height:auto;border:1px solid var(--line);background:#fff}
figcaption{font-size:13px;color:var(--muted);margin-top:4px}table{border-collapse:collapse;width:100%;font-size:13.5px}th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.tag{font-size:11px;padding:1px 6px;border-radius:2px;background:var(--warn-soft);color:var(--warn);white-space:nowrap}
.tag.ok{background:transparent;color:var(--ok);border:1px solid var(--ok)}#viewer{width:100%;aspect-ratio:16/10;max-width:100%;border:1px solid var(--line);background:#e9ebee;position:relative}
#viewer canvas{display:block;width:100%;height:100%}#cams{position:absolute;left:10px;top:10px}#cams button{margin-right:6px}code{background:var(--ground);padding:1px 5px;border-radius:3px;font-size:.9em}
ul{margin:6px 0;padding-left:20px}a{color:var(--accent)}.wrap{overflow-x:auto}.stale-ok{color:var(--ok)}
"""


def _esc(s: Any) -> str:
    return html.escape(str(s))


def _hash_script(source_rel: str, expected: str) -> str:
    return f"""
<script>
(async () => {{
  const el = document.getElementById('stale');
  try {{
    const r = await fetch({json.dumps(source_rel)}, {{cache: 'no-store'}});
    if (!r.ok) throw new Error(r.status);
    const buf = await r.arrayBuffer();
    const h = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buf))].map(b => b.toString(16).padStart(2, '0')).join('');
    if (h !== {json.dumps(expected)}) {{ el.textContent = 'The source file has changed since this export. Re-export to refresh these outputs.'; el.classList.add('show'); }}
    else {{ const ok = document.getElementById('stale-ok'); if (ok) ok.textContent = 'matches the source file'; }}
  }} catch (e) {{ /* file:// or missing: cannot check */ }}
}})();
</script>"""


def _viewer_script() -> str:
    return f"""
<script type="importmap">{{"imports":{{"three":"https://cdn.jsdelivr.net/npm/three@{THREE_VERSION}/build/three.module.js","three/addons/":"https://cdn.jsdelivr.net/npm/three@{THREE_VERSION}/examples/jsm/"}}}}</script>
<script type="module">
import * as THREE from 'three';
import {{ GLTFLoader }} from 'three/addons/loaders/GLTFLoader.js';
import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';
const host = document.getElementById('viewer');
const renderer = new THREE.WebGLRenderer({{ antialias: true }});
renderer.setPixelRatio(devicePixelRatio);
const size = () => renderer.setSize(host.clientWidth, host.clientHeight, false);
host.appendChild(renderer.domElement); size();
const scene = new THREE.Scene(); scene.background = new THREE.Color(0xe9ebee);
const camera = new THREE.PerspectiveCamera(50, host.clientWidth / host.clientHeight, 0.05, 100);
const controls = new OrbitControls(camera, renderer.domElement);
scene.add(new THREE.HemisphereLight(0xffffff, 0x888888, 1.2));
const sun = new THREE.DirectionalLight(0xffffff, 1.5); sun.position.set(3, 6, 4); scene.add(sun);
new GLTFLoader().load('scene.glb', (gltf) => {{
  scene.add(gltf.scene);
  const cams = gltf.scene.children.filter(n => n.name.startsWith('camera:'));
  const hud = document.getElementById('cams');
  const go = (c) => {{ camera.position.copy(c.position); const t = c.userData.target_m; controls.target.set(t[0], t[1], t[2]); controls.update(); }};
  for (const c of cams) {{ const b = document.createElement('button'); b.textContent = c.name.slice(7); b.onclick = () => go(c); hud.appendChild(b); }}
  if (cams.length) go(cams[cams.length - 1]); else {{ camera.position.set(3, 2, 4); controls.target.set(1.5, 0.9, 1); }}
}}, undefined, () => {{ document.getElementById('cams').textContent = 'could not load scene.glb (serve over http, not file://)'; }});
addEventListener('resize', () => {{ size(); camera.aspect = host.clientWidth / host.clientHeight; camera.updateProjectionMatrix(); }});
renderer.setAnimationLoop(() => {{ controls.update(); renderer.render(scene, camera); }});
</script>"""


def review_page(k: Kitchen, out_dir: Path, pack: PurchasePack, export: dict[str, Any], source_sha: str) -> str:
    findings = validate(k)
    source_rel = os.path.relpath(k.path, out_dir)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    drawings = [Path(p).name for p in export.get("drawings", [])]
    renders = [Path(p).name for p in export.get("renders", [])]
    p = [f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>{_esc(k.name)}</title><style>{STYLE}</style>",
         "<div class=page><header>",
         f"<div class=meta><a href='../index.html'>all layouts</a> · exported {now} · source <code>{_esc(source_rel)}</code> <span id=stale-ok class=stale-ok></span></div>",
         f"<h1>{_esc(k.name)}</h1>",
         f"<div class=meta>catalog {_esc(k.catalog.id)} · {len(k.runs)} runs · {sum(len(r.items) for r in k.runs)} items · ceiling {k.room.min_ceiling} mm · counter at {k.legs + 762 + k.counter_thickness} mm</div>",
         "<div id=stale class=banner></div>",
         "</header>"]

    errs = [f for f in findings if f.is_error]
    warns = [f for f in findings if not f.is_error]
    p.append("<section class=sheet><h2>Validation</h2>")
    p.append(f"<p><span class='tag{'' if errs else ' ok'}'>{len(errs)} errors</span> &nbsp; <span class=tag>{len(warns)} warnings</span></p>")
    if errs or warns:
        p.append("<ul>" + "".join(f"<li><code>{_esc(f.rule)}</code> {_esc(f.message)}</li>" for f in errs + warns) + "</ul>")
    p.append("</section>")

    p.append("<section class=sheet><h2>Drawings</h2><div class=grid>")
    for name in drawings + (["countertop.svg"] if (out_dir / "countertop.svg").exists() else []):
        p.append(f"<figure><a href='{name}'><img src='{name}' alt='{_esc(name)}'></a><figcaption>{_esc(name)} · real mm, 1:{export.get('scale', 20)} when printed</figcaption></figure>")
    p.append("</div></section>")

    p.append("<section class=sheet><h2>Renders</h2>")
    if renders:
        p.append("<div class=grid>" + "".join(f"<figure><a href='{n}'><img src='{n}' alt='{_esc(n)}'></a><figcaption>{_esc(n)}</figcaption></figure>" for n in renders) + "</div>")
    else:
        p.append("<p class=meta>No Blender renders in this export. Run <code>mmk export &lt;file&gt; --render</code> or ask for <code>export</code> with render on.</p>")
    p.append("</section>")

    p.append("<section class=sheet><h2>3D</h2><div id=viewer><div id=cams></div></div><p class=meta>Drag to orbit, scroll to zoom. Buttons jump to the export's cameras. Needs the page served over http (<code>python -m http.server</code> from the repo root).</p></section>")

    p.append("<section class=sheet><h2>Runs</h2>")
    for r in runs_summary(k):
        p.append(f"<h3>wall {_esc(r['wall'])} · {_esc(r['level'])} · span {r['span'][0]}–{r['span'][1]} ({r['length_mm']} mm), used {r['used_mm']} mm</h3><div class=wrap><table><tr><th>label</th><th>kind</th><th>id / ref</th><th class=n>start</th><th class=n>end</th><th class=n>width</th><th>fronts</th></tr>")
        for it in r["items"]:
            fronts = ", ".join(f"{f['count']}× {f['id'].split(':', 1)[1]}" for f in it["fronts"]) if it["fronts"] else ""
            p.append(f"<tr><td>{_esc(it['label'])}</td><td>{_esc(it['kind'])}</td><td>{_esc(it['id'] or it['ref'] or '')}</td><td class=n>{it['start']}</td><td class=n>{it['end']}</td><td class=n>{it['width']}</td><td>{_esc(fronts)}</td></tr>")
        p.append("</table></div>")
    p.append("</section>")

    p.append("<section class=sheet><h2>Purchase pack</h2>")
    p.append(f"<p class=meta>{len(pack.lines)} lines · {len(pack.unverified)} unverified · {len(pack.missing_articles)} without article number · <a href='purchase-pack.csv'>csv</a> · <a href='purchase-pack.md'>markdown</a></p>")
    p.append("<div class=wrap><table><tr><th class=n>qty</th><th>id</th><th>article</th><th>name</th><th>rule / detail</th></tr>")
    for l in pack.lines:
        flags = []
        if not l.verified and l.kind not in ("appliance", "finish"):
            flags.append("unverified")
        if l.article is None and l.kind not in ("appliance", "finish", "filler"):
            flags.append("no article")
        tag = " ".join(f"<span class=tag>{f}</span>" for f in flags)
        p.append(f"<tr><td class=n>{l.qty}</td><td>{_esc(l.id)}</td><td>{_esc(l.article or '')}</td><td>{_esc(l.name)} {tag}</td><td class=meta>{_esc((l.rule + ': ') if l.rule else '')}{_esc(l.detail)}</td></tr>")
    p.append("</table></div>")
    p.append("<h3>Countertop</h3><ul>" + "".join(f"<li>wall {_esc(s['wall'])} {s['start']}–{s['end']}: {s['length_mm']} × {s['depth_mm']} mm{' · starts in the corner' if s['corner_start'] else ''}{' · ends at ' + _esc(', '.join(s['cut_by'])) if s.get('cut_by') else ''}</li>" for s in pack.countertop) + "</ul>")
    p.append("<h3>Assumptions</h3><ul>" + "".join(f"<li>{_esc(a)}</li>" for a in pack.assumptions) + "</ul>")
    p.append("<h3>Not in this pack</h3><ul>" + "".join(f"<li>{_esc(a)}</li>" for a in pack.not_in_scope) + "</ul>")
    p.append("</section>")

    p.append("<section class=sheet><h2>Materials</h2><ul>" + "".join(f"<li>{_esc(role)}: <code>{_esc(key)}</code></li>" for role, key in (k.materials or {}).items()) + ("<li class=meta>library defaults for everything not listed</li>" if True else "") + "</ul></section>")
    p.append("</div>")
    p.append(_hash_script(source_rel, source_sha))
    p.append(_viewer_script())
    return "\n".join(p) + "\n"


def review_index(out_root: Path) -> str:
    rows = []
    for d in sorted(x for x in out_root.iterdir() if x.is_dir() and (x / "manifest.json").exists()):
        m = json.loads((d / "manifest.json").read_text())
        src = Path(m.get("source", ""))
        rel = os.path.relpath(src, out_root) if src.is_absolute() or src.exists() else m.get("source", "")
        rows.append((d.name, m, rel))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    p = [f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Millimeter Kitchen exports</title><style>{STYLE}</style>",
         "<div class=page><header><h1>Exported layouts</h1>", f"<div class=meta>index written {now} · each row checks its source file when opened over http</div></header>",
         "<section class=sheet><div class=wrap><table><tr><th>layout</th><th>source</th><th>exported</th><th>renders</th><th>status</th></tr>"]
    for name, m, rel in rows:
        p.append(f"<tr><td><a href='{_esc(name)}/index.html'>{_esc(name)}</a></td><td><code>{_esc(rel)}</code></td><td>{_esc(m.get('exported_at', ''))}</td>"
                 f"<td>{'yes' if m.get('renders_current') else 'no'}</td><td id='st-{_esc(name)}' data-src='{_esc(rel)}' data-sha='{_esc(m.get('source_sha256', ''))}'>…</td></tr>")
    p.append("</table></div>")
    if not rows:
        p.append("<p class=meta>Nothing exported yet. Run <code>mmk export examples/kitchen.fits.json</code>.</p>")
    p.append("</section></div>")
    p.append("""
<script>
for (const td of document.querySelectorAll('td[id^="st-"]')) (async () => {
  try {
    const r = await fetch(td.dataset.src, {cache: 'no-store'}); if (!r.ok) throw new Error(r.status);
    const h = [...new Uint8Array(await crypto.subtle.digest('SHA-256', await r.arrayBuffer()))].map(b => b.toString(16).padStart(2, '0')).join('');
    td.innerHTML = h === td.dataset.sha ? '<span class="tag ok">current</span>' : '<span class="tag">stale</span>';
  } catch (e) { td.textContent = 'unknown (serve over http)'; }
})();
</script>""")
    return "\n".join(p) + "\n"


def write_review(k: Kitchen, out_dir: Path, pack: PurchasePack, export: dict[str, Any], source_sha: str) -> Path:
    page = out_dir / "index.html"
    page.write_text(review_page(k, out_dir, pack, export, source_sha))
    (out_dir.parent / "index.html").write_text(review_index(out_dir.parent))
    return page
