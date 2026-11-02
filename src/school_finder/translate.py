"""Plain English -> structured SchoolQuery, in one Claude call.

"show me all catholic high schools" -> search_schools(religious_groups=["catholic"],
levels=["secondary"]). The SQL that runs is then fully deterministic, cheap and testable;
the evals/translate.jsonl suite measures how often the translation is right.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .query import SchoolQuery
from .tools import TRANSLATE_TOOLS, parse_query

SYSTEM = """You translate a parent's question about private K-12 schools into exactly one tool call.
- Only set filters the user asked for. Don't invent locations, sizes or price limits.
- "in <city>" -> cities. "near <city>" / "within N miles of <city>" -> place (+ radius_miles).
- Catholic -> religious_groups ["catholic"]. "Christian" alone -> religious_groups
  ["catholic","other_religious"] is too broad; use affiliation "Christian" only if they say
  non-denominational Christian, otherwise religious_groups ["other_religious"].
  Specific denominations (Jewish, Lutheran, Baptist, Islamic...) -> affiliation.
- "high school(s)" -> levels ["secondary"]; "elementary"/"middle school" -> ["elementary"];
  "K-12" -> ["combined"]; "schools with a high school" -> ["secondary","combined"].
- Montessori / Waldorf / a word in the school's name -> name_contains.
- "all"/"every" -> limit 500. "cheapest" -> sort tuition_asc. "biggest" -> enrollment_desc.
  "closest" -> sort distance (needs place).
- Counting / breakdown questions -> count_schools with the right group_by.
"""


class ToolLLM(Protocol):
    def choose_tool(self, system: str, user: str, tools: list[dict]) -> tuple[str, dict]: ...


class AnthropicToolLLM:
    def __init__(self, model: str, api_key: str | None = None):
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def choose_tool(self, system: str, user: str, tools: list[dict]) -> tuple[str, dict]:
        msg = self.client.messages.create(
            model=self.model, max_tokens=1000, system=system, tools=tools,
            tool_choice={"type": "any"}, messages=[{"role": "user", "content": user}],
        )
        for block in msg.content:
            if block.type == "tool_use":
                return block.name, dict(block.input)
        raise RuntimeError("model did not call a tool")


@dataclass
class Translation:
    kind: str                     # "search" | "count"
    query: SchoolQuery
    group_by: str | None = None


def translate(llm: ToolLLM, question: str) -> Translation:
    name, args = llm.choose_tool(SYSTEM, question, TRANSLATE_TOOLS)
    query, group_by = parse_query(args)
    return Translation("count" if name == "count_schools" else "search", query, group_by)
