"""Fetch media-attention data for every country in config/countries.json.

Writes:
  data/latest.json   everything the dashboard renders
  data/history.csv   daily archive that keeps growing past GDELT's 3-month window

Run locally:  python build_data.py            (all countries, ~15 min — GDELT rate limit)
              ONLY=UKR,SDN python build_data.py  (subset, for testing)
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from monitor import gdelt, gnews
from monitor.metrics import flags, merge_daily, summarise

ROOT = Path(__file__).parent
CONFIG = ROOT / "config" / "countries.json"
OUT = ROOT / "data" / "latest.json"
HISTORY = ROOT / "data" / "history.csv"


def fetch_entity(client: gdelt.Client, q: str, news_q: str, framing: dict | None) -> dict | None:
    vol_raw = client.get(gdelt.build_url(q, "timelinevolraw", timelinesmooth=0))
    if vol_raw is None:
        return None
    vol = gdelt.parse_timeline_volraw(vol_raw)
    tone = gdelt.parse_timeline_tone(client.get(gdelt.build_url(q, "timelinetone")))
    viol = peace = {}
    if framing:
        viol = gdelt.parse_timeline_volraw(client.get(gdelt.build_url(f"{q} {framing['violence']}", "timelinevolraw")))
        peace = gdelt.parse_timeline_volraw(client.get(gdelt.build_url(f"{q} {framing['peace']}", "timelinevolraw")))
    arts = gdelt.parse_artlist(client.get(gdelt.build_url(q, "artlist", timespan="3d", maxrecords=75, sort="datedesc")))
    rows = merge_daily(vol, tone, viol, peace)
    metrics = summarise(rows)
    headlines = gnews.fetch(news_q) or []
    return {
        "metrics": metrics,
        "flags": flags(metrics),
        "series": [{k: r[k] for k in ("d", "n", "s", "t", "v", "p")} for r in rows[-92:]],
        "gdelt": arts,
        "headlines": headlines,
        "stale": False,
    }


def update_history(countries: list[dict]):
    rows: dict[tuple, dict] = {}
    if HISTORY.exists():
        with HISTORY.open() as f:
            for r in csv.DictReader(f):
                rows[(r["date"], r["iso3"])] = r
    for c in countries:
        if c.get("stale"):
            continue
        for p in c.get("series", []):
            n = p["n"] or 0
            rows[(p["d"], c["iso3"])] = {
                "date": p["d"], "iso3": c["iso3"], "articles": n,
                "share_per_10k": p["s"] if p["s"] is not None else "",
                "tone": p["t"] if p["t"] is not None else "",
                "violence_pct": round(100 * p["v"] / n, 2) if p["v"] is not None and n else "",
                "peace_pct": round(100 * p["p"] / n, 2) if p["p"] is not None and n else "",
            }
    fields = ["date", "iso3", "articles", "share_per_10k", "tone", "violence_pct", "peace_pct"]
    with HISTORY.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for key in sorted(rows):
            w.writerow({k: rows[key].get(k, "") for k in fields})


def main() -> int:
    cfg = json.loads(CONFIG.read_text())
    only = {s.strip().upper() for s in os.environ.get("ONLY", "").split(",") if s.strip()}
    previous = {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text())
            previous = {c["iso3"]: c for c in prev.get("countries", [])}
            previous.update({f"watch:{w['key']}": w for w in prev.get("watch", [])})
        except (json.JSONDecodeError, KeyError):
            pass

    client = gdelt.Client()
    started = time.time()
    countries = []
    for c in cfg["countries"]:
        base = {k: c.get(k) for k in ("iso3", "name", "region", "tier", "atlas", "atlas_also", "gdelt", "news")}
        if only and c["iso3"] not in only:
            if c["iso3"] in previous:
                countries.append({**previous[c["iso3"]], **base})
            continue
        print(f"→ {c['name']}")
        data = fetch_entity(client, c["gdelt"], c["news"], cfg["framing"])
        if data is None:
            print(f"  ✗ {c['name']}: GDELT unavailable, keeping previous data")
            old = previous.get(c["iso3"])
            countries.append({**(old or {}), **base, "stale": True})
            continue
        countries.append({**base, **data})

    watch = []
    for t in cfg.get("watch_terms", []):
        print(f"→ watch: {t['label']}")
        data = fetch_entity(client, t["gdelt"], t["news"], None)
        if data is None:
            old = previous.get(f"watch:{t['key']}")
            watch.append({**(old or {}), "key": t["key"], "label": t["label"], "stale": True})
        else:
            watch.append({"key": t["key"], "label": t["label"], "gdelt": t["gdelt"], "news": t["news"], **data})

    fresh = sum(1 for c in countries if not c.get("stale"))
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "site_title": cfg.get("site_title", "Conflict Media Monitor"),
        "framing": cfg["framing"],
        "run": {
            "gdelt_calls": client.calls,
            "gdelt_failures": client.failures,
            "seconds": round(time.time() - started),
            "fresh_countries": fresh,
            "total_countries": len(countries),
        },
        "countries": countries,
        "watch": watch,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    update_history(countries)
    print(f"Done: {fresh}/{len(countries)} fresh, {client.calls} GDELT calls, {payload['run']['seconds']}s")
    # Fail the job only if nothing at all came back, so a GDELT outage is visible in Actions.
    return 0 if fresh or only else 1


if __name__ == "__main__":
    sys.exit(main())
