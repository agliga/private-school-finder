"""MCP server exposing the school tools to any MCP client (Claude Code, Cursor, Claude Desktop).

Run: school-finder mcp   (stdio transport)
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import db
from .query import GroupBy, SchoolQuery
from .tools import run_tool

mcp = FastMCP("school-finder")


@mcp.tool()
def search_schools(filters: SchoolQuery) -> str:
    """List private schools matching filters (religion, denomination, level, city, distance,
    size, tuition, college outcomes). Only set the filters the user asked for."""
    with db.connect() as conn:
        return run_tool(conn, "search_schools", filters.model_dump(exclude_none=True))


@mcp.tool()
def count_schools(group_by: GroupBy, filters: SchoolQuery | None = None) -> str:
    """Count schools matching filters, grouped by religious_group, affiliation, city, level or
    typology."""
    args = (filters or SchoolQuery()).model_dump(exclude_none=True)
    with db.connect() as conn:
        return run_tool(conn, "count_schools", {**args, "group_by": group_by})


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
