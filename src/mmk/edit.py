"""Phase 5: operations on a kitchen document, gated by the validator.

An operation edits the raw JSON document. `apply` runs a list of operations
on a copy, resolves and validates the result, and writes the file only if
there are no errors. A proposal that does not fit is refused, and the file
on disk does not change. This is the one door through which any assistant,
script or MCP client changes a layout.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bom import BomLine, bill_of_materials
from .findings import Finding
from .io import FileError, load_validated
from .model import Kitchen, kitchen_from_dict
from .rules import validate

OPS = ("replace", "insert", "remove", "move", "swap", "set_fronts", "set_width", "fit_width", "set_material", "set", "add_run", "remove_run")
LEVELS = ("base", "wall", "high")


class EditError(Exception):
    """An operation could not be applied to the document (bad label, bad index, bad op)."""


@dataclass
class EditResult:
    ok: bool
    written: bool
    path: str
    findings: list[Finding]
    bom_diff: list[dict[str, Any]] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.is_error]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "written": self.written,
            "path": self.path,
            "message": self.message,
            "errors": [f.render() for f in self.errors],
            "warnings": [f.render() for f in self.findings if not f.is_error],
            "bom_diff": self.bom_diff,
            "runs": self.runs,
        }


# ---------------------------------------------------------------- locating things

def _runs(doc: dict) -> list[dict]:
    return doc["runs"]


def _find_label(doc: dict, label: str) -> tuple[dict, int]:
    """Return (run, index) of the item with this label."""
    hits = [(r, i) for r in _runs(doc) for i, it in enumerate(r["items"]) if it.get("label") == label]
    if not hits:
        raise EditError(f"no item labelled '{label}'; use describe to list labels")
    if len(hits) > 1:
        raise EditError(f"label '{label}' is not unique; fix the file first")
    return hits[0]


def _find_run(doc: dict, wall: str, level: str, run_index: int = 0) -> dict:
    cands = [r for r in _runs(doc) if r["wall"] == wall and r["level"] == level]
    if not cands:
        raise EditError(f"no {level} run on wall {wall}")
    if run_index >= len(cands):
        raise EditError(f"wall {wall} has only {len(cands)} {level} run(s)")
    return cands[run_index]


def _all_labels(doc: dict) -> set[str]:
    return {it.get("label") for r in _runs(doc) for it in r["items"] if it.get("label")}


def _label_new(doc: dict, run: dict, item: dict) -> dict:
    """Every item gets a unique label so later edits can address it."""
    item = dict(item)
    if "kind" not in item:
        raise EditError(f"item needs a kind: {item}")
    if item.get("label"):
        if item["label"] in _all_labels(doc):
            raise EditError(f"label '{item['label']}' already exists")
        return item
    stem = item.get("id", item.get("ref", item["kind"]))
    stem = stem.split(":")[-1] if ":" in stem else stem
    base = f"{run['wall']}-{item['kind'] if item['kind'] in ('filler', 'gap', 'panel') else stem}"
    labels = _all_labels(doc)
    n = 1
    cand = base
    while cand in labels:
        n += 1
        cand = f"{base}-{n}"
    item["label"] = cand
    return item


def _position(run: dict, op: dict, default_end: bool = True) -> int:
    if "index" in op:
        i = int(op["index"])
        if i < 0 or i > len(run["items"]):
            raise EditError(f"index {i} out of range for a run with {len(run['items'])} items")
        return i
    for key, offset in (("before", 0), ("after", 1)):
        if key in op:
            for i, it in enumerate(run["items"]):
                if it.get("label") == op[key]:
                    return i + offset
            raise EditError(f"no item labelled '{op[key]}' in that run")
    return len(run["items"]) if default_end else 0


# ---------------------------------------------------------------- operations

def op_replace(doc: dict, op: dict) -> str:
    run, i = _find_label(doc, op["label"])
    items = op.get("items") or ([op["item"]] if "item" in op else None)
    if not items:
        raise EditError("replace needs 'items' (a list) or 'item'")
    old = run["items"].pop(i)
    new = [_label_new(doc, run, it) for it in items]
    run["items"][i:i] = new
    return f"replaced {old.get('label')} with {', '.join(it['label'] for it in new)}"


def op_insert(doc: dict, op: dict) -> str:
    if "label" in op and "wall" not in op:
        raise EditError("insert takes wall/level (+ index|before|after) and item; to replace an item use replace")
    run = _find_run(doc, op["wall"], op["level"], int(op.get("run", 0)))
    pos = _position(run, op)
    item = _label_new(doc, run, op["item"])
    run["items"].insert(pos, item)
    return f"inserted {item['label']} at position {pos} on wall {run['wall']} {run['level']}"


def op_remove(doc: dict, op: dict) -> str:
    run, i = _find_label(doc, op["label"])
    run["items"].pop(i)
    return f"removed {op['label']}"


def op_move(doc: dict, op: dict) -> str:
    run, i = _find_label(doc, op["label"])
    item = run["items"].pop(i)
    if "to" in op:
        t = op["to"]
        run = _find_run(doc, t["wall"], t["level"], int(t.get("run", 0)))
        pos = _position(run, t)
    else:
        pos = _position(run, op)
    run["items"].insert(pos, item)
    return f"moved {op['label']} to position {pos} on wall {run['wall']} {run['level']}"


def op_swap(doc: dict, op: dict) -> str:
    ra, ia = _find_label(doc, op["label"])
    rb, ib = _find_label(doc, op["with"])
    ra["items"][ia], rb["items"][ib] = rb["items"][ib], ra["items"][ia]
    return f"swapped {op['label']} and {op['with']}"


def op_set_fronts(doc: dict, op: dict) -> str:
    run, i = _find_label(doc, op["label"])
    it = run["items"][i]
    if it["kind"] != "cabinet":
        raise EditError(f"{op['label']} is a {it['kind']}, not a cabinet")
    it["fronts"] = [{"id": f["id"], "count": int(f.get("count", 1))} for f in op["fronts"]]
    return f"set fronts on {op['label']}"


def op_set_width(doc: dict, op: dict) -> str:
    run, i = _find_label(doc, op["label"])
    it = run["items"][i]
    if it["kind"] not in ("filler", "panel", "gap"):
        raise EditError(f"{op['label']} is a {it['kind']}; only fillers, panels and gaps take a width")
    it["width"] = int(op["width"])
    return f"set {op['label']} width to {op['width']} mm"


def op_fit_width(doc: dict, op: dict) -> str:
    """Size a filler, panel or gap so its run closes exactly: the run's span less everything else in it.

    The width is computed from the resolved run, never typed, and the validator still judges the result
    (a strip narrower than the cut minimum, or a wall end under 51 mm, is refused as usual).
    """
    run, i = _find_label(doc, op["label"])
    it = run["items"][i]
    if it["kind"] not in ("filler", "panel", "gap"):
        raise EditError(f"{op['label']} is a {it['kind']}; only fillers, panels and gaps can be fitted")
    k = _resolve(doc)
    placed = next((p for r in k.runs for p in r.items if p.label == op["label"]), None)
    resolved_run = next(r for r in k.runs if any(p.label == op["label"] for p in r.items))
    if any(p.unresolved for p in resolved_run.items):
        raise EditError(f"cannot fit {op['label']}: an item in its run has an unknown catalog id")
    width = resolved_run.length - (resolved_run.used - placed.width)
    if width < 0:
        raise EditError(f"cannot fit {op['label']}: the other items in its run already overrun the span by {-width} mm")
    it["width"] = int(width)
    return f"fitted {op['label']} to {width} mm"


def op_add_run(doc: dict, op: dict) -> str:
    """A new run on a wall: {wall, level, from?, to?, bottom?, items?[]}. Items are labelled like inserts."""
    level = op.get("level")
    if level not in LEVELS:
        raise EditError(f"add_run needs a level, one of {', '.join(LEVELS)}")
    walls = _resolve(doc).room.order
    if op["wall"] not in walls:
        raise EditError(f"room has no wall '{op['wall']}' (walls: {', '.join(walls)})")
    run: dict[str, Any] = {"wall": op["wall"], "level": level, "items": []}
    for key in ("from", "to", "bottom"):
        if key in op and op[key] is not None:
            run[key] = int(op[key])
    if "top" in op and op["top"] is not None:
        run["top"] = int(op["top"])
    _runs(doc).append(run)
    for it in op.get("items") or []:
        run["items"].append(_label_new(doc, run, it))
    span = f" from {run['from']}" if "from" in run else ""
    span += f" to {run['to']}" if "to" in run else ""
    return f"added a {level} run on wall {op['wall']}{span} with {len(run['items'])} item(s)"


def op_remove_run(doc: dict, op: dict) -> str:
    """Remove the n-th run (default the first) of a wall and level, with everything in it."""
    run = _find_run(doc, op["wall"], op["level"], int(op.get("run", 0)))
    _runs(doc).remove(run)
    gone = [it.get("label") for it in run["items"]]
    return f"removed the {op['level']} run on wall {op['wall']}" + (f" and its {len(gone)} item(s): {', '.join(gone)}" if gone else "")


def op_set_material(doc: dict, op: dict) -> str:
    doc.setdefault("materials", {})[op["role"]] = op["key"]
    return f"set materials.{op['role']} = {op['key']}"


def op_set(doc: dict, op: dict) -> str:
    """Set a dotted top-level path such as counter.thickness or appliances.range.width."""
    parts = op["path"].split(".")
    if parts[0] in ("runs",):
        raise EditError("use the run operations to edit runs")
    node = doc
    for key in parts[:-1]:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):
            raise EditError(f"{op['path']}: '{key}' is not an object")
    node[parts[-1]] = op["value"]
    return f"set {op['path']} = {op['value']!r}"


OP_FUNCS = {
    "replace": op_replace, "insert": op_insert, "remove": op_remove, "move": op_move, "swap": op_swap,
    "set_fronts": op_set_fronts, "set_width": op_set_width, "fit_width": op_fit_width, "set_material": op_set_material, "set": op_set,
    "add_run": op_add_run, "remove_run": op_remove_run,
}

_RESOLVE_PATH: list[Path] = []   # the file being edited, so fit_width can resolve the room and catalog mid-batch


def _resolve(doc: dict) -> Kitchen:
    try:
        return kitchen_from_dict(doc, _RESOLVE_PATH[-1])
    except FileError as exc:
        raise EditError(f"cannot resolve the layout: {exc}") from exc


# ---------------------------------------------------------------- apply

def _bom_diff(before: list[BomLine], after: list[BomLine]) -> list[dict[str, Any]]:
    b = {l.id: l for l in before}
    a = {l.id: l for l in after}
    out = []
    for id_ in sorted(set(b) | set(a)):
        qb = b[id_].qty if id_ in b else 0
        qa = a[id_].qty if id_ in a else 0
        name = (a.get(id_) or b.get(id_)).name
        detail_changed = id_ in a and id_ in b and a[id_].detail != b[id_].detail
        if qa != qb or detail_changed:
            out.append({"id": id_, "name": name, "before": qb, "after": qa, "delta": qa - qb, **({"detail": a[id_].detail} if id_ in a and a[id_].detail else {})})
    return out


def runs_summary(k: Kitchen) -> list[dict[str, Any]]:
    out = []
    for r in k.runs:
        out.append({
            "wall": r.wall, "level": r.level, "span": [r.start, r.end], "used_mm": r.used, "length_mm": r.length,
            "items": [{"label": p.label, "kind": p.kind, "id": p.catalog_item.id if p.catalog_item else None,
                       "ref": p.appliance.ref if p.appliance else None, "start": p.start, "end": p.end, "width": p.width,
                       "fronts": [{"id": fu.item.id, "count": fu.count} for fu in p.fronts]} for p in r.items],
        })
    return out


def apply(path: str | Path, ops: list[dict], dry_run: bool = False) -> EditResult:
    """Apply operations to the kitchen file at `path`; write only if the result validates clean."""
    loaded = load_validated(path, "kitchen")
    before_doc = loaded.data
    doc = copy.deepcopy(before_doc)
    messages = []
    _RESOLVE_PATH.append(loaded.path)
    try:
        for n, op in enumerate(ops):
            kind = op.get("op")
            if kind not in OP_FUNCS:
                raise EditError(f"op {n}: unknown op '{kind}' (one of {', '.join(OPS)})")
            try:
                messages.append(OP_FUNCS[kind](doc, op))
            except KeyError as exc:
                raise EditError(f"op {n} ({kind}): missing field {exc}") from exc
    finally:
        _RESOLVE_PATH.pop()

    try:
        k_before = kitchen_from_dict(before_doc, loaded.path)
        k_after = kitchen_from_dict(doc, loaded.path)
    except (FileError, KeyError) as exc:
        return EditResult(False, False, str(loaded.path), [Finding("error", "schema", str(exc))], message="; ".join(messages))

    findings = validate(k_after)
    errors = [f for f in findings if f.is_error]
    if errors:
        return EditResult(False, False, str(loaded.path), findings, [], runs_summary(k_after),
                          message="refused: " + "; ".join(messages) + " → " + "; ".join(f.render() for f in errors))
    diff = _bom_diff(bill_of_materials(k_before), bill_of_materials(k_after))
    written = False
    if not dry_run:
        loaded.path.write_text(json.dumps(doc, indent=2) + "\n")
        written = True
    return EditResult(True, written, str(loaded.path), findings, diff, runs_summary(k_after), message="; ".join(messages))


FIXTURE_DIR_NAME = "examples"
VARIATIONS_DIR_NAME = "variations"


def is_fixture(path: Path) -> bool:
    """Files under examples/ are the repo's generated test fixtures, not working layouts."""
    return FIXTURE_DIR_NAME in Path(path).resolve().parts


def branch(path: str | Path, name: str, dest_dir: str | Path | None = None) -> Path:
    """Start a variation: copy the kitchen file to a new file named after the intent.

    A variation of a fixture under examples/ goes to variations/ next to
    examples/ so the fixtures stay untouched; otherwise it lands beside the
    source. The room path is rewritten to stay valid. Variations are files;
    git is how they are versioned (`git checkout -b variation/<name>` is the
    convention), but this function never touches git.
    """
    import os

    src = Path(path).resolve()
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name.strip().lower()).strip("-")
    if not safe:
        raise EditError("branch needs a name")
    if dest_dir is not None:
        dst_dir = Path(dest_dir)
    elif is_fixture(src):
        dst_dir = src.parent.parent / VARIATIONS_DIR_NAME
    else:
        dst_dir = src.parent
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{safe}.json"
    if dst.exists():
        raise EditError(f"{dst} already exists")
    doc = load_validated(src, "kitchen").data
    doc["name"] = f"{doc['name']} — {name}"
    room_abs = (src.parent / doc["room"]).resolve()
    doc["room"] = os.path.relpath(room_abs, dst_dir)
    dst.write_text(json.dumps(doc, indent=2) + "\n")
    return dst
