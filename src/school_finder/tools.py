"""Tools shared by the translator, the chat agent and the MCP server."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from .query import GroupBy, SchoolQuery

_QUERY_SCHEMA = SchoolQuery.model_json_schema()

SEARCH_TOOL: dict[str, Any] = {
    "name": "search_schools",
    "description": (
        "List private schools matching filters. Use for 'show me', 'find', 'list', 'which' "
        "questions. Only set filters the user actually asked for. Returns rows with name, city, "
        "religious group/affiliation, NCES type, level, enrollment, tuition_max and "
        "college_outcome_score (null = not published yet), plus the total match count."
    ),
    "input_schema": _QUERY_SCHEMA,
}

COUNT_TOOL: dict[str, Any] = {
    "name": "count_schools",
    "description": (
        "Count schools matching filters, grouped by a field. Use for 'how many', 'breakdown', "
        "'which denominations', 'what cities' questions."
    ),
    "input_schema": {
        **_QUERY_SCHEMA,
        "properties": {
            **_QUERY_SCHEMA["properties"],
            "group_by": {"type": "string", "enum": list(GroupBy.__args__),  # type: ignore[attr-defined]
                         "description": "Field to group counts by."},
        },
        "required": ["group_by"],
    },
}

SEMANTIC_TOOL: dict[str, Any] = {
    "name": "semantic_search",
    "description": (
        "Search crawled school web pages by meaning (e.g. 'strong robotics program', "
        "'small class sizes'). Only enriched schools have pages. Optionally restrict to ppins."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "ppins": {"type": "array", "items": {"type": "string"}},
            "limit": {"type": "integer", "default": 8},
        },
        "required": ["query"],
    },
}

GET_TOOL: dict[str, Any] = {
    "name": "get_school",
    "description": "Full record for one school, with every extracted fact, its source URL and quote.",
    "input_schema": {
        "type": "object",
        "properties": {"ppin": {"type": "string"}},
        "required": ["ppin"],
    },
}

# Translator: one call, question -> structured query
TRANSLATE_TOOLS = [SEARCH_TOOL, COUNT_TOOL]
# Chat agent: can also read pages and drill into schools
TOOL_SPECS = [SEARCH_TOOL, COUNT_TOOL, SEMANTIC_TOOL, GET_TOOL]


def _jsonable(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def parse_query(args: dict[str, Any]) -> tuple[SchoolQuery, str | None]:
    args = dict(args)
    group_by = args.pop("group_by", None)
    return SchoolQuery.model_validate(args), group_by


def run_tool(conn, name: str, args: dict[str, Any]) -> str:
    from . import db

    try:
        if name == "search_schools":
            q, _ = parse_query(args)
            result: Any = db.run_search(conn, q)
            result.pop("center", None)
        elif name == "count_schools":
            q, group_by = parse_query(args)
            result = db.run_stats(conn, q, group_by or "religious_group")
        elif name == "semantic_search":
            from .embed import embed_query

            result = db.semantic_search(conn, embed_query(args["query"]), args.get("ppins"),
                                        args.get("limit", 8))
        elif name == "get_school":
            result = db.get_school(conn, args["ppin"])
        else:
            result = {"error": f"unknown tool {name}"}
    except ValueError as e:  # bad filter values from the model: let it retry
        result = {"error": str(e)}
    return json.dumps(result, default=_jsonable)
