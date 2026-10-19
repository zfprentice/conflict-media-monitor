"""GDELT 2.0 raw event files -> daily per-country aggregates.

GDELT publishes a zipped, tab-separated event export every 15 minutes (plus a
machine-translated export covering ~65 non-English languages). Unlike the
DOC API these static files are not rate limited, so the pipeline downloads
them directly and aggregates them itself.

Each event row carries: who (actor country codes), where (ActionGeo FIPS
country), what (CAMEO event code), how much coverage (NumArticles), tone
(AvgTone) and one source URL. An event counts toward a tracked country when
it happens there (ActionGeo) or either actor belongs to it.
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://data.gdeltproject.org/gdeltv2/"
STREAMS = ("export", "translation.export")
USER_AGENT = "conflict-media-monitor/2.0"

# Column indexes in the 61-column GDELT 2.0 event export
C_ACTOR1_COUNTRY, C_ACTOR2_COUNTRY = 7, 17
C_EVENT_CODE, C_BASE_CODE, C_ROOT_CODE = 26, 27, 28
C_NUM_ARTICLES, C_TONE = 33, 34
C_ACTION_COUNTRY = 53
C_URL = 60

VIOLENCE_ROOTS = {"18", "19", "20"}  # assault, fight, unconventional mass violence
PEACE_BASES = {"036", "045", "046", "057", "087"}  # intent to negotiate, mediate, negotiate, sign agreement, de-escalate/ceasefire
ROOT_NAMES = {
    "01": "Public statements", "02": "Appeals", "03": "Intent to cooperate", "04": "Consultations",
    "05": "Diplomatic cooperation", "06": "Material cooperation", "07": "Aid", "08": "Concessions",
    "09": "Investigations", "10": "Demands", "11": "Disapproval", "12": "Rejections", "13": "Threats",
    "14": "Protests", "15": "Shows of force", "16": "Reduced relations", "17": "Coercion",
    "18": "Assaults", "19": "Armed clashes", "20": "Mass violence",
}
ROOTS = sorted(ROOT_NAMES)
FIELDS = ["date", "key", "slots", "events", "articles", "tone_w", "viol", "peace"] + [f"r{r}" for r in ROOTS]
ALL = "_ALL"


# ---------------------------------------------------------------- slots
def slot_id(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S")


def slots_between(start: datetime, end: datetime) -> list[str]:
    """15-minute slot ids from start to end inclusive, newest first."""
    t = end.replace(minute=end.minute - end.minute % 15, second=0, microsecond=0)
    out = []
    while t >= start:
        out.append(slot_id(t))
        t -= timedelta(minutes=15)
    return out


def slot_day(slot: str) -> str:
    return f"{slot[0:4]}-{slot[4:6]}-{slot[6:8]}"


# ---------------------------------------------------------------- parsing
def build_index(countries: list[dict]) -> tuple[dict, dict]:
    fips, cameo = defaultdict(set), defaultdict(set)
    for c in countries:
        for f in c.get("fips", []):
            fips[f].add(c["iso3"])
        for k in c.get("cameo", []):
            cameo[k].add(c["iso3"])
    return dict(fips), dict(cameo)


_SLUG_JUNK = re.compile(r"^\d+$|^[a-f0-9]{8,}$|^(index|amp|article|news|story)(\.\w+)?$", re.I)


def title_from_url(url: str) -> str:
    """Best-effort headline from a URL slug ('sudan-rsf-shell-el-fasher-123' -> 'Sudan rsf shell el fasher')."""
    path = urllib.parse.urlparse(url).path
    parts = [p for p in path.split("/") if p and not _SLUG_JUNK.search(p)]
    for seg in reversed(parts):
        seg = re.sub(r"\.\w{2,5}$", "", seg)
        words = [w for w in re.split(r"[-_+]+", seg) if w and not re.fullmatch(r"\d{4,}|[a-z]?\d+[a-z]?|[a-f0-9]{6,}", w, re.I)]
        if len(words) >= 3:
            text = " ".join(words)
            text = urllib.parse.unquote(text)
            return text[:1].upper() + text[1:160]
    return ""


def domain_of(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def parse_export(text: str, slot: str, fips: dict, cameo: dict, agg: dict, articles: dict | None):
    """Add one 15-minute file's events into `agg` ({(date, key): counters}).

    If `articles` is given, also collect per-country candidate stories.
    """
    day = slot_day(slot)
    g = agg[(day, ALL)]
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) < 61:
            continue
        try:
            n = int(f[C_NUM_ARTICLES] or 0)
            tone = float(f[C_TONE] or 0)
        except ValueError:
            continue
        g["events"] += 1
        g["articles"] += n
        hits = set(fips.get(f[C_ACTION_COUNTRY], ()))
        hits |= cameo.get(f[C_ACTOR1_COUNTRY], set())
        hits |= cameo.get(f[C_ACTOR2_COUNTRY], set())
        if not hits:
            continue
        root, base = f[C_ROOT_CODE], f[C_BASE_CODE]
        for iso in hits:
            a = agg[(day, iso)]
            a["events"] += 1
            a["articles"] += n
            a["tone_w"] += tone * n
            if root in VIOLENCE_ROOTS:
                a["viol"] += n
            if base in PEACE_BASES:
                a["peace"] += n
            if root in ROOT_NAMES:
                a["r" + root] += n
            if articles is not None and f[C_URL].startswith("http"):
                articles[iso].append((n, f[C_URL], slot, root))


def unzip_text(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return z.read(z.namelist()[0]).decode("utf-8", errors="replace")


# ---------------------------------------------------------------- download
def fetch(url: str, timeout: int = 60, retries: int = 3) -> bytes | None:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None  # GDELT occasionally skips a slot
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed after {retries} tries: {url}")


def download_slots(slots: list[str], deadline: float, workers: int = 16):
    """Yield (slot, stream, text|None) for each slot and stream, stopping at the deadline.

    A slot is only yielded once both streams were attempted; network failures
    leave it unprocessed so a later run retries it.
    """
    def job(slot):
        out = []
        for stream in STREAMS:
            blob = fetch(f"{BASE}{slot}.{stream}.CSV.zip")
            out.append((stream, unzip_text(blob) if blob else None))
        return slot, out

    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = iter(slots)
        futures = set()
        for _ in range(workers * 2):
            s = next(pending, None)
            if s:
                futures.add(pool.submit(job, s))
        while futures:
            for fut in as_completed(list(futures)):
                futures.discard(fut)
                try:
                    yield fut.result()
                except Exception as exc:
                    print(f"  ! {exc}", flush=True)
                if time.time() < deadline:
                    s = next(pending, None)
                    if s:
                        futures.add(pool.submit(job, s))
                break


# ---------------------------------------------------------------- state files
def load_daily(path: Path) -> dict:
    agg = defaultdict(lambda: defaultdict(float))
    if path.exists():
        with path.open() as f:
            for r in csv.DictReader(f):
                a = agg[(r["date"], r["key"])]
                for k in FIELDS[2:]:
                    a[k] = float(r.get(k) or 0)
    return agg


def save_daily(path: Path, agg: dict, keep_from: str):
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for (d, key) in sorted(agg):
            if d < keep_from:
                continue
            a = agg[(d, key)]
            w.writerow([d, key] + [round(a[k], 2) if k == "tone_w" else int(a[k]) for k in FIELDS[2:]])


def load_slots(path: Path) -> set[str]:
    return set(path.read_text().split()) if path.exists() else set()


def save_slots(path: Path, done: set[str], keep_from: str):
    cutoff = keep_from.replace("-", "")
    path.write_text("\n".join(sorted(s for s in done if s[:8] >= cutoff)) + "\n")


def merge_articles(old: dict, new: dict, now: datetime, keep_hours: int = 72, per_country: int = 80) -> dict:
    """Keep the most-covered distinct stories per country from the last few days."""
    cutoff = slot_id(now - timedelta(hours=keep_hours))
    out = {}
    for iso in set(old) | set(new):
        best: dict[str, dict] = {}
        for a in old.get(iso, []):
            if a["slot"] >= cutoff:
                best[a["url"]] = a
        for n, url, slot, root in new.get(iso, []):
            if slot < cutoff:
                continue
            cur = best.get(url)
            if cur:
                cur["mentions"] = max(cur["mentions"], n)
            else:
                best[url] = {"url": url, "mentions": n, "slot": slot, "root": root}
        ranked = sorted(best.values(), key=lambda a: (-a["mentions"], -int(a["slot"])))
        out[iso] = ranked[:per_country]
    return out
