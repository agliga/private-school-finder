from school_finder.crawl import Page, chunk_text, html_to_text, score_links
from school_finder.extract import RECORD_TOOL, extract_facts, quote_on_page

# A fictional school used only for tests.
PAGES = [
    Page(url="https://example-prep.test/tuition", title="Tuition",
         text="Tuition and Fees\nTuition for 2026-27 is $38,500 for grades 9-12.\n"
              "A $1,000 enrollment deposit is due in March."),
    Page(url="https://example-prep.test/college", title="College Counseling",
         text="Recent graduates enrolled at:\nStanford University\nUC Davis\nSanta Clara University"),
]


class StubLLM:
    """Returns a canned tool call, like the real model would."""

    model = "stub"

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def extract(self, system, user, tool):
        self.calls.append((system, user, tool))
        return self.payload


GOOD = {
    "tuition": {"amount_min": 38500, "amount_max": 38500, "school_year": "2026-27",
                "source_url": "https://example-prep.test/tuition",
                "quote": "Tuition for 2026-27 is $38,500 for grades 9-12."},
    "matriculation": {"colleges": ["Stanford University", "UC Davis", "Santa Clara University"],
                      "kind": "enrolled", "source_url": "https://example-prep.test/college",
                      "quote": "Recent graduates enrolled at:"},
}


def test_extract_verifies_quotes():
    facts, verified = extract_facts(StubLLM(GOOD), "Example Prep", PAGES)
    assert facts.tuition.amount_max == 38500
    assert verified == {"tuition": True, "matriculation": True}


def test_fabricated_quote_is_not_verified():
    bad = {"tuition": {**GOOD["tuition"], "quote": "Tuition is $12,000 per year."}}
    _, verified = extract_facts(StubLLM(bad), "Example Prep", PAGES)
    assert verified == {"tuition": False}


def test_quote_must_be_on_the_cited_page():
    assert not quote_on_page("Stanford University", "https://example-prep.test/tuition", PAGES)
    assert quote_on_page("stanford   university", "https://example-prep.test/college/", PAGES)


def test_tool_schema_is_json_schema():
    schema = RECORD_TOOL["input_schema"]
    assert schema["type"] == "object"
    assert "tuition" in schema["properties"]


def test_prompt_includes_pages():
    llm = StubLLM({})
    extract_facts(llm, "Example Prep", PAGES)
    _, user, _ = llm.calls[0]
    assert "https://example-prep.test/college" in user


def test_html_to_text_and_links():
    html = """<html><head><title>Home</title><script>x()</script></head><body>
      <nav>menu</nav><p>Welcome</p>
      <a href="/admissions/tuition-and-fees">Tuition & Fees</a>
      <a href="/college-counseling/matriculation">Where our grads go</a>
      <a href="https://other.test/tuition">Elsewhere</a>
      <a href="/athletics">Athletics</a></body></html>"""
    title, text = html_to_text(html)
    assert title == "Home" and "Welcome" in text and "x()" not in text and "menu" not in text
    links = score_links("https://example-prep.test/", html)
    assert links[0].endswith("/college-counseling/matriculation")
    assert all("other.test" not in u for u in links)
    assert not any(u.endswith("/athletics") for u in links)


def test_chunking_overlaps_and_bounds():
    text = "\n".join(f"Paragraph {i} " + "x" * 200 for i in range(20))
    chunks = chunk_text(text, max_chars=1000, overlap=100)
    assert len(chunks) > 1
    assert all(len(c) <= 1300 for c in chunks)
