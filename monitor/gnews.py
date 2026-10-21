"""Google News RSS headlines — mainstream outlets to complement GDELT's long tail."""
from __future__ import annotations

import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

USER_AGENT = "Mozilla/5.0 (compatible; conflict-media-monitor/1.0)"


def build_url(query: str, window: str = "2d", edition: str = "GB:en", after: str | None = None, before: str | None = None) -> str:
    """Google News RSS search. `edition` is 'COUNTRY:lang' (e.g. 'FR:fr'); `after`/`before`
    (YYYY-MM-DD) ask for a date range instead of the trailing `window`."""
    q = f"{query} after:{after} before:{before}" if after and before else f"{query} when:{window}"
    gl, lang = edition.split(":")
    hl = f"{lang}-{gl}" if lang == "en" else lang
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": hl, "gl": gl, "ceid": edition})


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


def fetch(query: str, retries: int = 3, window: str = "2d", limit: int = 100, deadline: float | None = None,
          edition: str = "GB:en", after: str | None = None, before: str | None = None) -> list[dict] | None:
    """Headlines for `query`, or None on failure or once `deadline` (epoch seconds) has passed."""
    url = build_url(query, window, edition, after, before)
    for attempt in range(retries):
        left = deadline - time.time() if deadline else 30
        if left <= 1:
            return None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=min(30, left)) as r:
                return parse_rss(r.read().decode("utf-8", errors="replace"), limit)
        except Exception as exc:
            print(f"  ! Google News failed ({exc}); retry {attempt + 1}/{retries}")
            time.sleep(min(5 * (attempt + 1), max(0, (deadline - time.time()) if deadline else 15)))
    return None
