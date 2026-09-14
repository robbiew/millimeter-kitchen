"""Phase 5: the MCP server. Thin registration of `mmk.tools` with FastMCP.

Run with `mmk mcp --root /path/to/repo` (stdio transport). Configure Claude
Code with the repo's `.mcp.json`, or Claude Desktop with the snippet in
README.md. Requires the optional dependency: `pip install -e ".[mcp]"`.

Every tool takes kitchen paths relative to --root and refuses paths outside
it. Edits go through `mmk.edit.apply`, so the validator has the last word.
"""

from __future__ import annotations

from pathlib import Path

from . import tools


def build_server(root: Path):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised only without the extra installed
        raise SystemExit("the MCP server needs the 'mcp' package: pip install -e '.[mcp]'") from exc

    root = root.resolve()
    server = FastMCP(
        "millimeter-kitchen",
        instructions=(
            "Millimeter Kitchen edits a kitchen layout file (kitchen.json) for an IKEA SEKTION remodel. "
            "Dimensions flow one way: survey and catalog -> the file -> drawings, 3D and the bill of materials. "
            "Never guess a dimension: look ids up with search_catalog, read the layout with describe, and change it "
            "only through apply_ops, which refuses any result the fit validator rejects. Report refusals to the user "
            "verbatim rather than working around them. Files under examples/ are test fixtures: call start_variation first and work on the copy."
        ),
    )

    @server.tool()
    def describe(kitchen: str) -> dict:
        """Read the whole layout: walls, runs with every item's label and millimetre interval, materials, appliances, and current findings."""
        return tools.describe(root, kitchen)

    @server.tool()
    def search_catalog(kitchen: str | None = None, kind: str | None = None, type: str | None = None, width_in: float | None = None,
                       height_in: float | None = None, series: str | None = None, text: str | None = None, limit: int = 50) -> dict:
        """Find catalog ids for frames and fronts. kind: frame|front|drawer_front|filler. type: base|sink_base|wall|wall_fridge|high|door|drawer. Sizes are nominal inches."""
        return tools.search_catalog(root, kitchen, kind, type, width_in, height_in, series, text, limit)

    @server.tool()
    def list_finishes(role: str | None = None) -> dict:
        """Finish keys for the materials block, by role: frame, counter, backsplash, floor, wall, appliance, toe_kick."""
        return tools.list_finishes(role)

    @server.tool()
    def apply_ops(kitchen: str, ops: list[dict], dry_run: bool = False, draw_out: str | None = None, allow_fixture_edit: bool = False) -> dict:
        """Apply edit operations to the kitchen file. The file is written only if the result passes every fit rule; otherwise the
        call is refused and returns the errors, and the file is unchanged. Returns the bill-of-materials diff and the new runs.
        Ops: replace{label, items[]} | insert{wall, level, index|before|after, item} | remove{label} | move{label, before|after|index|to{wall,level,index}}
        | swap{label, with} | set_fronts{label, fronts[{id,count}]} | set_width{label, width} | set_material{role, key} | set{path, value}.
        Items: {kind:'cabinet', id, label?, fronts?} | {kind:'appliance', ref} | {kind:'filler'|'gap'|'panel', width}.
        Pass draw_out to regenerate the SVG drawings after a successful edit. Files under examples/ are test fixtures and are refused
        unless allow_fixture_edit is true; call start_variation first and edit the copy."""
        return tools.apply_ops(root, kitchen, ops, dry_run, draw_out, allow_fixture_edit)

    @server.tool()
    def validate(kitchen: str) -> dict:
        """Run the fit validator and report errors and warnings without changing anything."""
        return tools.validate_kitchen(root, kitchen)

    @server.tool()
    def bom(kitchen: str) -> dict:
        """Bill of materials with quantities, article numbers and verification status."""
        return tools.bom(root, kitchen)

    @server.tool()
    def start_variation(kitchen: str, name: str) -> dict:
        """Copy the kitchen file to a new file named for the intent, so the original stays intact. A fixture from examples/ is copied to variations/. Returns the new path to edit."""
        return tools.start_variation(root, kitchen, name)

    @server.tool()
    def draw(kitchen: str, out: str = "out", scale: int = 20) -> dict:
        """Write dimensioned SVG elevations and a plan view."""
        return tools.draw(root, kitchen, out, scale)

    @server.tool()
    def render(kitchen: str, out: str = "out", blender: str | None = None, engine: str = "EEVEE", no_render: bool = False) -> dict:
        """Export scene.glb and render one image per wall with Blender (if available)."""
        return tools.render(root, kitchen, out, blender, engine, no_render)

    return server


def main(root: Path) -> int:
    build_server(root).run()
    return 0
