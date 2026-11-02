"""MCP server exposing the school tools to any MCP client (Claude Code, Cursor, Claude Desktop).

Run: school-finder mcp   (stdio transport)
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import db
from .tools import run_tool

mcp = FastMCP("school-finder")


@mcp.tool()
def search_schools(place: str = "", lat: float | None = None, lon: float | None = None,
                   radius_miles: float = 15, religious_group: str | None = None,
                   affiliation: str | None = None, level: str | None = None,
                   max_tuition: float | None = None, min_outcome_score: float | None = None,
                   limit: int = 25) -> str:
    """Find private schools near a place with filters (religion, level, tuition, outcomes)."""
    args = {k: v for k, v in locals().items() if v not in (None, "")}
    with db.connect() as conn:
        return run_tool(conn, "search_schools", args)


@mcp.tool()
def semantic_search(query: str, ppins: list[str] | None = None, limit: int = 8) -> str:
    """Search crawled school pages by meaning, e.g. 'strong robotics program'."""
    with db.connect() as conn:
        return run_tool(conn, "semantic_search", {"query": query, "ppins": ppins, "limit": limit})


@mcp.tool()
def get_school(ppin: str) -> str:
    """Full record for one school with every fact's source URL and quote."""
    with db.connect() as conn:
        return run_tool(conn, "get_school", {"ppin": ppin})


def main() -> None:
    mcp.run()
