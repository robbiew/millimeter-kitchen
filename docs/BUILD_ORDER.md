# Build Order

No phase starts until the previous phase's acceptance test passes. Phases 0 and
1 contain all of the purchasing accuracy and no 3D at all, on purpose.

## Phase 0 — Survey the room

Deliverables: `docs/SURVEY_PROTOCOL.md`, `schema/room.schema.json`,
`mmk survey check`.

Measure every wall at floor, 914 mm (36") and 2134 mm (84"); both diagonals of
every corner; ceiling at each corner; every window, door, outlet, switch,
plumbing centerline, gas stub and vent.

**Accept:** each wall's three measurements agree within 6 mm, every corner has
a diagonal, `room.json` validates against the schema, and `mmk survey check`
exits 0.

## Phase 1 — Catalog and fit validator

Deliverables: `catalog/sektion-us-*.json`, `schema/catalog.schema.json`,
`schema/kitchen.schema.json`, `mmk validate`, `tools/scrape_sektion.py`.

**Accept:** `examples/kitchen.fits.json` passes with zero errors; each fixture
in `examples/bad/` fails with a finding that names the rule and the offending
item:

| fixture | rule |
|---|---|
| `run_too_long.json` | `run_closure` |
| `dishwasher_against_wall.json` | `appliance_side_clearance` |
| `wall_cabinet_over_window.json` | `opening_conflict` |
| `wrong_size_front.json` | `front_fit` |
| `missing_filler.json` | `wall_filler_min` |
| `blocked_drain.json` | `service_conflict` |

Also: every catalog entry used in a purchase must be `"verified": true`
(product page fetched by the scraper). Until then `mmk validate` warns.

## Phase 2 — Dimensioned elevations and plan

Deliverables: `mmk draw kitchen.json --out out/ --scale 20`. SVG elevation per wall and a
plan view with running dimensions, generated from `kitchen.json`. Every SVG
coordinate is a real millimeter; the page size is the viewBox divided by the
print scale.

**Accept:** printed at scale, a caliper on the drawing matches the file; every
cabinet shows nominal width and catalog id; the sheet lists total run and
filler widths.

## Phase 3 — 3D scene in Blender

`mmk render kitchen.json --out out/`. The scene is built in Python as boxes
from `kitchen.json` and written to `scene.glb` (so the geometry can be tested
without Blender), then `tools/blender_render.py` imports it, places one camera
per wall and renders. Home Builder 5 parametric cabinets are an option for
phase 4 detail, not a phase 3 requirement.

**Accept:** the bounding box of every placed object matches its `actual`
dimensions within 1 mm; regenerating replaces the scene without cleanup; one
scripted camera produces a rendered image of each wall from `mmk render` with
no manual step in Blender.

## Phase 4 — Materials and appearance

Front series and finishes mapped to Blender materials; countertop, backsplash,
floor and paint as named materials in the file.

**Accept:** changing one finish string and regenerating changes only that; the
BOM lists the new front ids.

## Phase 5 — Variations through Claude

An MCP server exposing `list_run`, `place`, `move`, `swap`, `branch`,
`validate`. Each tool applies a change and returns the validator's verdict.

**Accept:** "replace the 36 base with two 18s with three drawers each" produces
a valid file and a BOM diff with no manual edits; an impossible request is
refused with the `run_closure` error.

## Phase 6 — Purchase pack and reconciliation

BOM by article number, including rail, legs, cover panels, toe kicks, fillers,
hinges, runners, lighting. Rebuild in the official IKEA Kitchen Planner and diff
its item list against the BOM.

**Accept:** zero unexplained differences.

---

## Current Status Tracker

| Phase | Status | Notes |
|---|---|---|
| 0 — Survey | **Scaffolded** | Protocol, schema, `mmk survey check` and tests exist. Real room not yet measured; `examples/room.example.json` is illustrative. |
| 1 — Catalog + validator | **Scaffolded** | Six rules with good/bad fixtures pass. Catalog is a seed from published size guides, all `verified: false`; scraper written but untested against ikea.com. Corner cabinets not yet modeled. |
| 2 — Elevations | **Scaffolded** | `mmk draw` writes an SVG elevation per wall and a plan view in real millimeters at a chosen print scale, with running dimensions, front splits, openings, services and a title block listing totals and fillers. Tests check geometry against the catalog. Corner geometry in plan assumes 90° turns; countertop outline export (build123d) deferred to phase 6. |
| 3 — 3D | **Scaffolded** | `mmk render` builds the scene (walls cut around openings, floor, frames, door and drawer panels, toe kicks, counters, appliances, fillers) as axis-aligned boxes from `kitchen.json`, writes `scene.glb` with one named node per object and a camera per wall plus an overview, then runs `tools/blender_render.py` to render each camera. glTF bounding boxes are tested against the catalog within 1 mm and export is deterministic. The Blender script is written for 4.x but has not been executed yet (no Blender in the authoring environment). Home Builder 5 not used; plain boxes only. `viewer/index.html` is a three.js walkthrough, untested. |
| 4 — Materials | Not started | |
| 5 — Claude/MCP | Not started | |
| 6 — Purchase pack | Not started | |
