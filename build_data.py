"""Build the dashboard data from GDELT raw event files and Google News.

Each run:
  1. downloads any 15-minute GDELT event files (English + translated streams)
     from the last 92 days it hasn't processed yet, newest first, within a
     time budget, and adds them to data/daily.csv (kept indefinitely);
  2. recomputes every country's metrics from daily.csv;
  3. refreshes Google News headlines, drops off-topic ones, groups them into
     stories and tags their themes; records every watch-term (EIP) mention;
     freezes finished weeks' stories into data/weekly/;
  4. writes the page data (latest.json, weekly.json, eip_mentions.json) and
     the Excel workbooks.

Records (committed): daily.csv, slots_done.txt, recent_articles.json,
news.json, weekly/*.json, *_mentions.csv, backfill_done.txt, run_log.json.
Outputs (rebuilt every run, not committed): latest.json, weekly.json,
*_mentions.json, *.xlsx.

Run locally:  python build_data.py              (BUDGET_MIN=10 for a shorter run)
              OFFLINE=1 python build_data.py    (rebuild the outputs from the records, no network)
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from monitor import archive, events, excel, gnews, narrative
from monitor import stories as st
from monitor.metrics import baseline_band, flags, merge_daily, summarise, week_stats, weekday_factors

ROOT = Path(__file__).parent
CONFIG = ROOT / "config" / "countries.json"
DATA = ROOT / "data"

WINDOW_DAYS = 92  # GDELT backfill window and chart span; daily.csv itself keeps everything
LAG_MINUTES = 20  # GDELT posts each file a few minutes after the slot
SETTLE_HOURS = 3  # a file still missing after this long is treated as skipped upstream
COMPLETE_SLOTS = 90  # of 96 quarter-hours; only complete days are scored
WEEKS_BACK = 13  # finished weeks whose stories are collected (and backfilled) from Google News
BACKFILL_REQUESTS = 60  # per run, for finished weeks and older watch-term months
TIER_LABELS = {"operates": "Field presence", "dialogue": "Regional dialogue"}


def paths(data: Path) -> dict:
    return {
        "daily": data / "daily.csv", "slots": data / "slots_done.txt", "articles": data / "recent_articles.json",
        "news": data / "news.json", "weeks": data / "weekly", "backfill": data / "backfill_done.txt",
        "run": data / "run_log.json", "latest": data / "latest.json", "weekly": data / "weekly.json",
        "history_xlsx": data / "history.xlsx",
    }


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


def story_list(items: list[dict], matcher: st.Matcher | None = None, limit: int = 40) -> list[dict]:
    """GDELT's most-covered stories, keeping only titles that read as English and name the country."""
    out = []
    for a in items:
        s = a["slot"]
        domain = events.domain_of(a["url"])
        title = events.title_from_url(a["url"]) or domain
        if matcher and not (st.readable_slug_title(title, domain) and matcher.mentions(title)):
            continue
        out.append({
            "title": title, "url": a["url"], "domain": domain, "mentions": a["mentions"],
            "kind": events.ROOT_NAMES.get(a["root"], ""),
            "seen": f"{s[0:4]}-{s[4:6]}-{s[6:8]}T{s[8:10]}:{s[10:12]}:00+00:00",
        })
        if len(out) >= limit:
            break
    return out


def clean_headlines(items: list[dict] | None, matcher: st.Matcher) -> list[dict]:
    return [h for h in items or [] if matcher.mentions(h["title"]) and not st.is_noise(h["title"], h.get("source", ""))]


def ingest_gdelt(cfg: dict, p: dict, now: datetime, deadline: float, started: float) -> tuple[dict, dict, dict]:
    """Download new GDELT files into daily.csv; returns (agg, stories, run stats)."""
    window_start = (now - timedelta(days=WINDOW_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    keep_from = window_start.strftime("%Y-%m-%d")
    if not events.state_is_current(p["daily"]):
        print("daily.csv uses an older column set; rebuilding history from scratch", flush=True)
        p["daily"].unlink()
        p["slots"].unlink(missing_ok=True)
    agg = events.load_daily(p["daily"])
    done = events.load_slots(p["slots"])
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
    events.save_daily(p["daily"], agg, "")  # all history is kept; only the slot list is trimmed to the window
    events.save_slots(p["slots"], done, keep_from)
    old_articles = json.loads(p["articles"].read_text()) if p["articles"].exists() else {}
    stories = events.merge_articles(old_articles, new_articles, now)
    p["articles"].write_text(json.dumps(stories, separators=(",", ":")))
    remaining = len(todo) - processed
    print(f"Ingested {processed} slots ({missing} files missing upstream, {deferred} recent ones not posted yet); "
          f"{remaining} left for later runs", flush=True)
    return agg, stories, {"slots_ingested": processed, "slots_remaining": remaining, "files_missing": missing,
                          "slots_deferred": deferred}


class NewsClient:
    """Google News within a time budget; stops early if Google starts refusing every request."""

    def __init__(self, budget_s: float):
        self.deadline = time.time() + budget_s
        self.requests = self.failed = self.streak = 0

    @property
    def usable(self) -> bool:
        return self.streak < 6 and time.time() < self.deadline - 2

    def get(self, query: str, **kw) -> list[dict] | None:
        if not self.usable:
            return None
        self.requests += 1
        r = gnews.fetch(query, deadline=self.deadline, **kw)
        if r is None:
            self.failed += 1
            self.streak += 1
        else:
            self.streak = 0
        time.sleep(0.25)
        return r


def refresh_news(cfg: dict, p: dict, now: datetime, news: dict, mentions: dict, client: NewsClient) -> dict:
    """Fetch headlines and watch-term mentions; update news.json entries, week snapshots and mention records."""
    stamp = now.isoformat(timespec="seconds")
    today = now.date()
    countries = cfg["countries"]
    matchers = {c["iso3"]: st.Matcher(c) for c in countries}
    tag = lambda title: [c["name"] for c in countries if matchers[c["iso3"]].mentions(title)]  # noqa: E731
    stats = {"news_failed": 0, "news_total": 0, "mentions_new": 0, "weeks_filled": 0, "weeks_empty": 0, "months_filled": 0}

    # 1. watch terms, last 7 days, every edition (first, so the budget never squeezes them out)
    for t in cfg.get("watch_terms", []):
        for q in t["queries"]:
            stats["news_total"] += 1
            items = client.get(q["q"], window="7d", edition=q["edition"])
            if items is None:
                stats["news_failed"] += 1
                continue
            stats["mentions_new"] += archive.merge_mentions(mentions[t["key"]], items, term=t["label"],
                                                            language=q["lang"], found=stamp[:16].replace("T", " "),
                                                            tag_countries=tag)

    # 2. each country: last 2 days (fresh) + last 7 days (the week's main stories)
    wid = archive.week_id(today)
    wstart, wend = archive.week_bounds(wid)
    snap = archive.load_week(p["weeks"], wid)
    for c in countries:
        stats["news_total"] += 1
        iso, m = c["iso3"], matchers[c["iso3"]]
        fresh = client.get(c["news"], window="2d")
        week = client.get(c["news"], window="7d")
        if fresh is None and week is None:
            stats["news_failed"] += 1
            continue  # keep the previous entry; the page shows its age
        pool = st.dedupe(clean_headlines(fresh, m) + clean_headlines(week, m))
        cut = (now - timedelta(days=7)).isoformat()
        recent = [h for h in pool if (h.get("published") or "") >= cut]
        latest = sorted(pool, key=lambda h: h.get("published") or "", reverse=True)[:25]
        ignore = st.ignore_words(c)
        news[iso] = {"at": stamp, "latest": latest, "recent": st.analyse(recent, ignore)}
        this_week = [h for h in pool if archive.in_week(h.get("published"), wstart, wend)]
        snap["countries"][iso] = {**st.analyse(this_week, ignore), "final": False, "at": stamp}
    archive.save_week(p["weeks"], snap)

    # 3. finished weeks: one date-bounded search per country, newest week first, then frozen
    budget = BACKFILL_REQUESTS
    for w in archive.recent_weeks(today, WEEKS_BACK + 1)[1:]:
        if budget <= 0 or not client.usable:
            break
        s, e = archive.week_bounds(w)
        snap = archive.load_week(p["weeks"], w)
        changed = False
        for c in countries:
            if snap["countries"].get(c["iso3"], {}).get("final") or budget <= 0 or not client.usable:
                continue
            budget -= 1
            items = client.get(c["news"], after=s.isoformat(), before=(e + timedelta(days=1)).isoformat())
            if not items:  # failed, or an empty answer: try again next run rather than freeze an empty week
                stats["weeks_empty"] += 1
                continue
            got = [h for h in clean_headlines(items, matchers[c["iso3"]]) if archive.in_week(h.get("published"), s, e)]
            snap["countries"][c["iso3"]] = {**st.analyse(got, st.ignore_words(c)), "final": True, "at": stamp}
            changed = True
        if changed:
            archive.save_week(p["weeks"], snap)
            stats["weeks_filled"] += 1

    # 4. older watch-term mentions, one month per request, newest first
    done = set(p["backfill"].read_text().split("\n")) if p["backfill"].exists() else set()
    for t in cfg.get("watch_terms", []):
        for a, b in archive.months_between(t.get("backfill_from", "2025-01-01"), today):
            for q in t["queries"]:
                key = f"{t['key']}|{q['lang']}|{a}"
                if key in done or budget <= 0 or not client.usable:
                    continue
                budget -= 1
                items = client.get(q["q"], edition=q["edition"], after=a, before=b)
                if items is None:
                    continue
                stats["mentions_new"] += archive.merge_mentions(mentions[t["key"]], items, term=t["label"],
                                                                language=q["lang"], found=stamp[:16].replace("T", " "),
                                                                tag_countries=tag)
                if b <= today.isoformat():  # a month still in progress is searched again next run
                    done.add(key)
                stats["months_filled"] += 1
    p["backfill"].write_text("\n".join(sorted(k for k in done if k)) + "\n")
    print(f"Google News: {client.requests} requests, {client.failed} failed; {stats['mentions_new']} new watch-term "
          f"mentions; {stats['weeks_filled']} past weeks and {stats['months_filled']} past months filled "
          f"({stats['weeks_empty']} country-weeks came back empty and will be retried)", flush=True)
    sizes = {iso: e["recent"]["n"] for iso, e in news.items() if e.get("at") == stamp}
    if sizes:
        print(f"  headlines kept per country this run: min {min(sizes.values())}, max {max(sizes.values())}, "
              f"total {sum(sizes.values())}", flush=True)
    return stats


def mention_summary(t: dict, rows: list[dict], today: date, done: set) -> dict:
    def since(d):
        return sum(1 for r in rows if (r["published"] or r["found"])[:10] >= d.isoformat())
    q_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    months = Counter((r["published"] or r["found"])[:7] for r in rows)
    span = archive.months_between(t.get("backfill_from", "2025-01-01"), today)
    want = {f"{t['key']}|{q['lang']}|{a}" for a, _ in span for q in t["queries"] if _ <= today.isoformat()}
    return {
        "key": t["key"], "label": t["label"], "total": len(rows), "since": t.get("backfill_from"),
        "languages": [q["lang"] for q in t["queries"]],
        "count_7d": since(today - timedelta(days=7)), "count_30d": since(today - timedelta(days=30)),
        "count_quarter": since(q_start), "count_year": since(date(today.year, 1, 1)),
        "quarter_label": f"Q{(today.month - 1) // 3 + 1} {today.year}",
        "by_month": [[f"{a[:7]}", months.get(a[:7], 0)] for a, _ in reversed(span)],
        "backfill_done": len(want & done), "backfill_total": len(want),
        "recent": [{"title": r["title"], "url": r["link"], "source": r["outlet"], "published": r["published"],
                    "language": r["language"], "countries": r["countries"]} for r in rows[:8]],
        "files": {"xlsx": f"data/{t['key']}_mentions.xlsx", "csv": f"data/{t['key']}_mentions.csv",
                  "json": f"data/{t['key']}_mentions.json"},
    }


def build_weekly(cfg: dict, p: dict, rows_by: dict, bands: dict, today: date, mentions: dict) -> list[dict]:
    """Every week with data, newest first: figures from daily.csv, stories from the week snapshots."""
    first_days = [r[0]["d"] for r in rows_by.values() if r]
    weeks = set(archive.all_weeks(p["weeks"]))
    if first_days:
        d = date.fromisoformat(min(first_days))
        while d <= today:
            weeks.add(archive.week_id(d))
            d += timedelta(days=7)
    weeks.add(archive.week_id(today))
    out = []
    for wid in sorted(weeks, reverse=True):
        start, end = archive.week_bounds(wid)
        snap = archive.load_week(p["weeks"], wid)
        prev = archive.load_week(p["weeks"], archive.week_id(start - timedelta(days=7)))
        cs = {}
        for c in cfg["countries"]:
            iso = c["iso3"]
            wk = week_stats(rows_by[iso], bands[iso], start.isoformat(), end.isoformat())
            s, ps = snap["countries"].get(iso), prev["countries"].get(iso)
            if not wk and not s:
                continue
            cs[iso] = {
                "stats": wk,
                "summary": narrative.week_summary(c["name"], wk, (s or {}).get("themes"), (s or {}).get("n", 0),
                                                  (ps or {}).get("themes"), (ps or {}).get("n", 0)),
                "stories": [{**x, "also": x.get("also", [])[:2]} for x in (s or {}).get("stories", [])[:5]],
                "themes": (s or {}).get("themes"), "n": (s or {}).get("n", 0),
                "themes_prev": (ps or {}).get("themes"), "n_prev": (ps or {}).get("n", 0),
                "names": (s or {}).get("names", []), "collected": s is not None, "final": bool((s or {}).get("final")),
            }
        if not cs:
            continue
        eip = {}
        for key, rows in mentions.items():
            eip[key] = [{"title": r["title"], "url": r["link"], "source": r["outlet"], "published": r["published"],
                         "language": r["language"]}
                        for r in rows if start.isoformat() <= (r["published"] or r["found"])[:10] <= end.isoformat()]
        out.append({"week": wid, "start": start.isoformat(), "end": end.isoformat(),
                    "current": wid == archive.week_id(today), "countries": cs, "mentions": eip})
    return out


def main(data: Path = DATA, cfg_path: Path = CONFIG) -> int:
    cfg = json.loads(cfg_path.read_text())
    offline = os.environ.get("OFFLINE") == "1"
    budget = float(os.environ.get("BUDGET_MIN", "30")) * 60
    news_budget = float(os.environ.get("NEWS_BUDGET_MIN", "6")) * 60
    started = time.time()
    data.mkdir(exist_ok=True)
    p = paths(data)
    prev_run = json.loads(p["run"].read_text()) if p["run"].exists() else {}

    # ---- 1. GDELT (offline: reuse the records as of the last data run)
    if offline:
        now = datetime.fromisoformat(prev_run["generated_at"]) if prev_run.get("generated_at") else datetime.now(timezone.utc)
        agg = events.load_daily(p["daily"])
        stories = json.loads(p["articles"].read_text()) if p["articles"].exists() else {}
        run = {k: prev_run.get(k) for k in ("slots_ingested", "slots_remaining", "files_missing", "slots_deferred")}
    else:
        now = datetime.now(timezone.utc)
        agg, stories, run = ingest_gdelt(cfg, p, now, started + budget, started)

    # ---- 2. headlines, stories, watch-term mentions
    news = json.loads(p["news"].read_text()) if p["news"].exists() else {}
    mentions = {t["key"]: archive.load_mentions(data / f"{t['key']}_mentions.csv") for t in cfg.get("watch_terms", [])}
    if offline:
        run.update({k: prev_run.get(k) for k in ("news_failed", "news_total", "mentions_new", "weeks_filled", "weeks_empty", "months_filled")})
    else:
        run.update(refresh_news(cfg, p, now, news, mentions, NewsClient(news_budget)))
        p["news"].write_text(json.dumps(news, ensure_ascii=False, separators=(",", ":")))
        for key, rows in mentions.items():
            archive.save_mentions(data / f"{key}_mentions.csv", rows)
        mentions = {k: archive.load_mentions(data / f"{k}_mentions.csv") for k in mentions}  # re-read sorted

    # ---- 3. metrics per country
    days = sorted({d for (d, k) in agg if k == events.ALL})
    last7 = days[-7:]
    countries, rows_by, bands = [], {}, {}
    for c in cfg["countries"]:
        iso = c["iso3"]
        base = {k: c.get(k) for k in ("iso3", "name", "region", "tier", "atlas", "atlas_also", "gdelt", "news")}
        rows = country_rows(agg, iso, days)
        window = rows[-WINDOW_DAYS:]
        metrics = summarise(window, today_so_far(agg, iso, days[-1]) if days else None)
        band = baseline_band(rows, weekday_factors(window))
        rows_by[iso], bands[iso] = rows, band
        items = stories.get(iso, [])
        dom = Counter(events.domain_of(a["url"]) for a in items)
        entry = news.get(iso, {})
        recent = entry.get("recent") or {}
        countries.append({
            **base,
            "metrics": metrics,
            "flags": flags(metrics),
            "attention": narrative.attention(metrics.get("z_attention")),
            "summary": narrative.country_summary(c["name"], metrics, recent),
            "series": [{**{k: r[k] for k in ("d", "n", "s", "t", "v", "p", "m")}, "b": b} for r, b in zip(rows, band)][-WINDOW_DAYS:],
            "gdelt": {"articles": story_list(items, st.Matcher(c)), "top_domains": dom.most_common(8),
                      "event_mix": event_mix(agg, iso, last7)},
            "headlines": entry.get("latest", []), "headlines_at": entry.get("at"),
            "recent": recent,
            "pending": not metrics,
        })

    # ---- 4. outputs
    today = now.date()
    done = set(p["backfill"].read_text().split("\n")) if p["backfill"].exists() else set()
    stamp = now.isoformat(timespec="seconds")
    watch = []
    for t in cfg.get("watch_terms", []):
        rows = mentions[t["key"]]
        watch.append(mention_summary(t, rows, today, done))
        (data / f"{t['key']}_mentions.json").write_text(json.dumps(
            [{"title": r["title"], "url": r["link"], "source": r["outlet"], "published": r["published"],
              "language": r["language"], "countries": r["countries"], "found": r["found"]} for r in rows],
            ensure_ascii=False, separators=(",", ":")))
        excel.write_mentions(data / f"{t['key']}_mentions.xlsx", t["label"], rows, stamp[:16].replace("T", " "),
                             t.get("backfill_from", ""))

    weekly = build_weekly(cfg, p, rows_by, bands, today, mentions)
    p["weekly"].write_text(json.dumps({"generated_at": stamp, "weeks": weekly}, ensure_ascii=False, separators=(",", ":")))
    excel.write_history(
        p["history_xlsx"],
        [{"name": c["name"], "region": c["region"], "tier_label": TIER_LABELS.get(c["tier"], c["tier"]),
          "series": [{**r, "b": b} for r, b in zip(rows_by[c["iso3"]], bands[c["iso3"]])]} for c in cfg["countries"]],
        [{"week": w["week"], "start": w["start"], "country": next(c["name"] for c in cfg["countries"] if c["iso3"] == iso),
          "summary": " ".join(x["summary"]), "share": (x["stats"] or {}).get("share"),
          "change_pct": (x["stats"] or {}).get("change_pct"), "unusual_days": len((x["stats"] or {}).get("unusual_days", [])),
          "violence": (x["stats"] or {}).get("violence"),
          "story": x["stories"][0]["title"] if x["stories"] else "", "story_url": x["stories"][0]["url"] if x["stories"] else None,
          "outlets": x["stories"][0]["outlets"] if x["stories"] else None}
         for w in weekly for iso, x in w["countries"].items()],
        stamp[:16].replace("T", " "),
    )

    coverage_days = sum(1 for d in days[-WINDOW_DAYS:] if agg[(d, events.ALL)]["slots"] >= COMPLETE_SLOTS)
    run.update({
        "generated_at": stamp,
        "complete_days": coverage_days,
        "history_days": sum(1 for d in days if agg[(d, events.ALL)]["slots"] >= COMPLETE_SLOTS),
        "seconds": prev_run.get("seconds") if offline else round(time.time() - started),
        "total_countries": len(countries),
    })
    payload = {
        "generated_at": stamp,
        "site_title": cfg.get("site_title", "Conflict Media Monitor"),
        "method": {
            "violence_roots": sorted(events.VIOLENCE_ROOTS),
            "diplomacy_bases": sorted(events.PEACE_BASES),
            "scored_day": max((c["metrics"]["latest_day"] for c in countries if c["metrics"]), default=None),
            "themes": st.THEME_LABELS,
        },
        "run": run,
        "countries": countries,
        "watch": watch,
        "weeks": [{"week": w["week"], "start": w["start"], "end": w["end"], "current": w["current"]} for w in weekly],
    }
    p["latest"].write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    if not offline:
        p["run"].write_text(json.dumps(run, indent=1))
    print(f"Done in {round(time.time() - started)}s: {coverage_days} complete days in the window, "
          f"{run['history_days']} in all; {len(weekly)} weeks in the weekly report", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
