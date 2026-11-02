"""LLM extraction of tuition, affiliation and college outcomes, with provenance checks.

The model must return a verbatim quote for every value. We then verify the quote
really appears on the fetched page; unverified facts are stored but never used in
search results.
"""

from __future__ import annotations

import re
from typing import Protocol

from .crawl import Page
from .models import SchoolFacts

SYSTEM = """You extract facts about one private K-12 school from pages of its own website.
Rules:
- Only report what the pages state. If a fact is not published, leave it null. Never guess.
- For every value, copy a short verbatim quote (under 300 characters) from the page that
  supports it, and give that page's URL as source_url.
- Tuition: annual tuition in USD. If there are several grade bands, report min and max.
  Ignore one-time fees, deposits and financial-aid amounts.
- Matriculation: list college names from a published college list (enrolled or admitted).
  Say which kind it is.
"""

RECORD_TOOL = {
    "name": "record_school_facts",
    "description": "Record the facts found for this school. Use null for anything not published.",
    "input_schema": SchoolFacts.model_json_schema(),
}


class LLM(Protocol):
    def extract(self, system: str, user: str, tool: dict) -> dict: ...


class AnthropicLLM:
    def __init__(self, model: str, api_key: str | None = None):
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def extract(self, system: str, user: str, tool: dict) -> dict:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": user}],
        )
        for block in msg.content:
            if block.type == "tool_use":
                return block.input
        return {}


def build_prompt(school_name: str, pages: list[Page], max_chars_per_page: int = 12000) -> str:
    parts = [f"School: {school_name}\n"]
    for p in pages:
        parts.append(f"<page url=\"{p.url}\" title=\"{p.title}\">\n{p.text[:max_chars_per_page]}\n</page>")
    return "\n".join(parts)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_on_page(quote: str, source_url: str, pages: list[Page]) -> bool:
    """True when the quote appears (whitespace-insensitive) on the cited page."""
    q = _norm(quote)
    if len(q) < 4:
        return False
    for p in pages:
        if p.url.rstrip("/") == source_url.rstrip("/") and q in _norm(p.text):
            return True
    return False


def extract_facts(llm: LLM, school_name: str, pages: list[Page]) -> tuple[SchoolFacts, dict[str, bool]]:
    raw = llm.extract(SYSTEM, build_prompt(school_name, pages), RECORD_TOOL)
    facts = SchoolFacts.model_validate(raw)
    verified = {}
    for field in ("tuition", "matriculation", "affiliation"):
        cited = getattr(facts, field)
        if cited is not None:
            verified[field] = quote_on_page(cited.quote, cited.source_url, pages)
    return facts, verified
