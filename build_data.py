"""Build the dashboard data from GDELT raw event files and Google News.

Each run:
  1. downloads any 15-minute GDELT event files (English + translated streams)
     from the last 92 days it hasn't processed yet, newest first, within a
     time budget, and adds them to data/daily.csv;
  2. recomputes every country's metrics from daily.csv;
  3. refreshes Google News headlines for every country and watch term;
  4. writes data/latest.json for the page.

The first run backfills as much history as the budget allows; later runs pick
up the rest, then only the few dozen new files since the last run.

Run locally:  python build_data.py              (BUDGET_MIN=10 for a shorter run)
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from monitor import events, gnews
from monitor.metrics import flags, merge_daily, summarise

ROOT = Path(__file__).parent
CONFIG = ROOT / "config" / "countries.json"
DATA = ROOT / "data"
OUT = DATA / "latest.json"
DAILY = DATA / "daily.csv"
SLOTS = DATA / "slots_done.txt"
ARTICLES = DATA / "recent_articles.json"

WINDOW_DAYS = 92
LAG_MINUTES = 20  # GDELT posts each file a few minutes after the slot


def country_rows(agg: dict, iso: str, days: list[str]) -> list[dict]:
    vol, tone, viol, peace = {}, {}, {}, {}
    for d in days:
        g, a = agg.get((d, events.ALL)), agg.get((d, iso))
        if not g or not g["articles"] or g["slots"] < 8:  # skip days with under 2 hours ingested
            continue
        n = a["articles"] if a else 0
        vol[d] = {"count": int(n), "norm": int(g["articles"])}
        if a and n:
            tone[d] = round(a["tone_w"] / n, 3)
        viol[d] = {"count": int(a["viol"]) if a else 0}
        peace[d] = {"count": int(a["peace"]) if a else 0}
    return merge_daily(vol, tone, viol, peace)


def event_mix(agg: dict, iso: str, days: list[str]) -> list:
    tot = Counter()
    for d in days:
        a = agg.get((d, iso))
        if a:
            for r in events.ROOTS:
                tot[r] += a["r" + r]
    return [(events.ROOT_NAMES[r], int(v)) for r, v in tot.most_common(8) if v]


def story_list(items: list[dict], limit: int = 40) -> list[dict]:
    out = []
    for a in items[:limit]:
        s = a["slot"]
        out.append({
            "title": events.title_from_url(a["url"]) or events.domain_of(a["url"]),
            "url": a["url"],
            "domain": events.domain_of(a["url"]),
            "mentions": a["mentions"],
            "kind": events.ROOT_NAMES.get(a["root"], ""),
            "seen": f"{s[0:4]}-{s[4:6]}-{s[6:8]}T{s[8:10]}:{s[10:12]}:00+00:00",
        })
    return out


def main() -> int:
    cfg = json.loads(CONFIG.read_text())
    budget = float(os.environ.get("BUDGET_MIN", "30")) * 60
    started = time.time()
    deadline = started + budget
    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(days=WINDOW_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    keep_from = window_start.strftime("%Y-%m-%d")
    DATA.mkdir(exist_ok=True)

    # ---- 1. ingest new GDELT files
    agg = events.load_daily(DAILY)
    done = events.load_slots(SLOTS)
    todo = [s for s in events.slots_between(window_start, now - timedelta(minutes=LAG_MINUTES)) if s not in done]
    recent_cut = events.slot_id(now - timedelta(hours=72))
    fips, cameo = events.build_index(cfg["countries"])
    new_articles = defaultdict(list)
    processed = missing = 0
    print(f"{len(todo)} slots to ingest ({len(done)} already done)", flush=True)
    for slot, streams in events.download_slots(todo, deadline - 120):
        for stream, text in streams:
            if text is None:
                missing += 1
                continue
            events.parse_export(text, slot, fips, cameo, agg, new_articles if slot >= recent_cut else None)
        agg[(events.slot_day(slot), events.ALL)]["slots"] += 1
        done.add(slot)
        processed += 1
        if processed % 500 == 0:
            print(f"  {processed} slots ({(time.time() - started) / 60:.1f} min)", flush=True)
    events.save_daily(DAILY, agg, keep_from)
    events.save_slots(SLOTS, done, keep_from)
    old_articles = json.loads(ARTICLES.read_text()) if ARTICLES.exists() else {}
    stories = events.merge_articles(old_articles, new_articles, now)
    ARTICLES.write_text(json.dumps(stories, separators=(",", ":")))
    remaining = len(todo) - processed
    print(f"Ingested {processed} slots ({missing} files missing upstream); {remaining} left for later runs", flush=True)

    # ---- 2. metrics per country
    days = sorted({d for (d, k) in agg if k == events.ALL and d >= keep_from})
    last7 = days[-7:]
    countries = []
    for c in cfg["countries"]:
        base = {k: c.get(k) for k in ("iso3", "name", "region", "tier", "atlas", "atlas_also", "gdelt", "news")}
        rows = country_rows(agg, c["iso3"], days)
        metrics = summarise(rows)
        items = stories.get(c["iso3"], [])
        dom = Counter(events.domain_of(a["url"]) for a in items)
        countries.append({
            **base,
            "metrics": metrics,
            "flags": flags(metrics),
            "series": [{k: r[k] for k in ("d", "n", "s", "t", "v", "p")} for r in rows[-WINDOW_DAYS:]],
            "gdelt": {"articles": story_list(items), "top_domains": dom.most_common(8), "event_mix": event_mix(agg, c["iso3"], last7)},
            "pending": not metrics,
        })

    # ---- 3. headlines
    for c in countries:
        h = gnews.fetch(c["news"])
        c["headlines"] = h if h is not None else []
    watch = []
    for t in cfg.get("watch_terms", []):
        week = gnews.fetch(t["news"], window="7d", limit=100) or []
        watch.append({"key": t["key"], "label": t["label"], "news": t["news"], "headlines": week[:15], "count_7d": len(week)})

    coverage_days = sum(1 for d in days if agg[(d, events.ALL)]["slots"] >= 90)
    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "site_title": cfg.get("site_title", "Conflict Media Monitor"),
        "method": {
            "violence_roots": sorted(events.VIOLENCE_ROOTS),
            "peace_bases": sorted(events.PEACE_BASES),
        },
        "run": {
            "slots_ingested": processed,
            "slots_remaining": remaining,
            "files_missing": missing,
            "complete_days": coverage_days,
            "seconds": round(time.time() - started),
            "total_countries": len(countries),
        },
        "countries": countries,
        "watch": watch,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    (DATA / "run_log.json").write_text(json.dumps(payload["run"], indent=1))
    (DATA / "history.csv").unlink(missing_ok=True)  # superseded by daily.csv
    print(f"Done in {payload['run']['seconds']}s: {coverage_days} complete days of history", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
