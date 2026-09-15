# Millimeter Kitchen

> **Work in progress.** Every phase is built and tested: room survey checks,
> a SEKTION catalog verified article by article on ikea.com, the fit
> validator, dimensioned drawings, a 3D scene with real-scale textures and
> Blender renders, named finishes, validator-gated edits from Claude over MCP,
> and a purchase pack with reconciliation against IKEA's item list. What is
> still missing is the real room: `examples/room.example.json` is illustrative,
> and the purchase pack has not yet been reconciled against a real IKEA
> Kitchen Planner export, so nothing here is ready to buy from. See the status
> tracker at the bottom of [docs/BUILD_ORDER.md](docs/BUILD_ORDER.md).

A dimension-accurate planning tool for a kitchen remodel using IKEA SEKTION
frames and IKEA fronts. The layout is a plain JSON file; a deterministic
validator checks that everything in it fits the measured room before any of it
is drawn, rendered, or bought.

Read [docs/PLAN.md](docs/PLAN.md) for the approach and
[docs/BUILD_ORDER.md](docs/BUILD_ORDER.md) for the phases and what is built.

## Planned tools

Every dimension enters from a tape measure or an IKEA product page and lives in
`kitchen.json`. The tools below either feed that file, check it, or render from
it. None of them writes a dimension on its own.

| Layer | Tool | Role | Status |
|---|---|---|---|
| Capture | Laser distance meter + tape | The only source of wall lengths. Entered by hand per `docs/SURVEY_PROTOCOL.md`. | In use (phase 0) |
| Capture | Apple RoomPlan / Polycam / IKEA Kreativ | Optional LiDAR rough-in of the room envelope. Hints only; the survey overrides it. | Planned |
| Catalog | IKEA US product pages and search API | `tools/scrape_sektion.py --sweep` enumerates an article family by number (the leading digit is a Luhn check), `--discover` matches entries by series, type, size and finish, and the verify pass reads each product page. | Built; all 215 entries carry an article number and the product page's size, verified on ikea.com (2026-09-14) |
| Catalog | IKEA Rotera GLB models | IKEA's own mesh per article, fetched by `mmk ikea-models fetch` into a cache outside the repo and swapped into Blender renders with `--ikea-models`. Pictures only: the box scene places them, never the reverse, and `mmk ikea-models check` only reports when a model's size disagrees with the catalog. | Built; swap checked in Blender renders |
| Validation | Python, `jsonschema`, pytest | Schema checks and the fit rules: run closure, fillers, clearances, openings, services, front sizes. | Built (phase 1) |
| Geometry | build123d | Exact solids for countertop outlines and the countertop cut drawing. | Planned (phase 6) |
| Drawings | Generated SVG | Dimensioned elevations per wall and a plan view for contractors and fabricators, at a chosen print scale. | Built (phase 2) |
| 3D and renders | glTF export (pure Python) + Blender | `mmk render` writes `scene.glb` with a named node per cabinet, front, counter and wall, then Blender imports it and renders one image per wall. Finishes come from `catalog/finishes.json` by role, with procedural wood, tile and stone textures embedded in the glTF at real-world scale; Home Builder 5 is optional detail. | Built (phases 3 and 4) |
| 3D and renders | blender-mcp | Lets an AI assistant adjust cameras, lighting and materials in the live scene. Never the path a dimension travels. | Planned (phase 4) |
| Review | Static HTML + three.js | Every export writes `out/<file>/index.html` (drawings, renders, embedded 3D viewer, runs, purchase pack, assumptions) and `out/index.html` listing all layouts; pages flag themselves stale when the source file changes. | Built; checked in Chrome |
| Variations | Claude via `mmk mcp` (MCP Python SDK, 1.x or 2.x) | Natural-language edits ("swap the 36 for two 18s with drawers") become `apply_ops` calls that are refused unless the result fits. Variations are sibling files; branch them in git. | Built (phase 5) |
| Variations | Layout editor, `mmk serve` | A local page (standard-library HTTP server, no build step) that lists the runs, edits frames, fronts, fillers, appliances and finishes through the same validator-gated operations, and shows the plan, elevations, 3D scene, BOM and purchase pack, refreshed after every edit that fits. | Built; checked in Chrome |
| Mood | GenRoom, MeltFlex, Decor8 | Photo-to-photo restyles for finishes and lighting, fed a validated render. Pictures only. | Optional (phase 4) |
| Purchase | IKEA Kitchen Planner | The final arbiter. `mmk purchase` derives the full pack; `mmk reconcile` diffs it against the planner's item list saved as CSV. | Built; waits on a real planner export to reconcile (phase 6) |

## Install

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Use

```sh
# Phase 0: check a room survey for internal consistency
mmk survey check examples/room.example.json

# Phase 1: look things up in the catalog
mmk catalog list --kind frame
mmk catalog show frame:base:36x24x30

# Phase 1: validate a layout against its room and the catalog
mmk validate examples/kitchen.fits.json
mmk validate examples/bad/run_too_long.json     # exits 1, names the item

# Phase 2: dimensioned elevations and plan, SVG in real mm at 1:20
mmk draw examples/kitchen.fits.json --out out/

# Phase 3: 3D scene as glTF, then one Blender render per wall (finds Blender on PATH,
# in /Applications or Program Files; otherwise --blender /path or MMK_BLENDER=/path)
mmk render examples/kitchen.fits.json --out out/
mmk render examples/kitchen.fits.json --out out/ --no-render   # glTF + cameras only

# Optional: IKEA's own meshes in the renders (cached under ~/Library/Caches or ~/.cache, never in the repo)
mmk ikea-models fetch examples/kitchen.fits.json     # every article the layout uses that has a model
mmk ikea-models check examples/kitchen.fits.json     # model bounding box vs catalog, report only
mmk render examples/kitchen.fits.json --out out/ --ikea-models
python -m http.server   # then open http://localhost:8000/viewer/index.html?scene=../out/scene.glb

# Phase 4: finishes and the bill of materials
mmk finishes list                       # every finish by role, defaults marked
mmk bom examples/kitchen.fits.json      # frames, fronts, fillers, appliances, finishes

# Phase 5: edits that the validator must approve
mmk edit examples/kitchen.fits.json '{"op":"set_material","role":"counter","key":"butcher-block-oak"}' --dry-run
mmk edit examples/kitchen.fits.json '{"op":"remove","label":"N-base-30"}'   # refused: run_closure, file unchanged
# a successful edit re-exports drawings + scene.glb into out/<file stem>/; add --render for Blender images

# Phase 6: purchase pack and reconciliation with IKEA's item list
mmk purchase examples/kitchen.fits.json --out out/kitchen.fits/
mmk reconcile examples/kitchen.fits.json ikea-items.csv --explain notes.json
mmk catalog import ikea-items.csv --write      # article numbers from the planner's list into the catalog

# Review in a browser: every export writes out/<file>/index.html and out/index.html
mmk export examples/kitchen.fits.json           # or any successful mmk edit / apply_ops
python -m http.server                           # then open http://localhost:8000/out/

# Edit in a browser: the layout editor over the same operations as mmk edit and the MCP server
mmk serve                                       # opens http://127.0.0.1:8760/ ; fixtures are read only, "Start variation" copies one
```

## Claude as a design assistant

Install the MCP extra and let Claude Code or Claude Desktop drive the same
operations. Every edit goes through the fit validator; a proposal that does
not fit is refused and the file is unchanged.

```sh
pip install -e ".[mcp]"
```

Claude Code picks up the repo's `.mcp.json` automatically when you run it in
this folder. For Claude Desktop, add to its MCP settings (adjust the paths):

```json
{
  "mcpServers": {
    "millimeter-kitchen": {
      "command": "/Users/robbie/GitHub/millimeter-kitchen/.venv/bin/mmk",
      "args": ["mcp", "--root", "/Users/robbie/GitHub/millimeter-kitchen"]
    }
  }
}
```

Then ask, for example: "Start a variation of examples/kitchen.fits.json
called drawers everywhere, replace the 30-inch base with two 15s with three
drawers each, and redraw." Claude will call `start_variation` (which copies
the fixture into `variations/`), `search_catalog` for the ids, `apply_ops`
with a `replace`, and report the bill-of-materials diff. Every successful
edit re-exports the drawings and `scene.glb` into `out/<file stem>/`; ask for
`export` with render on if you want fresh Blender images too. Ask for something
that cannot fit and it reports the validator's refusal instead. Files under
`examples/` are test fixtures and `apply_ops` refuses to change them.

```sh

# run the tests
pytest -q
```

## Layout

```
docs/                 plan, build order with status tracker, survey protocol
schema/               JSON Schema for room, catalog and kitchen files
catalog/              SEKTION catalog (regenerate with tools/build_catalog_seed.py <file>; verified entries survive), finishes.json (hand-maintained) and textures/ (regenerate with tools/build_textures.py)
examples/             one room, two kitchens that fit (one with corner cabinets), seven that do not
src/mmk/              the package: units, io, room, catalog, model, rules, draw, scene, gltf, finishes, textures, ikea_models, bom, edit, export, review, purchase, reconcile, planner_import, tools, mcp_server, cli
tools/                catalog seed generator, fixture generator, product-page scraper, texture builder, Blender render script
viewer/               three.js walkthrough for scene.glb
tests/                pytest
```
