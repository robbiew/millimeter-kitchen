"""Phase 5: the tool surface an assistant sees, as plain functions returning JSON-able dicts.

`mcp_server.py` registers these with FastMCP and `cli.py` exposes them as
`mmk edit`. Keeping them here means the whole surface is tested without an
MCP client. Every path is resolved under `root` and must stay inside it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .bom import bill_of_materials
from .catalog import load_catalog
from .edit import EditError, apply, branch, is_fixture, runs_summary
from .export import export_all, is_stale
from .finishes import ROLES, load_finishes
from .io import CATALOG_DIR, FileError, resolve_catalog_path
from .model import load_kitchen
from .rules import validate


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
        "export_stale": is_stale(root / "out", resolve_path(root, kitchen)),
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
def apply_ops(root: Path, kitchen: str, ops: list[dict], dry_run: bool = False, out: str = "out", allow_fixture_edit: bool = False,
              render: bool = False, blender: str | None = None) -> dict[str, Any]:
    """Apply edit operations. Writes the file only if the result validates; otherwise refuses and returns the errors.
    Ops: replace{label, items[]}, insert{wall, level, index|before|after, item}, remove{label}, move{label, before|after|index|to{}},
    swap{label, with}, set_fronts{label, fronts[]}, set_width{label, width}, set_material{role, key}, set{path, value}.
    Items: {kind: cabinet, id, label?, fronts?[{id,count}]} | {kind: appliance, ref} | {kind: filler|gap|panel, width}.
    Files under examples/ are fixtures: start_variation first, or pass allow_fixture_edit.
    A successful edit re-exports drawings, scene.glb and cameras.json into <out>/<kitchen stem>/; pass render=True to also render in Blender."""
    kp = resolve_path(root, kitchen)
    if is_fixture(kp) and not dry_run and not allow_fixture_edit:
        return {"ok": False, "written": False, "error": (
            f"'{kitchen}' is a test fixture under examples/ and is regenerated by tools/make_fixtures.py. "
            "Call start_variation first and edit the variation, or pass allow_fixture_edit=true if you really mean to change the fixture.")}
    res = apply(kp, ops, dry_run=dry_run)
    result = res.to_dict()
    if res.ok and res.written:
        result["export"] = export_all(load_kitchen(kp), resolve_path(root, out), render=render, blender=blender)
    return result


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
    """Copy the kitchen to a new file named for the intent (e.g. 'island instead of peninsula'). A fixture from examples/ is copied into variations/. Returns the new path."""
    dst = branch(resolve_path(root, kitchen), name)
    return {"ok": True, "path": str(dst.relative_to(root.resolve())), "git_hint": f"git checkout -b variation/{dst.stem}"}


@_wrap
def export(root: Path, kitchen: str, out: str = "out", scale: int = 20, render: bool = False, blender: str | None = None, engine: str = "EEVEE") -> dict[str, Any]:
    """Regenerate everything derived from the file into <out>/<kitchen stem>/: SVG elevations and plan, scene.glb, cameras.json, manifest.json.
    With render=True, also one Blender image per camera (needs blender on PATH or a blender path)."""
    k = load_kitchen(resolve_path(root, kitchen))
    if any(f.is_error for f in validate(k)):
        return {"ok": False, "error": "layout has errors; fix them before exporting (see validate)"}
    result = export_all(k, resolve_path(root, out), scale=scale, render=render, blender=blender, engine=engine)
    return {"ok": "render_error" not in result, **result}
