"""Natural-language query agent: Claude tool use over the school database."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .config import settings
from .tools import TOOL_SPECS, run_tool

SYSTEM = """You help parents find private schools. Use the tools; never answer from memory.
- Plan: search_schools with structured filters first, semantic_search for fuzzy wishes,
  get_school for details on the shortlist.
- When tuition or college outcomes are null, say "not published" — never estimate.
- Cite the source URL for every tuition figure or college outcome you mention.
- End with a JSON block: {"ppins": [...]} listing the schools you recommend, in order.
"""


@dataclass
class AgentResult:
    answer: str
    ppins: list[str]
    tool_calls: list[dict] = field(default_factory=list)


def ask(conn, question: str, max_turns: int = 8, client=None) -> AgentResult:
    import anthropic

    client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)
    messages: list[dict] = [{"role": "user", "content": question}]
    calls: list[dict] = []
    for _ in range(max_turns):
        msg = client.messages.create(model=settings.agent_model, max_tokens=4000, system=SYSTEM,
                                     tools=TOOL_SPECS, messages=messages)
        messages.append({"role": "assistant", "content": msg.content})
        if msg.stop_reason != "tool_use":
            text = "".join(b.text for b in msg.content if b.type == "text")
            return AgentResult(text, parse_ppins(text), calls)
        results = []
        for block in msg.content:
            if block.type == "tool_use":
                calls.append({"name": block.name, "input": block.input})
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": run_tool(conn, block.name, block.input)})
        messages.append({"role": "user", "content": results})
    return AgentResult("Stopped: too many tool calls.", [], calls)


def parse_ppins(text: str) -> list[str]:
    start = text.rfind('{"ppins"')
    if start == -1:
        return []
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return [str(p) for p in obj.get("ppins", [])]
    except json.JSONDecodeError:
        return []
