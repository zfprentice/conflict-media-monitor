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


def fetch_entity(client: gdelt.Client, q: str, news_q: str, framing: dict | None, deadline: float) -> dict:
    """Fetch one country. Always returns headlines; GDELT parts are None if unavailable."""
    out = {"headlines": gnews.fetch(news_q)}
    if client.down or time.time() > deadline:
        return out
    vol_raw = client.get(gdelt.build_url(q, "timelinevolraw", timelinesmooth=0))
    if not vol_raw:
        return out
    vol = gdelt.parse_timeline_volraw(vol_raw)

    def maybe(url, parse, empty):
        if client.down or time.time() > deadline:
            return empty
        return parse(client.get(url))

    tone = maybe(gdelt.build_url(q, "timelinetone"), gdelt.parse_timeline_tone, {})
    viol = peace = {}
    if framing:
        viol = maybe(gdelt.build_url(f"{q} {framing['violence']}", "timelinevolraw"), gdelt.parse_timeline_volraw, {})
        peace = maybe(gdelt.build_url(f"{q} {framing['peace']}", "timelinevolraw"), gdelt.parse_timeline_volraw, {})
    arts = maybe(gdelt.build_url(q, "artlist", timespan="3d", maxrecords=75, sort="datedesc"), gdelt.parse_artlist, None)
    rows = merge_daily(vol, tone, viol, peace)
    metrics = summarise(rows)
    out.update({
        "metrics": metrics,
        "flags": flags(metrics),
        "series": [{k: r[k] for k in ("d", "n", "s", "t", "v", "p")} for r in rows[-92:]],
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "partial": not (tone and (viol or not framing) and arts),
    })
    if arts is not None:
        out["gdelt"] = arts
    return out


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


def merge(old: dict | None, base: dict, new: dict) -> dict:
    """Combine a fresh fetch with the previous run's record for the same entity."""
    rec = {**(old or {}), **base}
    if new.get("headlines") is not None:
        rec["headlines"] = new["headlines"]
    if "metrics" in new:
        rec.update({k: new[k] for k in ("metrics", "flags", "series", "fetched_at", "partial")})
        if "gdelt" in new:
            rec["gdelt"] = new["gdelt"]
        rec["stale"] = False
    else:
        rec["stale"] = bool(rec.get("metrics"))
    rec["pending"] = not rec.get("metrics")
    return rec


def main() -> int:
    cfg = json.loads(CONFIG.read_text())
    only = {s.strip().upper() for s in os.environ.get("ONLY", "").split(",") if s.strip()}
    budget = float(os.environ.get("BUDGET_MIN", "32")) * 60
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
    deadline = started + budget

    entities = []
    for t in cfg.get("watch_terms", []):
        entities.append(("watch:" + t["key"], {"key": t["key"], "label": t["label"], "gdelt": t["gdelt"], "news": t["news"]}, None))
    for c in cfg["countries"]:
        base = {k: c.get(k) for k in ("iso3", "name", "region", "tier", "atlas", "atlas_also", "gdelt", "news")}
        entities.append((c["iso3"], base, cfg["framing"]))
    # Oldest (or never) fetched first, so a run cut short by the time budget
    # still rotates through every country over successive runs.
    order = sorted(entities, key=lambda e: (previous.get(e[0]) or {}).get("fetched_at") or "")

    results = {}
    for key, base, framing in order:
        if only and key not in only and not key.startswith("watch:"):
            results[key] = {**(previous.get(key) or {}), **base}
            continue
        label = base.get("name") or base.get("label")
        left = deadline - time.time()
        print(f"→ {label} ({left / 60:.0f} min of budget left)", flush=True)
        new = fetch_entity(client, base["gdelt"], base["news"], framing, deadline - 60)
        results[key] = merge(previous.get(key), base, new)
        print(f"  {'✓' if 'metrics' in new else '·'} {label}: {'GDELT ok' if 'metrics' in new else 'headlines only'}", flush=True)

    countries = [results[e[0]] for e in entities if not e[0].startswith("watch:")]
    watch = [results[e[0]] for e in entities if e[0].startswith("watch:")]
    fresh = sum(1 for c in countries if not c.get("stale") and not c.get("pending"))
    secs = [x["s"] for x in client.log if x["outcome"] == "ok"]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "site_title": cfg.get("site_title", "Conflict Media Monitor"),
        "framing": cfg["framing"],
        "run": {
            "gdelt_calls": client.calls,
            "gdelt_failures": client.failures,
            "gdelt_down": client.down,
            "gdelt_median_s": sorted(secs)[len(secs) // 2] if secs else None,
            "seconds": round(time.time() - started),
            "fresh_countries": fresh,
            "pending_countries": sum(1 for c in countries if c.get("pending")),
            "total_countries": len(countries),
        },
        "countries": countries,
        "watch": watch,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    (OUT.parent / "run_log.json").write_text(json.dumps({"run": payload["run"], "calls": client.log}, indent=1))
    update_history([c for c in countries if not c.get("stale")])
    print(f"Done: {fresh}/{len(countries)} refreshed from GDELT, {client.calls} calls, {payload['run']['seconds']}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
