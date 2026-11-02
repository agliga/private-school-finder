"""Conversational agent: Claude tool use over the school database, with follow-ups."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .config import settings
from .tools import TOOL_SPECS, run_tool
from .translate import SYSTEM as FILTER_RULES

SYSTEM = f"""You help parents find private K-12 schools. Use the tools; never answer from memory.
- search_schools / count_schools for structured questions, semantic_search for fuzzy wishes
  (only enriched schools have pages), get_school for details on a shortlist.
- Follow-ups refine the previous search: keep earlier filters unless the user changes them.
- When tuition or college outcomes are null, say "not published", never estimate.
- Cite the source URL for every tuition figure or college outcome you mention.
- Keep answers short: lead with how many schools matched, then a compact list.
- End with a JSON block: {{"ppins": [...]}} listing the schools you show, in order.

Filter rules:
{FILTER_RULES}"""

MAX_ROWS_TO_MODEL = 60


@dataclass
class AgentResult:
    answer: str
    ppins: list[str]
    tool_calls: list[dict] = field(default_factory=list)


def _trim(result_json: str) -> str:
    """Keep tool results small: long lists are cut to MAX_ROWS_TO_MODEL with a note."""
    data = json.loads(result_json)
    if isinstance(data, dict) and isinstance(data.get("rows"), list) \
            and len(data["rows"]) > MAX_ROWS_TO_MODEL:
        data["note"] = f"showing first {MAX_ROWS_TO_MODEL} of {data.get('total')} rows"
        data["rows"] = data["rows"][:MAX_ROWS_TO_MODEL]
        return json.dumps(data)
    return result_json


class Conversation:
    """Multi-turn chat; `ask` keeps history so follow-ups ('only the cheaper ones') work."""

    def __init__(self, conn, client=None, max_turns: int = 8):
        import anthropic

        self.conn = conn
        self.client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.max_turns = max_turns
        self.messages: list[dict] = []

    def ask(self, question: str) -> AgentResult:
        self.messages.append({"role": "user", "content": question})
        calls: list[dict] = []
        for _ in range(self.max_turns):
            msg = self.client.messages.create(model=settings.agent_model, max_tokens=4000,
                                              system=SYSTEM, tools=TOOL_SPECS,
                                              messages=self.messages)
            self.messages.append({"role": "assistant", "content": msg.content})
            if msg.stop_reason != "tool_use":
                text = "".join(b.text for b in msg.content if b.type == "text")
                return AgentResult(text, parse_ppins(text), calls)
            results = []
            for block in msg.content:
                if block.type == "tool_use":
                    calls.append({"name": block.name, "input": block.input})
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": _trim(run_tool(self.conn, block.name, block.input))})
            self.messages.append({"role": "user", "content": results})
        return AgentResult("Stopped: too many tool calls.", [], calls)


def ask(conn, question: str, max_turns: int = 8, client=None) -> AgentResult:
    return Conversation(conn, client, max_turns).ask(question)


def parse_ppins(text: str) -> list[str]:
    start = text.rfind('{"ppins"')
    if start == -1:
        return []
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return [str(p) for p in obj.get("ppins", [])]
    except json.JSONDecodeError:
        return []


def strip_ppins_block(text: str) -> str:
    start = text.rfind('{"ppins"')
    return text[:start].rstrip().removesuffix("```json").removesuffix("```").rstrip() \
        if start != -1 else text
