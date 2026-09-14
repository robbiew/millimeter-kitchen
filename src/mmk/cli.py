"""`mmk` command line."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .catalog import load_catalog
from .bom import bill_of_materials, render_bom
from .draw import DEFAULT_SCALE, write_drawings
from .edit import EditError, apply
from .export import export_all, find_blender
from .purchase import countertop_svg, derive, pack_csv, render_pack
from .planner_import import import_list
from .reconcile import read_ikea_list, reconcile
from .finishes import ROLES, load_finishes
from .gltf import write_glb
from .scene import build_scene
from .findings import Finding, has_errors
from .io import CATALOG_DIR, FileError
from .model import load_kitchen
from .room import check_room, load_room
from .rules import validate
from .units import format_inch


def _print(findings: list[Finding]) -> None:
    for f in findings:
        print(f.render())


def cmd_survey_check(args: argparse.Namespace) -> int:
    room = load_room(args.room)
    findings = check_room(room)
    _print(findings)
    n_err = sum(f.is_error for f in findings)
    print(f"{room.name}: {len(room.walls)} walls, {len(room.corners)} corners, ceiling min {room.min_ceiling} mm — {n_err} errors, {len(findings) - n_err} warnings")
    for w in room.order:
        wall = room.walls[w]
        print(f"  wall {w}: planning length {wall.planning_length} mm ({format_inch(wall.planning_length)})")
    return 1 if n_err else 0


def _catalog_path(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    files = sorted(CATALOG_DIR.glob("*.json"))
    if not files:
        raise FileError(f"no catalog files in {CATALOG_DIR}")
    return files[-1]


def cmd_catalog_list(args: argparse.Namespace) -> int:
    cat = load_catalog(_catalog_path(args.catalog))
    for it in cat.items(kind=args.kind, type=args.type):
        dims = "x".join(str(v) for v in (it.w, it.d, it.h) if v is not None)
        flag = "" if it.verified else "  (unverified)"
        print(f"{it.id:44} {it.nominal or '':12} {dims:>14} mm  {it.article or '-':12}{flag}")
    return 0


def cmd_catalog_show(args: argparse.Namespace) -> int:
    cat = load_catalog(_catalog_path(args.catalog))
    it = cat.get(args.id)
    if it is None:
        print(f"no item '{args.id}' in {cat.id}", file=sys.stderr)
        return 1
    for k, v in vars(it).items():
        print(f"{k:12} {v}")
    return 0


def cmd_catalog_import(args: argparse.Namespace) -> int:
    rep = import_list(_catalog_path(args.catalog), args.ikea_list, write=args.write)
    print(rep.render())
    c = rep.counts()
    return 0 if not c.get("ambiguous") and not c.get("unmatched") and not c.get("conflict") else 1


def cmd_validate(args: argparse.Namespace) -> int:
    k = load_kitchen(args.kitchen)
    findings = validate(k)
    _print(findings)
    n_err = sum(f.is_error for f in findings)
    print(f"{k.name}: {len(k.runs)} runs, {sum(len(r.items) for r in k.runs)} items — {n_err} errors, {len(findings) - n_err} warnings")
    if args.show_runs:
        for r in k.runs:
            print(f"  wall {r.wall} {r.level}: span {r.start}–{r.end} ({r.length} mm), used {r.used} mm")
            for p in r.items:
                print(f"    {p.start:5}–{p.end:5}  {p.width:5} mm  {p.kind:9} {p.label}")
    return 1 if n_err else 0


def cmd_draw(args: argparse.Namespace) -> int:
    k = load_kitchen(args.kitchen)
    findings = validate(k)
    n_err = sum(f.is_error for f in findings)
    if n_err and not args.force:
        _print([f for f in findings if f.is_error])
        print(f"{k.name}: {n_err} errors; fix them or pass --force to draw anyway", file=sys.stderr)
        return 1
    for p in write_drawings(k, args.out, args.scale):
        print(p)
    return 0


def cmd_bom(args: argparse.Namespace) -> int:
    k = load_kitchen(args.kitchen)
    findings = validate(k)
    n_err = sum(f.is_error for f in findings)
    if n_err:
        _print([f for f in findings if f.is_error])
        print(f"{k.name}: {n_err} errors; a bill of materials is only meaningful for a layout that fits", file=sys.stderr)
        return 1
    lines = bill_of_materials(k)
    if args.json:
        print(json.dumps([l.__dict__ for l in lines], indent=2))
    else:
        print(render_bom(k, lines))
    return 0


def cmd_finishes_list(args: argparse.Namespace) -> int:
    lib = load_finishes()
    for role in ROLES:
        if args.role and role != args.role:
            continue
        for f in lib.for_role(role):
            star = " (default)" if lib.defaults[role] == f.key else ""
            print(f"{role:10} {f.key:22} {f.name}{star}")
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    raw = Path(args.ops[1:]).read_text() if args.ops.startswith("@") else args.ops
    ops = json.loads(raw)
    if isinstance(ops, dict):
        ops = [ops]
    try:
        res = apply(args.kitchen, ops, dry_run=args.dry_run)
    except EditError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print(res.message)
        _print(res.findings if not res.ok else [f for f in res.findings if not f.is_error])
        for d in res.bom_diff:
            sign = "+" if d["delta"] > 0 else ""
            print(f"  BOM {sign}{d['delta']:>3}  {d['id']}  ({d['before']} → {d['after']})")
        print("written" if res.written else ("dry run, not written" if res.ok else "refused, file unchanged"))
    if res.ok and res.written and not args.no_export:
        ex = export_all(load_kitchen(args.kitchen), args.out, render=args.render, blender=args.blender)
        print(f"exported to {ex['out']}: {len(ex['drawings'])} drawings, scene.glb, cameras.json" + (f", {len(ex['renders'])} renders" if ex["renders"] else "") + (f" ({ex['render_note']})" if ex.get("render_note") else ""))
    return 0 if res.ok else 1


def cmd_export(args: argparse.Namespace) -> int:
    k = load_kitchen(args.kitchen)
    findings = validate(k)
    if any(f.is_error for f in findings) and not args.force:
        _print([f for f in findings if f.is_error])
        print(f"{k.name}: fix the errors or pass --force", file=sys.stderr)
        return 1
    ex = export_all(k, args.out, scale=args.scale, render=args.render, blender=args.blender)
    print(f"exported to {ex['out']}: {len(ex['drawings'])} drawings, scene.glb, cameras.json, purchase pack, index.html" + (f", {len(ex['renders'])} renders" if ex["renders"] else "") + (f" ({ex['render_note']})" if ex.get("render_note") else ""))
    print(f"review page: {ex['review']}   all layouts: {ex['index']}")
    return 0


def cmd_purchase(args: argparse.Namespace) -> int:
    k = load_kitchen(args.kitchen)
    findings = validate(k)
    if any(f.is_error for f in findings):
        _print([f for f in findings if f.is_error])
        print(f"{k.name}: fix the errors before buying anything", file=sys.stderr)
        return 1
    pack = derive(k)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "purchase-pack.md").write_text(render_pack(k, pack))
        (out / "purchase-pack.csv").write_text(pack_csv(pack))
        (out / "countertop.svg").write_text(countertop_svg(k))
        for name in ("purchase-pack.md", "purchase-pack.csv", "countertop.svg"):
            print(out / name)
    else:
        print(render_pack(k, pack))
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    k = load_kitchen(args.kitchen)
    pack = derive(k)
    ikea = read_ikea_list(args.ikea_list)
    expl = json.loads(Path(args.explain).read_text()) if args.explain else None
    rep = reconcile(pack, ikea, expl)
    print(rep.render())
    return 0 if rep.clean else 1


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import main as mcp_main
    return mcp_main(Path(args.root))


BLENDER_SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "blender_render.py"


def cmd_render(args: argparse.Namespace) -> int:
    k = load_kitchen(args.kitchen)
    findings = validate(k)
    n_err = sum(f.is_error for f in findings)
    if n_err and not args.force:
        _print([f for f in findings if f.is_error])
        print(f"{k.name}: {n_err} errors; fix them or pass --force to render anyway", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    scene = build_scene(k)
    glb = write_glb(scene, out / "scene.glb")
    cams = out / "cameras.json"
    cams.write_text(json.dumps([{"name": c.name, "position": list(c.position), "target": list(c.target), "vfov_deg": c.vfov_deg, "aspect": c.aspect} for c in scene.cameras], indent=2) + "\n")
    print(glb)
    print(cams)
    print(f"{len(scene.boxes)} boxes, {len(scene.cameras)} cameras")
    if args.no_render:
        return 0
    blender = find_blender(args.blender)
    if not blender or not Path(blender).exists():
        where = f"'{blender}' does not exist" if blender else "blender not found on PATH or in the usual install locations"
        print(f"{where}; pass --blender /path/to/blender, set MMK_BLENDER, or open scene.glb in viewer/index.html", file=sys.stderr)
        return 2
    cmd = [blender, "--background", "--python", str(BLENDER_SCRIPT), "--", str(glb), str(cams), str(out),
           "--engine", args.engine, "--size", args.size, "--samples", str(args.samples)]
    print(" ".join(cmd))
    return subprocess.call(cmd)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="mmk", description="Millimeter Kitchen: survey checks and layout validation.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    survey = sub.add_parser("survey", help="phase 0: room survey").add_subparsers(dest="sub", required=True)
    sc = survey.add_parser("check", help="check a room.json for internal consistency")
    sc.add_argument("room")
    sc.set_defaults(fn=cmd_survey_check)

    catalog = sub.add_parser("catalog", help="phase 1: product catalog").add_subparsers(dest="sub", required=True)
    cl = catalog.add_parser("list")
    cl.add_argument("--catalog", help="catalog file (default: newest in catalog/)")
    cl.add_argument("--kind")
    cl.add_argument("--type")
    cl.set_defaults(fn=cmd_catalog_list)
    cs = catalog.add_parser("show")
    cs.add_argument("id")
    cs.add_argument("--catalog")
    cs.set_defaults(fn=cmd_catalog_show)
    ci = catalog.add_parser("import", help="phase 6: pull article numbers from an IKEA Kitchen Planner item list into the catalog")
    ci.add_argument("ikea_list", help="CSV/TSV with article number, product name and quantity columns")
    ci.add_argument("--catalog")
    ci.add_argument("--write", action="store_true", help="record matched articles as verified (default: report only)")
    ci.set_defaults(fn=cmd_catalog_import)

    v = sub.add_parser("validate", help="phase 1: validate a kitchen.json against its room and catalog")
    v.add_argument("kitchen")
    v.add_argument("--show-runs", action="store_true", help="print every placed item with its interval")
    v.set_defaults(fn=cmd_validate)

    d = sub.add_parser("draw", help="phase 2: write dimensioned elevations and a plan view as SVG")
    d.add_argument("kitchen")
    d.add_argument("--out", default="out", help="output directory (default: out/)")
    d.add_argument("--scale", type=int, default=DEFAULT_SCALE, help="print scale denominator (default 20 = 1:20)")
    d.add_argument("--force", action="store_true", help="draw even if the validator reports errors")
    d.set_defaults(fn=cmd_draw)

    r = sub.add_parser("render", help="phase 3: export scene.glb and cameras, then render each wall in Blender")
    r.add_argument("kitchen")
    r.add_argument("--out", default="out")
    r.add_argument("--no-render", action="store_true", help="only write scene.glb and cameras.json")
    r.add_argument("--blender", help="path to the blender executable (default: MMK_BLENDER, then PATH, then the usual install locations)")
    r.add_argument("--engine", default="EEVEE", choices=["EEVEE", "CYCLES"])
    r.add_argument("--size", default="1600x1000")
    r.add_argument("--samples", type=int, default=64)
    r.add_argument("--force", action="store_true", help="render even if the validator reports errors")
    r.set_defaults(fn=cmd_render)

    b = sub.add_parser("bom", help="phase 4/6: list every catalog item the layout uses, with counts and article numbers")
    b.add_argument("kitchen")
    b.add_argument("--json", action="store_true")
    b.set_defaults(fn=cmd_bom)

    fin = sub.add_parser("finishes", help="phase 4: the finish library").add_subparsers(dest="sub", required=True)
    fl = fin.add_parser("list")
    fl.add_argument("--role", choices=ROLES)
    fl.set_defaults(fn=cmd_finishes_list)

    e = sub.add_parser("edit", help="phase 5: apply edit operations; the file is written only if the result fits")
    e.add_argument("kitchen")
    e.add_argument("ops", help="JSON op or list of ops, or @file.json")
    e.add_argument("--dry-run", action="store_true")
    e.add_argument("--out", default="out", help="export root; outputs go to OUT/<kitchen stem>/ (default: out)")
    e.add_argument("--no-export", action="store_true", help="do not regenerate drawings and scene after the edit")
    e.add_argument("--render", action="store_true", help="also render in Blender after the edit")
    e.add_argument("--blender", help="path to the blender executable")
    e.add_argument("--json", action="store_true", help="machine-readable result")
    e.set_defaults(fn=cmd_edit)

    ex = sub.add_parser("export", help="regenerate everything derived from a layout: drawings, scene, purchase pack, review page")
    ex.add_argument("kitchen")
    ex.add_argument("--out", default="out")
    ex.add_argument("--scale", type=int, default=DEFAULT_SCALE)
    ex.add_argument("--render", action="store_true", help="also render in Blender")
    ex.add_argument("--blender")
    ex.add_argument("--force", action="store_true")
    ex.set_defaults(fn=cmd_export)

    pu = sub.add_parser("purchase", help="phase 6: the purchase pack with derived hardware, countertop outline and assumptions")
    pu.add_argument("kitchen")
    pu.add_argument("--out", metavar="DIR", help="write purchase-pack.md, purchase-pack.csv and countertop.svg here (default: print)")
    pu.set_defaults(fn=cmd_purchase)

    rc = sub.add_parser("reconcile", help="phase 6: compare the pack with the IKEA Kitchen Planner item list (CSV/TSV)")
    rc.add_argument("kitchen")
    rc.add_argument("ikea_list")
    rc.add_argument("--explain", metavar="JSON", help="{article: reason} for differences that are intended")
    rc.set_defaults(fn=cmd_reconcile)

    m = sub.add_parser("mcp", help="phase 5: run the MCP server over stdio (needs the mcp extra)")
    m.add_argument("--root", default=".", help="project root; kitchen paths are relative to it")
    m.set_defaults(fn=cmd_mcp)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (FileError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
