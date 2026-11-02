"""Enrichment pipeline: find site -> crawl -> extract with citations -> verify -> store -> embed."""

from __future__ import annotations

import logging

from . import db
from .config import settings
from .crawl import Crawler, chunk_text
from .extract import AnthropicLLM, extract_facts
from .normalize import normalize_date, normalize_time
from .scoring import college_outcome_score

log = logging.getLogger(__name__)

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 2}


def find_website(school: dict) -> str | None:
    """Ask Claude (with web search) for the school's official homepage."""
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    prompt = (
        f"Find the official website homepage of this private school: {school['name']}, "
        f"{school.get('address') or ''} {school.get('city') or ''}, {school.get('state') or ''}. "
        "Reply with only the URL, or NONE if you cannot find the school's own site. "
        "Do not return directory sites (Niche, GreatSchools, Private School Review, etc.)."
    )
    msg = client.messages.create(
        model=settings.extract_model,
        max_tokens=1000,
        tools=[WEB_SEARCH_TOOL],
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    url = text.split()[-1] if text else ""
    return url if url.startswith("http") else None


def enrich_school(conn, school: dict, crawler: Crawler, llm: AnthropicLLM,
                  embed_pages: bool = True) -> dict:
    ppin = school["ppin"]
    website = school.get("website") or find_website(school)
    if not website:
        return {"ppin": ppin, "status": "no_website"}
    db.set_website(conn, ppin, website)

    pages = crawler.crawl_school(website)
    if not pages:
        return {"ppin": ppin, "status": "crawl_failed", "website": website}

    facts, verified = extract_facts(llm, school["name"], pages)
    if facts.tuition:
        t = facts.tuition
        for field, amount in (("tuition_min", t.amount_min), ("tuition_max", t.amount_max)):
            if amount is not None:
                db.add_fact(conn, ppin, field, {"amount": amount, "school_year": t.school_year,
                                                "grade_note": t.grade_note},
                            t.source_url, t.quote, verified["tuition"], llm.model)
    if facts.matriculation:
        m = facts.matriculation
        db.add_fact(conn, ppin, "matriculation", m.model_dump(exclude={"source_url", "quote"}),
                    m.source_url, m.quote, verified["matriculation"], llm.model)
        score = college_outcome_score(m.colleges)
        if score is not None:
            db.add_fact(conn, ppin, "college_outcome_score",
                        {"score": score, "n_colleges": len(m.colleges), "kind": m.kind},
                        m.source_url, m.quote, verified["matriculation"], "scoring.v1")
    if facts.affiliation and facts.affiliation_name:
        db.add_fact(conn, ppin, "affiliation", {"name": facts.affiliation_name},
                    facts.affiliation.source_url, facts.affiliation.quote,
                    verified["affiliation"], llm.model)

    if facts.schedule:
        sch = facts.schedule
        for field, value in (("start_time", sch.start_time), ("end_time", sch.end_time)):
            t = normalize_time(value)
            if t:
                db.add_fact(conn, ppin, field, {"time": t, "applies_to": sch.applies_to},
                            sch.source_url, sch.quote, verified["schedule"], llm.model)
    if facts.calendar:
        cal = facts.calendar
        for field, value in (("first_day", cal.first_day), ("last_day", cal.last_day)):
            d = normalize_date(value)
            if d:
                db.add_fact(conn, ppin, field, {"date": d, "school_year": cal.school_year},
                            cal.source_url, cal.quote, verified["calendar"], llm.model)

    if embed_pages:
        from .embed import embed

        for page in pages:
            chunks = chunk_text(page.text)
            if chunks:
                db.replace_chunks(conn, ppin, page.url, chunks, embed(chunks))
    conn.commit()
    return {"ppin": ppin, "status": "ok", "website": website, "pages": len(pages),
            "verified": verified}
