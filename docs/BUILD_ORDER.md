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
| `corner_overlap.json` | `corner_overlap` |

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

`catalog/finishes.json` maps front series and every other surface to PBR
values; `kitchen.json` picks finishes by role in `materials`; `mmk bom` lists
what the layout uses. Textures (wood grain, veining, tile grout) are a later
refinement; phase 4 is flat PBR.

**Accept:** changing one finish string and regenerating changes only that; the
BOM lists the new front ids.

## Phase 5 — Variations through Claude

`mmk mcp` serves `describe`, `search_catalog`, `list_finishes`, `apply_ops`,
`validate`, `bom`, `start_variation`, `draw` and `render`. `apply_ops` takes a
batch of operations, applies them to a copy, validates, and writes only on a
clean result; otherwise it refuses and returns the errors. The same operations
run from the shell as `mmk edit`.

**Accept:** "replace the 36 base with two 18s with three drawers each" produces
a valid file and a BOM diff with no manual edits; an impossible request is
refused with the `run_closure` error.

## Phase 6 — Purchase pack and reconciliation

`mmk purchase kitchen.json --out out/` writes the pack (catalog items plus
derived rail, legs, hinges, drawers, cover panels, toe kick, filler stock),
`countertop.svg`, and the assumptions behind every derived line. Rebuild the
layout in the official IKEA Kitchen Planner, save its item list as CSV, and run
`mmk reconcile kitchen.json items.csv --explain notes.json`.

**Accept:** zero unexplained differences.

---

## Review page

Not a phase: every export also writes a static `index.html` per layout and an
index over all exports, with an embedded three.js viewer and a browser-side
staleness check against the source file's hash.

## Current Status Tracker

| Phase | Status | Notes |
|---|---|---|
| 0 — Survey | **Scaffolded** | Protocol, schema, `mmk survey check` and tests exist. Real room not yet measured; `examples/room.example.json` is illustrative. |
| 1 — Catalog + validator | **Scaffolded** | Six rules with good/bad fixtures pass. Catalog is a seed from published size guides, all `verified: false`; scraper written but untested against ikea.com. Corner cabinets (carousel base, blind base, corner wall) are modeled with placement, overlap and dead-space rules; `examples/kitchen.corner.json` shows them, together with door-and-drawer combinations (fronts are rows top to bottom; rows must tile the frame). |
| 2 — Elevations | **Scaffolded** | `mmk draw` writes an SVG elevation per wall and a plan view in real millimeters at a chosen print scale, with running dimensions, front splits, openings, services and a title block listing totals and fillers. Tests check geometry against the catalog. Corner geometry in plan assumes 90° turns. |
| 3 — 3D | **Scaffolded** | `mmk render` builds the scene (walls cut around openings, floor, frames, door and drawer panels, toe kicks, counters, appliances, fillers) as axis-aligned boxes from `kitchen.json`, writes `scene.glb` with one named node per object and a camera per wall plus an overview, then runs `tools/blender_render.py` to render each camera. glTF bounding boxes are tested against the catalog within 1 mm and export is deterministic. The Blender script has been run on macOS (Eevee, 3 renders in ~8 s) and writes `render-<camera>.png` per camera. Home Builder 5 not used; plain boxes only. `viewer/index.html` is a three.js walkthrough, untested. |
| 4 — Materials | **Scaffolded** | `catalog/finishes.json` is the finish library (IKEA front series, frames, counters, backsplash, floor, wall paint, appliances, toe kick) with sRGB color, roughness and metallic. `kitchen.json` names finishes by role in a `materials` block; fronts take theirs from the catalog series. The scene carries them into glTF PBR materials, and a backsplash surface fills from the counter to the wall cabinets. `mmk bom` lists frames, fronts, fillers, appliances and finishes. Colors are approximations from product photos, no textures yet, and Blender renders with the new materials have not been checked visually. |
| 5 — Claude/MCP | **Scaffolded** | `mmk.edit` applies operations (replace, insert, remove, move, swap, set_fronts, set_width, set_material, set) to the file and writes only if the validator passes; a refused edit leaves the file untouched and returns the errors and a BOM diff. `mmk edit` exposes it on the shell; `mmk mcp` serves it over MCP (FastMCP, `pip install -e .[mcp]`) with describe, search_catalog, list_finishes, apply_ops, validate, bom, start_variation, draw and render. `.mcp.json` configures Claude Code. Every successful edit re-exports drawings and the glTF scene into `out/<kitchen stem>/` with a manifest carrying the source hash; Blender renders are opt-in. Verified live from Claude Code on macOS: the acceptance edit was applied through the server with the right BOM diff and redrawn. Files under `examples/` are fixtures; `apply_ops` refuses to write them and `start_variation` copies them into `variations/`. Variations are files, with git branches as the convention rather than something the tool drives. |
| 6 — Purchase pack | **Scaffolded** | `mmk purchase` derives rail, legs, hinges, MAXIMERA drawers, cover panels on exposed sides, toe kick and filler stock from the layout, each with the rule that produced it, writes `purchase-pack.md`/`.csv` and a `countertop.svg` outline, and lists what is out of scope. `mmk reconcile` compares against an IKEA Kitchen Planner item list (CSV/TSV) with explained differences. Both are in `export_all` and the MCP server. `mmk catalog import items.csv --write` pulls article numbers from the planner's item list into the catalog by matching kind, series, finish and nominal size, refusing ambiguous rows. Acceptance still waits on a real planner export: the seed carries only two article numbers. |
