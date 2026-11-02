"""Polite crawler for a school's own website.

Fetches the home page, picks the pages most likely to hold tuition, admissions and
college-outcome info, and returns clean text. Respects robots.txt and only follows
links on the school's own domain.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from .config import settings

LINK_KEYWORDS = {
    "tuition": 5, "affordability": 4, "financial aid": 3, "fees": 3, "cost": 2,
    "admission": 2, "college counseling": 5, "matriculation": 6, "college acceptances": 6,
    "college list": 5, "school profile": 5, "profile": 2, "college": 2, "outcomes": 4,
    "mission": 1, "faith": 1, "about": 1,
    "calendar": 5, "bell schedule": 6, "daily schedule": 5, "school hours": 5, "schedule": 2,
    "hours": 1,
}


@dataclass
class Page:
    url: str
    title: str
    text: str


def html_to_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "form"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title else ""
    text = soup.get_text("\n")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return title, text.strip()


def pdf_to_text(data: bytes, max_pages: int = 10) -> str:
    """Text of a PDF (school calendars are often PDFs). Empty string if unreadable."""
    import io

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((pg.extract_text() or "") for pg in reader.pages[:max_pages])
    except Exception:
        return ""
    return re.sub(r"[ \t]+", " ", text).strip()


def score_links(base_url: str, html: str, limit: int = 6) -> list[str]:
    """Rank same-domain links by how likely they are to hold the facts we need."""
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(base_url).netloc.removeprefix("www.")
    scored: dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"}:
            continue
        is_pdf = parsed.path.lower().endswith(".pdf")
        if parsed.netloc.removeprefix("www.") != host and not is_pdf:
            continue  # PDFs (calendars) are often hosted on a CDN, so allow those
        label = f"{a.get_text(' ', strip=True)} {parsed.path.replace('-', ' ')}".lower()
        score = sum(w for kw, w in LINK_KEYWORDS.items() if kw in label)
        if score:
            scored[href] = max(score, scored.get(href, 0))
    return [u for u, _ in sorted(scored.items(), key=lambda kv: -kv[1])[:limit]]


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 1 > max_chars and buf:
            chunks.append(buf)
            buf = buf[-overlap:]
        buf = f"{buf}\n{p}" if buf else p
    if buf:
        chunks.append(buf)
    return chunks


class Crawler:
    def __init__(self, delay_s: float = 1.0, timeout_s: float = 15.0):
        import httpx

        self._httpx = httpx
        self.client = httpx.Client(
            headers={"User-Agent": settings.user_agent},
            timeout=timeout_s,
            follow_redirects=True,
        )
        self.delay_s = delay_s
        self._robots: dict[str, RobotFileParser] = {}

    def allowed(self, url: str) -> bool:
        root = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        if root not in self._robots:
            rp = RobotFileParser()
            try:
                resp = self.client.get(f"{root}/robots.txt")
                rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            except self._httpx.HTTPError:
                rp.parse([])
            self._robots[root] = rp
        return self._robots[root].can_fetch(settings.user_agent, url)

    def fetch(self, url: str) -> Page | None:
        if not self.allowed(url):
            return None
        try:
            resp = self.client.get(url)
        except self._httpx.HTTPError:
            return None
        time.sleep(self.delay_s)
        ctype = resp.headers.get("content-type", "")
        if resp.status_code != 200:
            return None
        if "pdf" in ctype or str(resp.url).lower().endswith(".pdf"):
            text = pdf_to_text(resp.content)
            page = Page(url=str(resp.url), title=str(resp.url).rsplit("/", 1)[-1], text=text)
            page._html = ""  # type: ignore[attr-defined]
            return page if text else None
        if "html" not in ctype:
            return None
        title, text = html_to_text(resp.text)
        page = Page(url=str(resp.url), title=title, text=text)
        page._html = resp.text  # type: ignore[attr-defined]
        return page

    def crawl_school(self, home_url: str, max_pages: int = 6) -> list[Page]:
        home = self.fetch(home_url)
        if not home:
            return []
        pages = [home]
        for link in score_links(home.url, home._html, limit=max_pages):  # type: ignore[attr-defined]
            if len(pages) > max_pages:
                break
            page = self.fetch(link)
            if page and page.text:
                pages.append(page)
        return pages
