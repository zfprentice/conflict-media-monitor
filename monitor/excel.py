"""Excel workbooks for people who live in spreadsheets: EIP mentions and full history.

Built fresh on every run from the CSV/JSON records, so they are never edited
by hand and never committed (they are binary and would bloat the repository).
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEAD_FILL = PatternFill("solid", fgColor="14202B")
HEAD_FONT = Font(bold=True, color="FFFFFF")
LINK_FONT = Font(color="2340A8", underline="single")


def _table(ws, headers: list[str], rows: list[list], widths: list[int], link_col: int | None = None, links: list | None = None):
    ws.append(headers)
    for c in ws[1]:
        c.fill, c.font = HEAD_FILL, HEAD_FONT
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for i, r in enumerate(rows):
        ws.append(r)
        if link_col is not None and links and links[i]:
            cell = ws.cell(row=i + 2, column=link_col + 1)
            cell.hyperlink, cell.font = links[i], LINK_FONT
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"


def _readme(ws, title: str, lines: list[str]):
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14)
    for i, line in enumerate(lines, start=3):
        ws.cell(row=i, column=1, value=line).alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 110


def write_mentions(path: Path, label: str, rows: list[dict], generated: str, since: str):
    wb = Workbook()
    ws = wb.active
    ws.title = "Mentions"
    _table(
        ws,
        ["Published (UTC)", "Headline (click to open)", "Outlet", "Language", "Countries named in headline",
         "Relevant? (your call)", "Notes", "First recorded"],
        [[r["published"], r["title"], r["outlet"], r["language"], r["countries"], "", "", r["found"]] for r in rows],
        [17, 80, 26, 11, 24, 14, 30, 17], link_col=1, links=[r["link"] for r in rows],
    )
    by_month = Counter((r["published"] or r["found"])[:7] for r in rows)
    by_lang = Counter(r["language"] for r in rows)
    ms = wb.create_sheet("By month")
    months = sorted(by_month, reverse=True)
    _table(ms, ["Month", "Mentions"] + sorted(by_lang),
           [[m, by_month[m]] + [sum(1 for r in rows if (r["published"] or r["found"])[:7] == m and r["language"] == lg)
                                for lg in sorted(by_lang)] for m in months],
           [12, 11] + [11] * len(by_lang))
    rd = wb.create_sheet("Read me")
    _readme(rd, f"{label}: media mentions", [
        f"Every Google News article that mentions the {label}, collected automatically by the Conflict Media Monitor.",
        f"Searched in English, French, German, Spanish and Arabic Google News. Articles published from {since} onwards; "
        "new ones are added every few hours. Last updated " + generated + " (UTC).",
        "Google News matches the name anywhere in the article, so the headline often won't mention it. Open the link to "
        "check context before citing, and use the 'Relevant?' and 'Notes' columns for your own review.",
        "Google News does not index every outlet (paywalled, broadcast and many local outlets are missing), so treat counts "
        "as a floor, not a full census. The same story syndicated by several outlets appears once per outlet.",
        "This file is rebuilt on every update, so copy rows into your own workbook before adding notes you want to keep.",
    ])
    wb.save(path)


def write_history(path: Path, countries: list[dict], weekly: list[dict], generated: str):
    """`countries`: [{name, region, tier, series: [daily rows]}]; `weekly`: [{week, start, country, ...}]."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Daily by country"
    rows = []
    for c in countries:
        for r in c["series"]:
            n = r.get("n") or 0
            pct = lambda k: round(100 * r[k] / n, 1) if n and r.get(k) is not None else None  # noqa: E731
            band = r.get("b") or [None, None, None]
            rows.append([r["d"], c["name"], c["region"], c["tier_label"], n, r.get("s"), band[1], band[2],
                         "yes" if band[2] is not None and r.get("s") is not None and r["s"] > band[2] else "",
                         r.get("t"), pct("v"), pct("p")])
    rows.sort(key=lambda x: (x[0], x[1]), reverse=True)
    _table(ws, ["Date", "Country", "Region", "Group", "Article mentions", "Share of world news (per 10,000)",
                "Usual share (median)", "Top of usual range", "Unusually high?", "Tone (GDELT)", "Violence in coverage (%)",
                "Diplomatic activity in coverage (%)"], rows, [11, 20, 22, 18, 14, 16, 13, 13, 11, 11, 14, 16])
    wk = wb.create_sheet("Weekly summary")
    _table(wk, ["Week", "Starts", "Country", "Summary", "Share of world news (per 10,000)", "Change vs week before (%)",
                "Days of unusual attention", "Violence in coverage (%)", "Main story", "Outlets carrying it"],
           [[w["week"], w["start"], w["country"], w["summary"], w["share"], w["change_pct"], w["unusual_days"],
             w["violence"], w["story"], w["outlets"]] for w in weekly],
           [10, 11, 20, 70, 14, 13, 12, 12, 70, 10], link_col=8, links=[w.get("story_url") for w in weekly])
    rd = wb.create_sheet("Read me")
    _readme(rd, "Conflict Media Monitor: coverage history", [
        "Daily media coverage for each tracked country since the monitor started, built from GDELT's machine-coded "
        "world news (English plus about 65 translated languages). Last updated " + generated + " (UTC).",
        "Article mentions: how many articles reported events in or involving the country that day. Share of world news: "
        "the same as a proportion of everything GDELT coded worldwide that day, per 10,000, so days stay comparable "
        "when overall news volume swings.",
        "Usual share and top of usual range: the country's typical level over the previous four weeks, adjusted for day "
        "of week. Days above the top of the range are marked 'Unusually high'.",
        "Violence in coverage: share of coverage about assaults, armed clashes or mass violence. Diplomatic activity: "
        "share about meetings, appeals, negotiations, mediation, agreements and ceasefires. Both are machine-coded and "
        "the diplomatic measure is dominated by routine meetings, so read them as rough signals.",
        "Weekly summary: one row per country per week, with the main story from Google News where it was collected.",
    ])
    wb.save(path)
