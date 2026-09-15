"""The MCP server builds against either SDK generation; neither is installed in CI, so both import paths are stubbed."""
import sys
import types

import pytest

from mmk import mcp_server


class _Stub:
    """Just enough of MCPServer/FastMCP: records the constructor call and the tools registered."""

    def __init__(self, name, *args, instructions=None, **kwargs):
        self.name, self.instructions, self.tools = name, instructions, []
        assert not args, "positional arguments after the name would land in title/description on 2.x"

    def tool(self, *a, **k):
        def deco(fn):
            self.tools.append(fn.__name__)
            return fn
        return deco


def _install(monkeypatch, module_path: str, cls_name: str):
    for mod in ("mcp", "mcp.server", "mcp.server.mcpserver", "mcp.server.fastmcp"):
        monkeypatch.delitem(sys.modules, mod, raising=False)
    pkg = types.ModuleType("mcp"); server = types.ModuleType("mcp.server"); leaf = types.ModuleType(module_path)
    setattr(leaf, cls_name, _Stub)
    monkeypatch.setitem(sys.modules, "mcp", pkg)
    monkeypatch.setitem(sys.modules, "mcp.server", server)
    monkeypatch.setitem(sys.modules, module_path, leaf)


@pytest.mark.parametrize("module_path,cls_name", [("mcp.server.mcpserver", "MCPServer"), ("mcp.server.fastmcp", "FastMCP")])
def test_builds_on_either_sdk(monkeypatch, tmp_path, module_path, cls_name):
    _install(monkeypatch, module_path, cls_name)
    s = mcp_server.build_server(tmp_path)
    assert s.name == "millimeter-kitchen" and "apply_ops" in s.instructions
    assert {"describe", "search_catalog", "apply_ops", "validate", "export", "purchase"} <= set(s.tools)


def test_missing_sdk_says_how_to_install(monkeypatch, tmp_path):
    for mod in ("mcp", "mcp.server", "mcp.server.mcpserver", "mcp.server.fastmcp"):
        monkeypatch.setitem(sys.modules, mod, None)   # None makes `import` raise ImportError
    with pytest.raises(SystemExit, match="pip install"):
        mcp_server.build_server(tmp_path)
