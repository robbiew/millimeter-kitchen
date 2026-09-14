# Millimeter Kitchen

> **Work in progress.** Phases 0 to 3 (room survey checks, SEKTION catalog,
> fit validator, dimensioned drawings, 3D scene export and Blender rendering)
> are scaffolded and tested, `mmk render` produces Blender renders, and phase 4
> gives every surface a named finish, and phase 5 lets Claude edit the layout
> through an MCP server whose every change is validator-gated, and phase 6
> derives the purchase pack and reconciles it against IKEA's item list. What
> blocks buying is the catalog: only two entries carry verified article numbers. The catalog's dimensions come from
> published size guides and are not yet verified against IKEA product pages,
> so nothing here is ready to buy from. See the status tracker at the bottom of
> [docs/BUILD_ORDER.md](docs/BUILD_ORDER.md).

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
| Catalog | IKEA US product pages | Actual cabinet and front dimensions per article number, read by `tools/scrape_sektion.py`. | Scraper written, untested |
| Catalog | IKEA Rotera GLB models, SketchUp 3D Warehouse SEKTION packs | Reference meshes for how fronts and frames look. | Planned (phase 3) |
| Validation | Python, `jsonschema`, pytest | Schema checks and the fit rules: run closure, fillers, clearances, openings, services, front sizes. | Built (phase 1) |
| Geometry | build123d | Exact solids for countertop outlines and the countertop cut drawing. | Planned (phase 6) |
| Drawings | Generated SVG | Dimensioned elevations per wall and a plan view for contractors and fabricators, at a chosen print scale. | Built (phase 2) |
| 3D and renders | glTF export (pure Python) + Blender | `mmk render` writes `scene.glb` with a named node per cabinet, front, counter and wall, then Blender imports it and renders one image per wall. Finishes come from `catalog/finishes.json` by role; Home Builder 5 is optional detail. | Built (phases 3 and 4) |
| 3D and renders | blender-mcp | Lets an AI assistant adjust cameras, lighting and materials in the live scene. Never the path a dimension travels. | Planned (phase 4) |
| Viewer | three.js | `viewer/index.html` loads `scene.glb` for a browser walkthrough with a button per camera. | Written, untested (phase 3) |
| Variations | Claude via `mmk mcp` (FastMCP) | Natural-language edits ("swap the 36 for two 18s with drawers") become `apply_ops` calls that are refused unless the result fits. Variations are sibling files; branch them in git. | Built (phase 5) |
| Mood | GenRoom, MeltFlex, Decor8 | Photo-to-photo restyles for finishes and lighting, fed a validated render. Pictures only. | Optional (phase 4) |
| Purchase | IKEA Kitchen Planner | The final arbiter. `mmk purchase` derives the full pack; `mmk reconcile` diffs it against the planner's item list saved as CSV. | Built, blocked on catalog articles (phase 6) |

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

# Phase 3: 3D scene as glTF, then one Blender render per wall (needs blender on PATH)
mmk render examples/kitchen.fits.json --out out/
mmk render examples/kitchen.fits.json --out out/ --no-render   # glTF + cameras only
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
catalog/              SEKTION catalog (generated by tools/build_catalog_seed.py) and finishes.json (hand-maintained)
examples/             one room, one kitchen that fits, six that do not
src/mmk/              the package: units, io, room, catalog, model, rules, draw, scene, gltf, finishes, bom, edit, export, purchase, reconcile, tools, mcp_server, cli
tools/                catalog seed generator, fixture generator, product-page scraper, Blender render script
viewer/               three.js walkthrough for scene.glb
tests/                pytest
```
