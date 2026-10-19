"""Google News RSS headlines — mainstream outlets to complement GDELT's long tail."""
from __future__ import annotations

import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

USER_AGENT = "Mozilla/5.0 (compatible; conflict-media-monitor/1.0)"


def build_url(query: str, window: str = "2d") -> str:
    q = f"{query} when:{window}"
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": "en-GB", "gl": "GB", "ceid": "GB:en"}
    )


def parse_rss(xml_text: str, limit: int = 15) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        # Google appends " - Publisher" to the title; strip it when we have the source.
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3]
        pub = it.findtext("pubDate")
        try:
            published = parsedate_to_datetime(pub).isoformat() if pub else None
        except (TypeError, ValueError):
            published = None
        link = it.findtext("link")
        if title and link:
            items.append({"title": title, "url": link, "source": source, "published": published})
    items.sort(key=lambda x: x["published"] or "", reverse=True)
    return items[:limit]


def fetch(query: str, retries: int = 3) -> list[dict] | None:
    url = build_url(query)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as r:
                return parse_rss(r.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            print(f"  ! Google News failed ({exc}); retry {attempt + 1}/{retries}")
            time.sleep(5 * (attempt + 1))
    return None
