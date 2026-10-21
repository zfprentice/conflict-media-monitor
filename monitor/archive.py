"""Long-lived records that the page and the Excel files are built from.

- Watch-term mentions (e.g. every Google News article mentioning the European
  Institute of Peace), appended to a CSV and never pruned.
- Weekly story snapshots: one small JSON file per ISO week with each country's
  main stories, theme counts and names, frozen once the week is over.

Both are stored as plain files in the repository so history survives
indefinitely and diffs stay small.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from monitor.stories import fold

MENTION_FIELDS = ["published", "found", "title", "outlet", "language", "countries", "link", "term"]


# ---------------------------------------------------------------- mentions
def mention_key(m: dict) -> tuple:
    return (re.sub(r"\W+", "", fold(m["title"]))[:90], fold(m.get("outlet", "")))


def load_mentions(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_mentions(path: Path, rows: list[dict]):
    rows = sorted(rows, key=lambda r: (r["published"] or r["found"], r["title"]), reverse=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MENTION_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def merge_mentions(rows: list[dict], items: list[dict], *, term: str, language: str, found: str,
                   tag_countries) -> int:
    """Add Google News items not already recorded. Returns how many were new."""
    seen = {mention_key(r) for r in rows}
    added = 0
    for it in items:
        m = {
            "published": (it.get("published") or "")[:16].replace("T", " "),
            "found": found,
            "title": it["title"],
            "outlet": it.get("source", ""),
            "language": language,
            "countries": "; ".join(tag_countries(it["title"])),
            "link": it["url"],
            "term": term,
        }
        k = mention_key(m)
        if k in seen:
            continue
        seen.add(k)
        rows.append(m)
        added += 1
    return added


def months_between(start: str, end: date) -> list[tuple[str, str]]:
    """[(first day, first day of next month)] from `start` (YYYY-MM-DD) to the month containing `end`, newest first."""
    y, m = int(start[:4]), int(start[5:7])
    out = []
    while (y, m) <= (end.year, end.month):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        out.append((f"{y:04d}-{m:02d}-01", f"{ny:04d}-{nm:02d}-01"))
        y, m = ny, nm
    return out[::-1]


# ---------------------------------------------------------------- weeks
def week_id(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_bounds(wid: str) -> tuple[date, date]:
    """Monday and Sunday of an ISO week id like '2026-W43'."""
    y, w = int(wid[:4]), int(wid[6:])
    monday = date.fromisocalendar(y, w, 1)
    return monday, monday + timedelta(days=6)


def recent_weeks(today: date, n: int) -> list[str]:
    """The current week and the n-1 before it, newest first."""
    return [week_id(today - timedelta(weeks=i)) for i in range(n)]


def load_week(folder: Path, wid: str) -> dict:
    p = folder / f"{wid}.json"
    if p.exists():
        return json.loads(p.read_text())
    start, end = week_bounds(wid)
    return {"week": wid, "start": start.isoformat(), "end": end.isoformat(), "countries": {}}


def save_week(folder: Path, snap: dict):
    folder.mkdir(parents=True, exist_ok=True)
    cs = snap.get("countries", {})
    snap["final"] = bool(cs) and all(c.get("final") for c in cs.values())
    for c in cs.values():  # keep the archive small: two extra links per story are plenty
        for story in c.get("stories", []):
            story["also"] = story.get("also", [])[:2]
    (folder / f"{snap['week']}.json").write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")


def all_weeks(folder: Path) -> list[str]:
    return sorted((p.stem for p in folder.glob("*-W*.json")), reverse=True) if folder.exists() else []


def in_week(published: str | None, start: date, end: date) -> bool:
    if not published:
        return False
    try:
        d = datetime.fromisoformat(published).date()
    except ValueError:
        return False
    return start <= d <= end
