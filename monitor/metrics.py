"""Pure metric computations on daily GDELT series. No network, fully testable.

Rows passed in are complete UTC days only: a partial day's share depends on
which hours have been ingested (Americas-heavy overnight, Europe-heavy in the
morning), so it is reported separately and never scored.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import median


def merge_daily(vol: dict, tone: dict, viol: dict, peace: dict, med: dict | None = None) -> list[dict]:
    rows = []
    for d, v in sorted(vol.items()):
        count, norm = v["count"], v["norm"]
        rows.append({
            "d": d,
            "n": count,
            "norm": norm,
            "s": round(count / norm * 1e4, 3) if norm else None,  # per 10k articles worldwide
            "t": tone.get(d),
            "v": viol.get(d, {}).get("count") if viol else None,
            "p": peace.get(d, {}).get("count") if peace else None,
            "m": med.get(d, {}).get("count") if med else None,
        })
    return rows


def latest_index(rows: list[dict]) -> int | None:
    """Index of the most recent day with any monitored volume."""
    for i in range(len(rows) - 1, -1, -1):
        if rows[i]["norm"]:
            return i
    return None


def weekday_factors(rows: list[dict], min_weeks: int = 3) -> list[float]:
    """Typical share on each weekday relative to the overall median (Mon=0).

    Countries have strong weekly rhythms (Gulf coverage rises at weekends,
    Moldova's falls by 40%), which a plain rolling baseline would flag as
    anomalies every week. Medians keep a single spike from moving the factor.
    """
    by_day = [[] for _ in range(7)]
    for r in rows:
        if r["s"] is not None:
            by_day[date.fromisoformat(r["d"]).weekday()].append(r["s"])
    if min(len(v) for v in by_day) < min_weeks:
        return [1.0] * 7
    overall = median([s for v in by_day for s in v])
    if overall <= 0:
        return [1.0] * 7
    return [median(v) / overall if median(v) > 0 else 1.0 for v in by_day]


def adjusted_shares(rows: list[dict], factors: list[float]) -> list[float | None]:
    return [r["s"] / factors[date.fromisoformat(r["d"]).weekday()] if r["s"] is not None else None for r in rows]


def _scale(hist: list[float]) -> tuple[float, float | None]:
    """Median and robust spread (1.4826 x MAD, falling back to the SD when MAD is 0)."""
    med = median(hist)
    scale = 1.4826 * median([abs(h - med) for h in hist])
    if scale < 1e-9:
        mean = sum(hist) / len(hist)
        sd = math.sqrt(sum((h - mean) ** 2 for h in hist) / max(len(hist) - 1, 1))
        scale = sd if sd > 1e-9 else None
    return med, scale


def baseline_band(rows: list[dict], factors: list[float], win: int = 28) -> list[list[float] | None]:
    """Per day [lo, median, hi] of the expected share: the weekday-adjusted rolling
    median of the previous `win` days +/- 2 robust SDs, mapped back to that day's
    weekday. A day above `hi` is what the anomaly score calls unusual."""
    adj = adjusted_shares(rows, factors)
    out = []
    for i, r in enumerate(rows):
        hist = [h for h in adj[max(0, i - win): i] if h is not None]
        if len(hist) < 7:
            out.append(None)
            continue
        med, scale = _scale(hist)
        f = factors[date.fromisoformat(r["d"]).weekday()]
        spread = 2 * (scale or 0)
        out.append([round(max(0.0, (med - spread) * f), 3), round(med * f, 3), round((med + spread) * f, 3)])
    return out


def robust_z(x: float, history: list[float]) -> float | None:
    hist = [h for h in history if h is not None]
    if x is None or len(hist) < 7:
        return None
    med, scale = _scale(hist)
    if not scale:
        return None
    return round((x - med) / scale, 2)


def _sum(rows, key):
    return sum(r.get(key) or 0 for r in rows)


def _ratio(rows, num, den):
    if not any(r.get(num) is not None for r in rows):
        return None  # series missing (e.g. that GDELT call failed), not zero
    d = _sum(rows, den)
    return _sum(rows, num) / d if d else None


def _weighted_tone(rows):
    pairs = [(r["t"], r["n"]) for r in rows if r["t"] is not None and r["n"]]
    w = sum(n for _, n in pairs)
    return sum(t * n for t, n in pairs) / w if w else None


def log_trend(values: list[float]) -> float | None:
    """OLS slope of log(value) on day index, expressed as % change per week."""
    pts = [(i, math.log(v)) for i, v in enumerate(values) if v and v > 0]
    if len(pts) < 10:
        return None
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    if sxx == 0:
        return None
    slope = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx
    return round((math.exp(slope * 7) - 1) * 100, 1)


def percentile_rank(x: float, history: list[float]) -> float | None:
    hist = [h for h in history if h is not None]
    if x is None or not hist:
        return None
    below = sum(1 for h in hist if h < x)
    equal = sum(1 for h in hist if h == x)
    return round(100 * (below + 0.5 * equal) / len(hist), 1)


def _r(x, nd=2):
    return round(x, nd) if x is not None else None


def summarise(rows: list[dict], today: dict | None = None) -> dict:
    """Metrics for the latest complete day. `today` ({"n", "norm", "hours"}) is the
    partial current day, reported for context but never scored."""
    i = latest_index(rows)
    if i is None:
        return {}
    last7 = rows[max(0, i - 6): i + 1]
    prev7 = rows[max(0, i - 13): max(0, i - 6)]
    prev30 = rows[max(0, i - 36): max(0, i - 6)]
    latest = rows[i]

    factors = weekday_factors(rows[: i + 1])
    adj = adjusted_shares(rows[: i + 1], factors)
    v7, p7 = _sum(last7, "n"), _sum(prev7, "n")
    share7 = _ratio(last7, "n", "norm")
    share_prev7 = _ratio(prev7, "n", "norm")
    tone7, tone30 = _weighted_tone(last7), _weighted_tone(prev30)
    viol7, viol30 = _ratio(last7, "v", "n"), _ratio(prev30, "v", "n")
    peace7, peace30 = _ratio(last7, "p", "n"), _ratio(prev30, "p", "n")
    med7, med30 = _ratio(last7, "m", "n"), _ratio(prev30, "m", "n")
    adj30 = adj[max(0, i - 29): i + 1]
    vals30 = [s for s in adj30 if s is not None]
    cv = None
    if len(vals30) > 5:
        m = sum(vals30) / len(vals30)
        sd = math.sqrt(sum((s - m) ** 2 for s in vals30) / (len(vals30) - 1))
        cv = sd / m if m else None
    pc = lambda x: _r(x * 100 if x is not None else None, 1)  # noqa: E731
    t_norm = (today or {}).get("norm")

    return {
        "latest_day": latest["d"],
        "articles_latest": latest["n"],
        "share_latest": latest["s"],
        "z_attention": robust_z(adj[i], adj[max(0, i - 28): i]),
        "attention_pctile_90d": percentile_rank(adj[i], adj[:i]),
        "weekday_adjusted": factors != [1.0] * 7,
        "articles_7d": v7,
        "articles_prev7d": p7,
        "change_7d_pct": _r((v7 / p7 - 1) * 100, 1) if p7 else None,
        "share_7d": _r(share7 * 1e4 if share7 is not None else None, 3),
        "share_change_7d_pct": _r((share7 / share_prev7 - 1) * 100, 1) if share7 and share_prev7 else None,
        "trend_30d_pct_per_week": log_trend(adj30),
        "volatility_30d": _r(cv, 2),
        "tone_7d": _r(tone7),
        "tone_prev30d": _r(tone30),
        "tone_delta": _r(tone7 - tone30) if tone7 is not None and tone30 is not None else None,
        "violence_share_7d": pc(viol7),
        "violence_share_prev30d": pc(viol30),
        "peace_share_7d": pc(peace7),
        "peace_share_prev30d": pc(peace30),
        "mediation_share_7d": pc(med7),
        "mediation_share_prev30d": pc(med30),
        "articles_90d": _sum(rows[: i + 1], "n"),
        "today_articles": today["n"] if today else None,
        "today_share": round(today["n"] / t_norm * 1e4, 3) if t_norm else None,
        "today_hours": today["hours"] if today else None,
    }


def flags(m: dict) -> list[dict]:
    """Plain-language alerts derived from the summary metrics.

    The diplomatic-activity share (CAMEO 'peace' codes) is not flagged: it
    mostly tracks routine meetings and visits, so a rise rarely means a peace
    process moved (Gulf states and Panama score highest).
    """
    out = []
    z = m.get("z_attention")
    if z is not None and z >= 3:
        out.append({"level": "high", "text": "Much more media attention than usual"})
    elif z is not None and z >= 2:
        out.append({"level": "mid", "text": "More media attention than usual"})
    elif z is not None and z <= -2:
        out.append({"level": "low", "text": "Unusually little media attention"})
    td = m.get("tone_delta")
    if td is not None and td <= -1.0:
        out.append({"level": "mid", "text": "Coverage has turned more negative than over the previous month"})
    v7, v30 = m.get("violence_share_7d"), m.get("violence_share_prev30d")
    if v7 is not None and v30 and v7 - v30 >= 5:
        out.append({"level": "mid", "text": f"Violence features more in coverage: {v7:.0f}% of it this week, up from {v30:.0f}%"})
    return out


def week_stats(rows: list[dict], band: list, start: str, end: str) -> dict | None:
    """Figures for one calendar week (complete days between `start` and `end`) and the week before."""
    prev_start = (date.fromisoformat(start) - timedelta(days=7)).isoformat()
    days = [(r, b) for r, b in zip(rows, band) if start <= r["d"] <= end and r["norm"]]
    prev = [r for r in rows if prev_start <= r["d"] < start and r["norm"]]
    if not days:
        return None
    week = [r for r, _ in days]
    share = _ratio(week, "n", "norm")
    share_prev = _ratio(prev, "n", "norm") if prev else None
    viol, viol_prev = _ratio(week, "v", "n"), _ratio(prev, "v", "n") if prev else None
    dipl = _ratio(week, "p", "n")
    busiest = max(week, key=lambda r: r["s"] or 0)
    return {
        "days": len(week),
        "articles": _sum(week, "n"),
        "share": _r(share * 1e4 if share is not None else None, 2),
        "share_prev": _r(share_prev * 1e4 if share_prev is not None else None, 2),
        "change_pct": _r((share / share_prev - 1) * 100, 1) if share and share_prev else None,
        "unusual_days": [r["d"] for r, b in days if b and r["s"] is not None and r["s"] > b[2]],
        "quiet_days": [r["d"] for r, b in days if b and r["s"] is not None and r["s"] < b[0]],
        "busiest_day": busiest["d"],
        "violence": _r(viol * 100 if viol is not None else None, 1),
        "violence_prev": _r(viol_prev * 100 if viol_prev is not None else None, 1),
        "diplomacy": _r(dipl * 100 if dipl is not None else None, 1),
        "tone": _r(_weighted_tone(week)),
    }
