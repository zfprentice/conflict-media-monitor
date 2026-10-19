"""Pure metric computations on daily GDELT series. No network, fully testable."""
from __future__ import annotations

import math
from statistics import median


def merge_daily(vol: dict, tone: dict, viol: dict, peace: dict) -> list[dict]:
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
        })
    return rows


def latest_index(rows: list[dict], min_frac: float = 0.3) -> int | None:
    """Index of the most recent day with enough monitored volume to be meaningful.

    Today's bucket is usually partial; once GDELT has seen >=30% of a normal
    day's articles the *share* is already a fair estimate, so we keep it.
    """
    norms = [r["norm"] for r in rows if r["norm"]]
    if not norms:
        return None
    floor = min_frac * median(norms[-30:])
    for i in range(len(rows) - 1, -1, -1):
        if rows[i]["norm"] and rows[i]["norm"] >= floor:
            return i
    return None


def robust_z(x: float, history: list[float]) -> float | None:
    hist = [h for h in history if h is not None]
    if x is None or len(hist) < 7:
        return None
    med = median(hist)
    mad = median([abs(h - med) for h in hist])
    scale = 1.4826 * mad
    if scale < 1e-9:
        mean = sum(hist) / len(hist)
        sd = math.sqrt(sum((h - mean) ** 2 for h in hist) / max(len(hist) - 1, 1))
        scale = sd if sd > 1e-9 else None
    if not scale:
        return None
    return round((x - med) / scale, 2)


def _sum(rows, key):
    return sum(r[key] or 0 for r in rows)


def _ratio(rows, num, den):
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


def summarise(rows: list[dict]) -> dict:
    i = latest_index(rows)
    if i is None:
        return {}
    last7 = rows[max(0, i - 6): i + 1]
    prev7 = rows[max(0, i - 13): max(0, i - 6)]
    prev30 = rows[max(0, i - 36): max(0, i - 6)]
    base28 = rows[max(0, i - 28): i]
    last30 = rows[max(0, i - 29): i + 1]
    latest = rows[i]

    v7, p7 = _sum(last7, "n"), _sum(prev7, "n")
    share7 = _ratio(last7, "n", "norm")
    share_prev7 = _ratio(prev7, "n", "norm")
    tone7, tone30 = _weighted_tone(last7), _weighted_tone(prev30)
    viol7, viol30 = _ratio(last7, "v", "n"), _ratio(prev30, "v", "n")
    peace7, peace30 = _ratio(last7, "p", "n"), _ratio(prev30, "p", "n")
    shares30 = [r["s"] for r in last30]
    mean30 = [s for s in shares30 if s is not None]
    cv = None
    if len(mean30) > 5:
        m = sum(mean30) / len(mean30)
        sd = math.sqrt(sum((s - m) ** 2 for s in mean30) / (len(mean30) - 1))
        cv = sd / m if m else None

    return {
        "latest_day": latest["d"],
        "latest_partial": i == len(rows) - 1,
        "articles_latest": latest["n"],
        "share_latest": latest["s"],
        "z_attention": robust_z(latest["s"], [r["s"] for r in base28]),
        "attention_pctile_90d": percentile_rank(latest["s"], [r["s"] for r in rows[: i]]),
        "articles_7d": v7,
        "articles_prev7d": p7,
        "change_7d_pct": _r((v7 / p7 - 1) * 100, 1) if p7 else None,
        "share_7d": _r(share7 * 1e4 if share7 is not None else None, 3),
        "share_change_7d_pct": _r((share7 / share_prev7 - 1) * 100, 1) if share7 and share_prev7 else None,
        "trend_30d_pct_per_week": log_trend(shares30),
        "volatility_30d": _r(cv, 2),
        "tone_7d": _r(tone7),
        "tone_prev30d": _r(tone30),
        "tone_delta": _r(tone7 - tone30) if tone7 is not None and tone30 is not None else None,
        "violence_share_7d": _r(viol7 * 100 if viol7 is not None else None, 1),
        "violence_share_prev30d": _r(viol30 * 100 if viol30 is not None else None, 1),
        "peace_share_7d": _r(peace7 * 100 if peace7 is not None else None, 1),
        "peace_share_prev30d": _r(peace30 * 100 if peace30 is not None else None, 1),
        "articles_90d": _sum(rows[: i + 1], "n"),
    }


def flags(m: dict) -> list[dict]:
    """Plain-language alerts derived from the summary metrics."""
    out = []
    z = m.get("z_attention")
    if z is not None and z >= 3:
        out.append({"level": "high", "text": f"Coverage spike: {z:+.1f} robust z vs 28-day baseline"})
    elif z is not None and z >= 2:
        out.append({"level": "mid", "text": f"Coverage rising: {z:+.1f} robust z vs 28-day baseline"})
    elif z is not None and z <= -2:
        out.append({"level": "low", "text": f"Unusually quiet: {z:+.1f} robust z"})
    td = m.get("tone_delta")
    if td is not None and td <= -1.0:
        out.append({"level": "mid", "text": f"Tone darkening: {td:+.2f} vs prior 30 days"})
    v7, v30 = m.get("violence_share_7d"), m.get("violence_share_prev30d")
    if v7 is not None and v30 and v7 - v30 >= 8:
        out.append({"level": "mid", "text": f"Violence framing up {v7 - v30:.0f} pts ({v30:.0f}% → {v7:.0f}%)"})
    p7, p30 = m.get("peace_share_7d"), m.get("peace_share_prev30d")
    if p7 is not None and p30 is not None and p7 - p30 >= 6:
        out.append({"level": "info", "text": f"Peace-process framing up {p7 - p30:.0f} pts ({p30:.0f}% → {p7:.0f}%)"})
    return out
