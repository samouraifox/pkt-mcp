"""pkt-mcp FastMCP server.

Step 1 scaffolding: confirms the MCP plumbing is wired up. Real Bridge tools
land in Step 3 — for now there's a single ping_self() that returns "ok" so
we can validate the server with the mcp inspector before adding surface area.

Run:
    uv run python -m pkt_mcp.server          # stdio, what Claude Code launches
    uv run mcp dev pkt_mcp/server.py         # interactive inspector
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("pkt-mcp")


@mcp.tool()
def ping_self() -> str:
    """Health check. Returns the literal string "ok" if the MCP server is
    alive and the tool dispatcher is working. Use this to verify the
    pkt-mcp server is reachable before attempting real PT operations."""
    return "ok"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
