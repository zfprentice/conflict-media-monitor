"""Plain-language sentences from the metrics, for readers who don't work with z-scores.

The same wording appears on the page, in the weekly report and in the Excel
files, so it lives here rather than in the front end.
"""
from __future__ import annotations

from datetime import date

from monitor.stories import THEME_LABELS

LEVELS = [  # (lower bound of robust z, key, label)
    (3, "much_higher", "Much more attention than usual"),
    (2, "higher", "More attention than usual"),
    (1, "bit_higher", "A little more attention than usual"),
    (-1, "usual", "Usual level of attention"),
    (-2, "bit_lower", "A little less attention than usual"),
    (float("-inf"), "lower", "Unusually little attention"),
]


def attention(z: float | None) -> dict:
    if z is None:
        return {"key": "unknown", "label": "Not enough history yet"}
    for lo, key, label in LEVELS:
        if z >= lo:
            return {"key": key, "label": label}
    return {"key": "lower", "label": LEVELS[-1][2]}


def day_label(d: str) -> str:
    x = date.fromisoformat(d)
    return f"{x.strftime('%a')} {x.day} {x.strftime('%b')}"


def change_words(pct: float | None, small: float = 10) -> str | None:
    if pct is None:
        return None
    if abs(pct) < small:
        return "about the same as"
    return f"{'up' if pct > 0 else 'down'} {abs(pct):.0f}% on"


def theme_shares(themes: dict, n: int) -> list[tuple[str, int]]:
    """[(theme key, % of headlines)], biggest first, only themes present."""
    if not n:
        return []
    return sorted(((k, round(100 * v / n)) for k, v in themes.items() if v), key=lambda kv: -kv[1])


def themes_sentence(themes: dict, n: int, past: bool = False) -> str | None:
    top = [kv for kv in theme_shares(themes, n) if kv[1] >= 15][:2]
    if n < 5 or not top:
        return None
    parts = [f"{THEME_LABELS[k].lower()} ({p}%)" for k, p in top]
    verb = "were" if past else "are"
    if top[0][1] >= 50:
        return f"Headlines {verb} mostly about {parts[0]}" + (f", followed by {parts[1]}" if len(parts) > 1 else "") + "."
    return f"The most common topics in headlines {verb} {' and '.join(parts)}."


def country_summary(name: str, m: dict, recent: dict | None = None) -> list[str]:
    """Two or three sentences on where a country stands now."""
    if not m:
        return [f"There isn't enough coverage history for {name} yet."]
    out = []
    a = attention(m.get("z_attention"))
    s = f"{a['label']} on {day_label(m['latest_day'])}"
    pc = m.get("attention_pctile_90d")
    if pc is not None and pc >= 97 and (m.get("z_attention") or 0) >= 1:
        s += ", one of the busiest days for coverage of " + name + " in three months"
    elif pc is not None and pc <= 3 and (m.get("z_attention") or 0) <= -1:
        s += ", one of the quietest days in three months"
    out.append(s + ".")
    cw = change_words(m.get("share_change_7d_pct"))
    if cw:
        out.append(f"Over the past week its share of world news is {cw} the week before.")
    if recent:
        t = themes_sentence(recent.get("themes", {}), recent.get("n", 0))
        if t:
            out.append(t)
    v7, v30 = m.get("violence_share_7d"), m.get("violence_share_prev30d")
    if v7 is not None and v30 and v7 - v30 >= 5:
        out.append(f"Violence features more than usual ({v7:.0f}% of coverage, up from {v30:.0f}%).")
    td = m.get("tone_delta")
    if td is not None and td <= -1:
        out.append("The tone of coverage has turned noticeably more negative.")
    return out


def week_summary(name: str, wk: dict | None, themes: dict | None = None, n: int = 0,
                 prev_themes: dict | None = None, prev_n: int = 0) -> list[str]:
    """Sentences for one country in the weekly report."""
    out = []
    if wk:
        u = wk["unusual_days"]
        if u:
            days = ", ".join(day_label(d) for d in u)
            out.append(f"{name} got unusually high attention on {len(u)} {'day' if len(u) == 1 else 'days'} ({days}).")
        elif wk["quiet_days"] and len(wk["quiet_days"]) >= 3:
            out.append(f"Coverage of {name} was unusually low on {len(wk['quiet_days'])} days.")
        else:
            out.append(f"Attention to {name} stayed within its usual range.")
        cw = change_words(wk.get("change_pct"))
        if cw:
            out.append(f"Its share of world news was {cw} the week before.")
        v, vp = wk.get("violence"), wk.get("violence_prev")
        if v is not None and vp is not None and abs(v - vp) >= 5:
            out.append(f"Violence made up {v:.0f}% of coverage, {'up' if v > vp else 'down'} from {vp:.0f}%.")
    t = themes_sentence(themes or {}, n, past=True)
    if t:
        out.append(t)
    if themes and prev_themes and n >= 10 and prev_n >= 10:
        now, before = dict(theme_shares(themes, n)), dict(theme_shares(prev_themes, prev_n))
        moves = sorted(((k, now.get(k, 0) - before.get(k, 0)) for k in THEME_LABELS), key=lambda kv: -abs(kv[1]))
        k, d = moves[0]
        if abs(d) >= 15:
            out.append(f"{THEME_LABELS[k]} featured {'much more' if d > 0 else 'much less'} than the week before "
                       f"({before.get(k, 0)}% → {now.get(k, 0)}% of headlines).")
    return out
