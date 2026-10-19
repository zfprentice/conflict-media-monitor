"""GDELT DOC 2.0 API client.

GDELT asks for at most one request every five seconds, so every call goes
through `Client.get`, which spaces requests and retries when GDELT answers
with its plain-text rate-limit message instead of JSON.

Parsing is kept in pure functions (`parse_*`) so the tests can run them
against saved fixtures without touching the network.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone

BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
USER_AGENT = "conflict-media-monitor/1.0 (+https://github.com)"


def build_url(query: str, mode: str, timespan: str = "3months", **extra) -> str:
    params = {"query": query, "mode": mode, "format": "json", "timespan": timespan}
    params.update({k: v for k, v in extra.items() if v is not None})
    return BASE + "?" + urllib.parse.urlencode(params)


class Client:
    """Rate-limited GDELT client with a circuit breaker.

    GDELT answers slowly (often 10-40 s) and intermittently from cloud IPs, so
    each call has a short timeout, at most one retry, and after several
    consecutive failures the client declares GDELT down for the rest of the run.
    """

    def __init__(self, min_interval: float = 5.5, retries: int = 2, timeout: int = 40, trip_after: int = 5):
        self.min_interval = min_interval
        self.retries = retries
        self.timeout = timeout
        self.trip_after = trip_after
        self._last = 0.0
        self._streak = 0
        self.down = False
        self.calls = 0
        self.failures = 0
        self.log: list[dict] = []

    def _wait(self):
        gap = time.monotonic() - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last = time.monotonic()

    def _record(self, mode: str, t0: float, outcome: str):
        self.log.append({"mode": mode, "s": round(time.monotonic() - t0, 1), "outcome": outcome})

    def get(self, url: str) -> dict | None:
        if self.down:
            return None
        mode = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("mode", ["?"])[0]
        for attempt in range(self.retries):
            self._wait()
            self.calls += 1
            t0 = time.monotonic()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    body = r.read().decode("utf-8", errors="replace")
            except Exception as exc:  # timeout, 429, 5xx, connection reset
                self._record(mode, t0, f"error: {type(exc).__name__}: {str(exc)[:80]}")
                print(f"  ! {mode} failed ({type(exc).__name__}: {str(exc)[:80]})", flush=True)
                time.sleep(8)
                continue
            body = body.strip()
            if not body:
                self._record(mode, t0, "empty")
                self._streak = 0
                return {}  # GDELT returns an empty body when nothing matches
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                # Rate-limit or query-syntax message in plain text
                self._record(mode, t0, "text: " + body[:80])
                print(f"  ! {mode} non-JSON reply: {body[:100]!r}", flush=True)
                if "limit" in body.lower() or "please" in body.lower():
                    time.sleep(12)
                    continue
                break
            self._record(mode, t0, "ok")
            self._streak = 0
            return data
        self.failures += 1
        self._streak += 1
        if self._streak >= self.trip_after:
            self.down = True
            print(f"  !! {self._streak} consecutive GDELT failures; skipping GDELT for the rest of this run", flush=True)
        return None


def _day(stamp: str) -> str:
    """'20261018T121500Z' -> '2026-10-18'"""
    return f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}"


def parse_timeline_volraw(payload: dict | None) -> dict[str, dict]:
    """Aggregate a timelinevolraw response to UTC days.

    Returns {day: {"count": articles matching, "norm": all articles monitored}}.
    """
    out: dict[str, dict] = defaultdict(lambda: {"count": 0, "norm": 0})
    if not payload:
        return {}
    for series in payload.get("timeline", []):
        for pt in series.get("data", []):
            d = _day(pt["date"])
            out[d]["count"] += int(pt.get("value", 0) or 0)
            out[d]["norm"] += int(pt.get("norm", 0) or 0)
    return dict(sorted(out.items()))


def parse_timeline_tone(payload: dict | None) -> dict[str, float]:
    """Average tone per UTC day (mean of the sub-day points GDELT returns)."""
    acc: dict[str, list[float]] = defaultdict(list)
    if not payload:
        return {}
    for series in payload.get("timeline", []):
        for pt in series.get("data", []):
            v = pt.get("value")
            if v is not None:
                acc[_day(pt["date"])].append(float(v))
    return {d: round(sum(v) / len(v), 3) for d, v in sorted(acc.items()) if v}


def parse_artlist(payload: dict | None, limit: int = 40) -> dict:
    """Clean article list plus outlet and source-country breakdowns."""
    if not payload:
        return {"articles": [], "top_domains": [], "source_countries": [], "languages": []}
    arts = payload.get("articles", []) or []
    seen, clean = set(), []
    for a in arts:
        title = (a.get("title") or "").strip()
        url = a.get("url")
        key = title.lower()[:90]
        if not url or not title or key in seen:
            continue
        seen.add(key)
        seen_at = a.get("seendate", "")
        try:
            iso = datetime.strptime(seen_at, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            iso = None
        clean.append({
            "title": title,
            "url": url,
            "domain": a.get("domain", ""),
            "country": a.get("sourcecountry", ""),
            "language": a.get("language", ""),
            "seen": iso,
            "image": a.get("socialimage") or None,
        })
    domains = Counter(a.get("domain", "") for a in arts if a.get("domain"))
    countries = Counter(a.get("sourcecountry", "") for a in arts if a.get("sourcecountry"))
    langs = Counter(a.get("language", "") for a in arts if a.get("language"))
    return {
        "articles": clean[:limit],
        "top_domains": domains.most_common(8),
        "source_countries": countries.most_common(8),
        "languages": langs.most_common(6),
    }
