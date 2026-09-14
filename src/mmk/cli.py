"""`mmk` command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .catalog import load_catalog
from .draw import DEFAULT_SCALE, write_drawings
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
