# Millimeter Kitchen — Approach

## The one design decision: the model is object-centric, renders are views

A kitchen layout is a structured list: a wall run of cabinet frames with
nominal widths, fronts, panels, fillers, a countertop and appliances, each
with a catalog id and a dimension. The tool's source of truth is a plain file
that lists exactly that. The 2D elevation, the 3D scene, the render and the
bill of materials are generated from it and never edited by hand.

Dimensions flow one way: in from a tape measure or an IKEA product page, into
`kitchen.json`, out to drawings, 3D and the purchase list. No AI model, LiDAR
scan or photo tool may write a dimension directly. They may only propose edits
to the file, which the validator accepts or rejects.

A variation is a branch of a small text file; the diff between two variations
is a readable list of which cabinets changed.

## Architecture

```
room survey (tape/laser) ──┐
LiDAR scan (hints only) ───┼──▶ kitchen.json ──▶ fit validator (every save)
SEKTION catalog ───────────┘        │
                                    ├──▶ elevations + plan (SVG/PDF)
Claude via MCP ── proposes ─────────┤
                                    ├──▶ Blender + Home Builder 5 ──▶ glTF, renders
                                    └──▶ bill of materials ──▶ IKEA Kitchen Planner (reconcile, buy)

────────────── dimensional boundary: nothing below writes a number above ──────────────
photo-to-render AI (GenRoom, MeltFlex, Decor8) ──▶ mood board (finish, lighting, style)
```

## Tool inventory

| Layer | Tool | Trust | Why |
|---|---|---|---|
| Capture | Laser meter + tape | truth | Only source of wall lengths. |
| Capture | RoomPlan / Polycam / IKEA Kreativ | hint | Rough envelope. RoomPlan models all walls ~16 cm thick. |
| Catalog | IKEA product pages | truth | Actual dimensions per article. |
| Catalog | IKEA Rotera GLB endpoint, 3D Warehouse SEKTION packs | hint | Meshes for looks. |
| Geometry | build123d | truth | Exact solids for fillers, countertop, clearance math. |
| 3D | Blender + Home Builder 5 (GPL 3) | truth | Parametric cabinets, drawings, cut lists; driven by script. |
| 3D | blender-mcp | hint | Camera, materials, what-ifs. |
| AI edit | Claude over a small MCP server | hint | Natural-language variation; validator has the last word. |
| AI render | GenRoom, MeltFlex, Decor8 | mood | Pictures only. |
| Purchase | IKEA Kitchen Planner | truth | Final arbiter; reconcile item lists. |

## Decisions

- **IKEA fronts only.** The catalog carries IKEA front series (ENKÖPING, BODBYN,
  AXSTAD, …); the validator rejects any other brand.
- **Millimeters internally**, inches only as nominal labels.
- **Python core, Blender for 3D.** build123d, bpy and Home Builder are Python.
- **Files over databases.** One JSON per variation, in git.
- **IKEA's planner as final arbiter.** Fast thinking here, ordering there.

## SEKTION, US market (published sizes, verify per article before buying)

| Cabinet | Widths (in) | Heights (in) | Depths (in) |
|---|---|---|---|
| Base | 12 15 18 21 24 30 36 | 30 | 24 · 15 |
| Base, sink | 30 36 | 30 | 24 |
| Base, corner | 47 × 28 | 30 | — |
| Wall | 12 15 18 21 24 30 36 | 15 20 30 40 | 12 · 24 over fridge |
| Wall, corner | 26 × 26 | 30 · 40 | — |
| High | 24 30 | 80 90 | 24 |
| Doors / drawer fronts | nominal − 1/8" each way | | |
| Fillers | ≥ 2" at walls, cut from 10" strips | | |

Things the tool refuses to guess: appliance cutouts (entered from the
manufacturer sheet), walls that are not straight (survey records plumb and
diagonals), countertop slabs (exported as an outline drawing, not a number),
anything a scan or image model said.
