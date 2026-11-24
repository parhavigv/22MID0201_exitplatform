"""Master tool registry — one place that knows every tool by name.

`graph.py` uses TOOLS_BY_NAME to look up a tool function when executing a
tool call, and TOOL_DEFS_BY_NAME to build the tool-definition list to send
with a model call. Workers declare which names they're allowed to use (in
workers.py); tool_node refuses calls whose name isn't in the active worker's
tuple, so this registry is also the exhaustive allow-list of what the model
can ever call.
"""

from __future__ import annotations

from typing import Any

from app.agent.tools import drafts, reads, writes
from app.agent.tools.base import ToolContext, ToolSpec

# All ToolSpec objects from every module, keyed by name
_ALL_SPECS: list[ToolSpec] = [
    *reads.TOOLS,
    *drafts.TOOLS,
    *writes.TOOLS,
]

TOOLS_BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in _ALL_SPECS}

TOOL_DEFS_BY_NAME: dict[str, dict[str, Any]] = {
    name: spec.as_tool_def() for name, spec in TOOLS_BY_NAME.items()
}


def call_tool(name: str, inputs: dict[str, Any], ctx: ToolContext) -> str:
    """Execute a named tool with the given inputs and context.

    Returns a plain-text string — either the tool's result or an error
    message the model can relay. Callers (tool_node in graph.py) are
    responsible for checking that `name` is in the active worker's allowed
    tool set before calling this.
    """
    spec = TOOLS_BY_NAME.get(name)
    if spec is None:
        return f"Unknown tool {name!r} — this is a bug in the router, not a valid tool call."
    try:
        return spec.fn(ctx, **inputs)
    except Exception as exc:
        return f"Tool {name!r} raised an unexpected error: {exc}"


__all__ = [
    "TOOLS_BY_NAME",
    "TOOL_DEFS_BY_NAME",
    "ToolContext",
    "call_tool",
]
