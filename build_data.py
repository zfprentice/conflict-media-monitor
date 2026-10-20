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
from monitor.metrics import baseline_band, flags, merge_daily, summarise, weekday_factors

ROOT = Path(__file__).parent
CONFIG = ROOT / "config" / "countries.json"
DATA = ROOT / "data"
OUT = DATA / "latest.json"
DAILY = DATA / "daily.csv"
SLOTS = DATA / "slots_done.txt"
ARTICLES = DATA / "recent_articles.json"

WINDOW_DAYS = 92
LAG_MINUTES = 20  # GDELT posts each file a few minutes after the slot
SETTLE_HOURS = 3  # a file still missing after this long is treated as skipped upstream
COMPLETE_SLOTS = 90  # of 96 quarter-hours; only complete days are scored


def country_rows(agg: dict, iso: str, days: list[str]) -> list[dict]:
    """Daily rows for complete days only (see metrics module docstring)."""
    vol, tone, viol, peace, med = {}, {}, {}, {}, {}
    for d in days:
        g, a = agg.get((d, events.ALL)), agg.get((d, iso))
        if not g or not g["articles"] or g["slots"] < COMPLETE_SLOTS:
            continue
        n = a["articles"] if a else 0
        vol[d] = {"count": int(n), "norm": int(g["articles"])}
        if a and n:
            tone[d] = round(a["tone_w"] / n, 3)
        viol[d] = {"count": int(a["viol"]) if a else 0}
        peace[d] = {"count": int(a["peace"]) if a else 0}
        med[d] = {"count": int(a["med"]) if a else 0}
    return merge_daily(vol, tone, viol, peace, med)


def today_so_far(agg: dict, iso: str, day: str) -> dict | None:
    """The current partial day, for display only. None once it is complete or under 2 hours in."""
    g, a = agg.get((day, events.ALL)), agg.get((day, iso))
    if not g or not g["articles"] or not 8 <= g["slots"] < COMPLETE_SLOTS:
        return None
    return {"n": int(a["articles"]) if a else 0, "norm": int(g["articles"]), "hours": round(g["slots"] / 4, 1)}


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
    news_budget = float(os.environ.get("NEWS_BUDGET_MIN", "6")) * 60
    started = time.time()
    deadline = started + budget
    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(days=WINDOW_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    keep_from = window_start.strftime("%Y-%m-%d")
    DATA.mkdir(exist_ok=True)

    # ---- 1. ingest new GDELT files
    if not events.state_is_current(DAILY):
        print("daily.csv uses an older column set; rebuilding history from scratch", flush=True)
        DAILY.unlink()
        SLOTS.unlink(missing_ok=True)
    agg = events.load_daily(DAILY)
    done = events.load_slots(SLOTS)
    todo = [s for s in events.slots_between(window_start, now - timedelta(minutes=LAG_MINUTES)) if s not in done]
    recent_cut = events.slot_id(now - timedelta(hours=72))
    fips, cameo = events.build_index(cfg["countries"])
    new_articles = defaultdict(list)
    settle_cut = events.slot_id(now - timedelta(hours=SETTLE_HOURS))
    processed = missing = deferred = 0
    print(f"{len(todo)} slots to ingest ({len(done)} already done)", flush=True)
    for slot, streams in events.download_slots(todo, deadline - 120):
        if not events.slot_settled(streams, slot, settle_cut):
            deferred += 1
            continue
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
    print(f"Ingested {processed} slots ({missing} files missing upstream, {deferred} recent ones not posted yet); "
          f"{remaining} left for later runs", flush=True)

    # ---- 2. metrics per country
    days = sorted({d for (d, k) in agg if k == events.ALL and d >= keep_from})
    last7 = days[-7:]
    countries = []
    for c in cfg["countries"]:
        base = {k: c.get(k) for k in ("iso3", "name", "region", "tier", "atlas", "atlas_also", "gdelt", "news")}
        rows = country_rows(agg, c["iso3"], days)
        metrics = summarise(rows, today_so_far(agg, c["iso3"], days[-1]) if days else None)
        band = baseline_band(rows, weekday_factors(rows))
        items = stories.get(c["iso3"], [])
        dom = Counter(events.domain_of(a["url"]) for a in items)
        countries.append({
            **base,
            "metrics": metrics,
            "flags": flags(metrics),
            "series": [{**{k: r[k] for k in ("d", "n", "s", "t", "v", "p", "m")}, "b": b} for r, b in zip(rows, band)][-WINDOW_DAYS:],
            "gdelt": {"articles": story_list(items), "top_domains": dom.most_common(8), "event_mix": event_mix(agg, c["iso3"], last7)},
            "pending": not metrics,
        })

    # ---- 3. headlines (time-boxed; on failure keep the previous run's, marked with their age)
    prev = json.loads(OUT.read_text()) if OUT.exists() and OUT.stat().st_size else {}
    prev_c = {c["iso3"]: c for c in prev.get("countries", [])}
    prev_w = {w["key"]: w for w in prev.get("watch", [])}
    stamp = now.isoformat(timespec="seconds")
    news_deadline = time.time() + news_budget
    news_failed = 0
    watch = []
    for t in cfg.get("watch_terms", []):  # first, so the budget never squeezes it out
        week = gnews.fetch(t["news"], window="7d", limit=100, deadline=news_deadline)
        if week is None:
            news_failed += 1
            old = prev_w.get(t["key"], {})
            watch.append({**old, "key": t["key"], "label": t["label"], "news": t["news"],
                          "headlines": old.get("headlines", []), "count_7d": old.get("count_7d"),
                          "headlines_at": old.get("headlines_at")})
        else:
            watch.append({"key": t["key"], "label": t["label"], "news": t["news"], "headlines": week[:15],
                          "count_7d": len(week), "headlines_at": stamp})
    for c in countries:
        h = gnews.fetch(c["news"], deadline=news_deadline)
        if h is None:
            news_failed += 1
            old = prev_c.get(c["iso3"], {})
            c["headlines"], c["headlines_at"] = old.get("headlines", []), old.get("headlines_at")
        else:
            c["headlines"], c["headlines_at"] = h, stamp
    if news_failed:
        print(f"Google News: {news_failed} queries failed or ran out of time; kept earlier headlines", flush=True)

    coverage_days = sum(1 for d in days if agg[(d, events.ALL)]["slots"] >= COMPLETE_SLOTS)
    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "site_title": cfg.get("site_title", "Conflict Media Monitor"),
        "method": {
            "violence_roots": sorted(events.VIOLENCE_ROOTS),
            "peace_bases": sorted(events.PEACE_BASES),
            "mediation_bases": sorted(events.MEDIATION_BASES),
            "scored_day": max((c["metrics"]["latest_day"] for c in countries if c["metrics"]), default=None),
        },
        "run": {
            "slots_ingested": processed,
            "slots_remaining": remaining,
            "files_missing": missing,
            "slots_deferred": deferred,
            "news_failed": news_failed,
            "news_total": len(countries) + len(cfg.get("watch_terms", [])),
            "complete_days": coverage_days,
            "seconds": round(time.time() - started),
            "total_countries": len(countries),
        },
        "countries": countries,
        "watch": watch,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    (DATA / "run_log.json").write_text(json.dumps(payload["run"], indent=1))
    print(f"Done in {payload['run']['seconds']}s: {coverage_days} complete days of history", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
