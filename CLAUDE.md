# Millimeter Kitchen — Claude Code Instructions

A planning tool for a kitchen remodel built from **IKEA SEKTION cabinets with
IKEA fronts only**. Its job is to produce a layout whose dimensions are exact
enough to buy from.

Read `docs/PLAN.md` first, then `docs/BUILD_ORDER.md`. The **Current Status
Tracker** at the bottom of `BUILD_ORDER.md` is the single source of truth for
what is built.

## The one rule: dimensions flow one way

```
tape measure / product page  →  kitchen.json  →  validator  →  drawings, 3D, BOM
```

- `kitchen.json` (and the `room.json` it references) is the **only** place a
  dimension is authored. Everything else is generated from it.
- The validator (`src/mmk/rules.py`) is deterministic and unit-tested. Every
  rule has a known-good fixture (`examples/kitchen.fits.json`) and at least one
  known-bad fixture under `examples/bad/`.
- No AI model, LiDAR scan or photo tool may write a dimension. They may only
  propose an edit to the file; the validator accepts or rejects it.
- The catalog (`catalog/*.json`) carries every product's **actual** dimension in
  millimeters and its **nominal** inch label. An entry with `"verified": false`
  came from a published size guide, not the product page. Do not treat it as
  purchasable until the scraper in `tools/` has verified it.

## Fronts are IKEA only

The catalog's `front` and `drawer_front` entries must have `"brand": "IKEA"`.
The validator rejects any other brand. Aftermarket fronts (Semihandmade and
similar) are deliberately out of scope; do not add them.

## Units

Millimeters internally, always integers. Inches appear only in `nominal`
labels (the size printed on the IKEA box) and in CLI output when asked.
`src/mmk/units.py` is the only place conversion happens.

## Code style

- Python 3.11+, typed, dataclasses for the model, no ORM, no web framework.
- `jsonschema` for structural validation; every JSON file in `examples/` and
  `catalog/` must validate against its schema in `schema/`.
- Rules are pure functions `(Kitchen, Catalog) -> list[Finding]`. A finding
  names the rule, the wall, and the offending item label.
- Tests with pytest. A rule with no failing fixture is not done.

## What this is NOT

- Not a renderer. 3D and drawings are later phases and are generated, never
  edited.
- Not a replacement for the official IKEA Kitchen Planner. The last phase
  rebuilds the winning variation there and reconciles item lists.
- Not related to any other project in this account; nothing is shared.
