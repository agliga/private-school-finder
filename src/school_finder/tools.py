"""Tools shared by the query agent and the MCP server."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

# Rough centers for common queries; the agent can also pass lat/lon directly.
PLACES = {
    "san jose": (37.3382, -121.8863),
    "palo alto": (37.4419, -122.1430),
    "san francisco": (37.7749, -122.4194),
    "oakland": (37.8044, -122.2712),
    "cupertino": (37.3230, -122.0322),
    "santa clara": (37.3541, -121.9552),
    "sunnyvale": (37.3688, -122.0363),
    "mountain view": (37.3861, -122.0839),
}

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "search_schools",
        "description": (
            "Find private schools near a place with structured filters. Returns name, distance, "
            "religious group/affiliation, level, tuition_max (null = not published) and "
            "college_outcome_score (0-1 share of listed colleges that are selective; null = not published)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "place": {"type": "string", "description": "City name, e.g. 'San Jose'"},
                "lat": {"type": "number"},
                "lon": {"type": "number"},
                "radius_miles": {"type": "number", "default": 15},
                "religious_group": {"type": "string",
                                    "enum": ["catholic", "other_religious", "nonsectarian"]},
                "affiliation": {"type": "string", "description": "e.g. 'Jewish', 'Lutheran'"},
                "level": {"type": "string", "enum": ["elementary", "secondary", "combined"]},
                "max_tuition": {"type": "number"},
                "min_outcome_score": {"type": "number"},
                "limit": {"type": "integer", "default": 25},
            },
        },
    },
    {
        "name": "semantic_search",
        "description": (
            "Search crawled school web pages by meaning (e.g. 'strong robotics program', "
            "'small class sizes'). Optionally restrict to school ids from search_schools."
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
    },
    {
        "name": "get_school",
        "description": "Full record for one school, with every extracted fact, its source URL and quote.",
        "input_schema": {
            "type": "object",
            "properties": {"ppin": {"type": "string"}},
            "required": ["ppin"],
        },
    },
]


def _jsonable(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def run_tool(conn, name: str, args: dict[str, Any]) -> str:
    from . import db

    if name == "search_schools":
        args = dict(args)
        place = (args.pop("place", "") or "").lower().strip()
        if "lat" not in args or "lon" not in args:
            if place not in PLACES:
                return json.dumps({"error": f"Unknown place '{place}'. Pass lat/lon instead."})
            args["lat"], args["lon"] = PLACES[place]
        result: Any = db.search_schools(conn, **args)
    elif name == "semantic_search":
        from .embed import embed_query

        result = db.semantic_search(conn, embed_query(args["query"]), args.get("ppins"),
                                    args.get("limit", 8))
    elif name == "get_school":
        result = db.get_school(conn, args["ppin"])
    else:
        result = {"error": f"unknown tool {name}"}
    return json.dumps(result, default=_jsonable)
