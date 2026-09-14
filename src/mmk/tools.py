"""Phase 5: the tool surface an assistant sees, as plain functions returning JSON-able dicts.

`mcp_server.py` registers these with FastMCP and `cli.py` exposes them as
`mmk edit`. Keeping them here means the whole surface is tested without an
MCP client. Every path is resolved under `root` and must stay inside it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .bom import bill_of_materials
from .catalog import load_catalog
from .draw import write_drawings
from .edit import EditError, apply, branch, runs_summary
from .finishes import ROLES, load_finishes
from .gltf import write_glb
from .io import CATALOG_DIR, FileError, resolve_catalog_path
from .model import load_kitchen
from .rules import validate
from .scene import build_scene


class ToolError(Exception):
    pass


def resolve_path(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    try:
        p.relative_to(root.resolve())
    except ValueError as exc:
        raise ToolError(f"'{rel}' is outside the project root {root}") from exc
    return p


def _wrap(fn):
    def inner(*a, **kw):
        try:
            return fn(*a, **kw)
        except (EditError, FileError, ToolError, KeyError) as exc:
            return {"ok": False, "error": str(exc)}
    inner.__name__ = fn.__name__
    inner.__doc__ = fn.__doc__
    return inner


@_wrap
def describe(root: Path, kitchen: str) -> dict[str, Any]:
    """The whole layout: walls, runs with every item's label and interval, materials, appliances, current findings."""
    k = load_kitchen(resolve_path(root, kitchen))
    findings = validate(k)
    return {
        "ok": True,
        "name": k.name,
        "catalog": k.catalog.id,
        "walls": [{"id": w, "planning_length_mm": k.room.walls[w].planning_length,
                   "openings": [{"kind": o.kind, "label": o.label, "from": o.start, "to": o.end, "sill": o.sill, "head": o.head} for o in k.room.walls[w].openings],
                   "services": [{"kind": s.kind, "at": s.at, "height": s.height} for s in k.room.walls[w].services]} for w in k.room.order],
        "ceiling_min_mm": k.room.min_ceiling,
        "legs_mm": k.legs, "counter_thickness_mm": k.counter_thickness, "wall_cabinet_bottom_mm": k.wall_cabinet_bottom,
        "materials": k.materials,
        "appliances": {r: {"name": a.name, "kind": a.kind, "width": a.width, "depth": a.depth, "height": a.height} for r, a in k.appliances.items()},
        "runs": runs_summary(k),
        "errors": [f.render() for f in findings if f.is_error],
        "warnings": [f.render() for f in findings if not f.is_error],
    }


@_wrap
def search_catalog(root: Path, kitchen: str | None = None, kind: str | None = None, type: str | None = None,
                   width_in: float | None = None, height_in: float | None = None, series: str | None = None, text: str | None = None,
                   limit: int = 50) -> dict[str, Any]:
    """Find catalog ids. kind: frame|front|drawer_front|filler; type: base|sink_base|wall|wall_fridge|high|door|drawer; sizes in nominal inches."""
    if kitchen:
        kp = resolve_path(root, kitchen)
        cat_ref = json.loads(kp.read_text())["catalog"]
        cat = load_catalog(resolve_catalog_path(cat_ref, kp))
    else:
        cat = load_catalog(sorted(CATALOG_DIR.glob("sektion-*.json"))[-1])
    out = []
    for it in cat.items(kind=kind, type=type):
        if width_in is not None and it.nominal_in.get("w") != width_in:
            continue
        if height_in is not None and it.nominal_in.get("h") != height_in:
            continue
        if series and (it.series or "").lower() != series.lower():
            continue
        if text and text.lower() not in (it.id + " " + it.name).lower():
            continue
        out.append({"id": it.id, "kind": it.kind, "type": it.type, "series": it.series, "finish": it.finish, "nominal": it.nominal,
                    "actual_mm": {"w": it.w, "d": it.d, "h": it.h}, "article": it.article, "verified": it.verified})
        if len(out) >= limit:
            break
    return {"ok": True, "catalog": cat.id, "count": len(out), "items": out}


@_wrap
def list_finishes(role: str | None = None) -> dict[str, Any]:
    """Finish keys by role for the materials block. Roles: frame, counter, backsplash, floor, wall, appliance, toe_kick (fronts follow the catalog series)."""
    lib = load_finishes()
    out = []
    for r in ROLES:
        if role and r != role:
            continue
        for f in lib.for_role(r):
            out.append({"key": f.key, "role": r, "name": f.name, "default": lib.defaults[r] == f.key})
    return {"ok": True, "finishes": out}


@_wrap
def apply_ops(root: Path, kitchen: str, ops: list[dict], dry_run: bool = False, draw_out: str | None = None) -> dict[str, Any]:
    """Apply edit operations. Writes the file only if the result validates; otherwise refuses and returns the errors.
    Ops: replace{label, items[]}, insert{wall, level, index|before|after, item}, remove{label}, move{label, before|after|index|to{}},
    swap{label, with}, set_fronts{label, fronts[]}, set_width{label, width}, set_material{role, key}, set{path, value}.
    Items: {kind: cabinet, id, label?, fronts?[{id,count}]} | {kind: appliance, ref} | {kind: filler|gap|panel, width}."""
    res = apply(resolve_path(root, kitchen), ops, dry_run=dry_run)
    out = res.to_dict()
    if res.ok and res.written and draw_out:
        k = load_kitchen(resolve_path(root, kitchen))
        out["drawings"] = [str(p) for p in write_drawings(k, resolve_path(root, draw_out))]
    return out


@_wrap
def validate_kitchen(root: Path, kitchen: str) -> dict[str, Any]:
    """Run the fit rules and report errors and warnings."""
    k = load_kitchen(resolve_path(root, kitchen))
    f = validate(k)
    return {"ok": not any(x.is_error for x in f), "errors": [x.render() for x in f if x.is_error], "warnings": [x.render() for x in f if not x.is_error]}


@_wrap
def bom(root: Path, kitchen: str) -> dict[str, Any]:
    """Bill of materials: every catalog item, filler cut, appliance and finish the layout uses."""
    k = load_kitchen(resolve_path(root, kitchen))
    return {"ok": True, "lines": [l.__dict__ for l in bill_of_materials(k)]}


@_wrap
def start_variation(root: Path, kitchen: str, name: str) -> dict[str, Any]:
    """Copy the kitchen to a sibling file named for the intent (e.g. 'island instead of peninsula'). Returns the new path."""
    dst = branch(resolve_path(root, kitchen), name)
    return {"ok": True, "path": str(dst.relative_to(root.resolve())), "git_hint": f"git checkout -b variation/{dst.stem}"}


@_wrap
def draw(root: Path, kitchen: str, out: str = "out", scale: int = 20) -> dict[str, Any]:
    """Write SVG elevations per wall and a plan view, in real millimeters at 1:scale."""
    k = load_kitchen(resolve_path(root, kitchen))
    if any(f.is_error for f in validate(k)):
        return {"ok": False, "error": "layout has errors; fix them before drawing (see validate)"}
    return {"ok": True, "files": [str(p) for p in write_drawings(k, resolve_path(root, out), scale)]}


@_wrap
def render(root: Path, kitchen: str, out: str = "out", blender: str | None = None, engine: str = "EEVEE", no_render: bool = False) -> dict[str, Any]:
    """Export scene.glb and cameras.json, then render one image per wall with Blender if it is available."""
    k = load_kitchen(resolve_path(root, kitchen))
    if any(f.is_error for f in validate(k)):
        return {"ok": False, "error": "layout has errors; fix them before rendering (see validate)"}
    outp = resolve_path(root, out)
    outp.mkdir(parents=True, exist_ok=True)
    scene = build_scene(k)
    glb = write_glb(scene, outp / "scene.glb")
    cams = outp / "cameras.json"
    cams.write_text(json.dumps([{"name": c.name, "position": list(c.position), "target": list(c.target), "vfov_deg": c.vfov_deg, "aspect": c.aspect} for c in scene.cameras], indent=2) + "\n")
    result: dict[str, Any] = {"ok": True, "glb": str(glb), "cameras": str(cams), "renders": []}
    if no_render:
        return result
    exe = blender or shutil.which("blender")
    if not exe or not Path(exe).exists():
        result["note"] = "blender not found; exported the scene only. Pass blender=/path/to/blender to render."
        return result
    script = Path(__file__).resolve().parents[2] / "tools" / "blender_render.py"
    proc = subprocess.run([exe, "--background", "--python", str(script), "--", str(glb), str(cams), str(outp), "--engine", engine], capture_output=True, text=True)
    result["renders"] = sorted(str(p) for p in outp.glob("render-*.png"))
    if proc.returncode != 0:
        result["ok"] = False
        result["error"] = proc.stderr[-2000:]
    return result
