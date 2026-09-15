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


def _server_class():
    """The MCP Python SDK renamed FastMCP to MCPServer in 2.0; the decorator and run() API is the same."""
    try:
        from mcp.server.mcpserver import MCPServer  # 2.x
        return MCPServer
    except ImportError:
        pass
    try:
        from mcp.server.fastmcp import FastMCP  # 1.x
        return FastMCP
    except ImportError as exc:  # pragma: no cover - exercised only without the extra installed
        raise SystemExit(f"the MCP server needs the 'mcp' package: pip install -e '.[mcp]'  ({exc})") from exc


def build_server(root: Path):
    root = root.resolve()
    server = _server_class()(
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
    def apply_ops(kitchen: str, ops: list[dict], dry_run: bool = False, out: str = "out", allow_fixture_edit: bool = False,
                  render: bool = False, blender: str | None = None) -> dict:
        """Apply edit operations to the kitchen file. The file is written only if the result passes every fit rule; otherwise the
        call is refused and returns the errors, and the file is unchanged. Returns the bill-of-materials diff and the new runs.
        Ops: replace{label, items[]} | insert{wall, level, index|before|after, item} | remove{label} | move{label, before|after|index|to{wall,level,index}}
        | swap{label, with} | set_fronts{label, fronts[{id,count}]} | set_width{label, width} | fit_width{label} | set_material{role, key} | set{path, value}
        | add_run{wall, level, from?, to?, bottom?, items?[]} | remove_run{wall, level, run?}.
        A run must close after every batch: pair an insert, replace or remove with fit_width{label} on a filler or gap in the same run,
        which sizes it so the run closes (the width is computed from the run, never guessed).
        Items: {kind:'cabinet', id, label?, fronts?} | {kind:'appliance', ref} | {kind:'filler'|'gap'|'panel', width}.
        A successful edit re-exports the drawings, scene.glb and cameras.json into <out>/<kitchen stem>/ automatically; pass render=True
        to also render one image per wall in Blender (slower). Files under examples/ are test fixtures and are refused unless
        allow_fixture_edit is true; call start_variation first and edit the copy."""
        return tools.apply_ops(root, kitchen, ops, dry_run, out, allow_fixture_edit, render, blender)

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
    def export(kitchen: str, out: str = "out", scale: int = 20, render: bool = False, blender: str | None = None, engine: str = "EEVEE", ikea_models: bool = False) -> dict:
        """Regenerate drawings, scene.glb, cameras.json and manifest.json into <out>/<kitchen stem>/ without editing anything.
        render=True also produces one Blender image per wall; ikea_models=True swaps boxes for cached IKEA models in those images
        (cache them first with `mmk ikea-models fetch <kitchen>`). describe reports export_stale when the file changed since the last export."""
        return tools.export(root, kitchen, out, scale, render, blender, engine, ikea_models)

    @server.tool()
    def purchase(kitchen: str) -> dict:
        """The purchase pack: every catalog item plus derived rail, legs, hinges, MAXIMERA drawers, cover panels, toe kick and filler stock,
        each derived line with its rule; the countertop slabs; unverified and article-less lines; and what is out of scope."""
        return tools.purchase(root, kitchen)

    @server.tool()
    def reconcile(kitchen: str, ikea_list: str, explanations: dict[str, str] | None = None) -> dict:
        """Compare the purchase pack against an IKEA Kitchen Planner item list saved as CSV/TSV (article number and quantity columns).
        explanations maps article numbers to a reason for an intended difference. ok is true only with zero unexplained differences."""
        return tools.reconcile(root, kitchen, ikea_list, explanations)

    return server


def main(root: Path) -> int:
    build_server(root).run()
    return 0
