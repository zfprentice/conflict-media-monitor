import json
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import build_data
from monitor import events, gnews
from monitor.metrics import (baseline_band, flags, latest_index, log_trend, merge_daily, percentile_rank, robust_z,
                             summarise, weekday_factors)

FX = Path(__file__).parent / "fixtures"
CFG = json.loads((Path(__file__).parent.parent / "config" / "countries.json").read_text())
START = date(2026, 7, 20)  # a Monday


def synthetic_rows(spike=True, framing=True, weekend=1.0, days=91):
    """Complete days: steady ~30 per 10k (x `weekend` on Sat/Sun), last 3 days 90 per 10k if spiking."""
    vol, tone, viol, med = {}, {}, {}, {}
    for i in range(days):
        day = START + timedelta(days=i)
        d = day.isoformat()
        norm = 100000 + (i * 37 % 7) * 1000
        noise = 1 + ((i * 7919) % 23 - 11) / 110  # deterministic +/-10% day-to-day wobble
        base = 300 * noise * (weekend if day.weekday() >= 5 else 1)
        if spike and i >= days - 3:
            base = 900
        vol[d] = {"count": round(base * norm / 1e5), "norm": norm}  # share ~ base / 10
        tone[d] = -3.0 - (1.5 if spike and i >= days - 7 else 0)
        viol[d] = {"count": int(base * (0.5 if spike and i >= days - 7 else 0.3))}
        med[d] = {"count": int(base * (0.06 if spike and i >= days - 7 else 0.02))}
    return merge_daily(vol, tone if framing else {}, viol if framing else {}, {}, med if framing else None)


# ---------------- metrics
def test_spike_detected_with_share_not_raw_count():
    m = summarise(synthetic_rows())
    assert m["share_latest"] == 90.0 and m["z_attention"] > 5
    assert m["violence_share_7d"] > m["violence_share_prev30d"] and m["tone_delta"] < -1
    texts = " ".join(f["text"] for f in flags(m))
    assert "spike" in texts and "Tone darkening" in texts and "Violent-event coverage up" in texts
    assert "Mediation coverage up" in texts


def test_steady_series_is_not_flagged():
    m = summarise(synthetic_rows(spike=False))
    assert abs(m["change_7d_pct"]) < 3 and abs(m["z_attention"]) < 2 and not flags(m)


def test_weekday_rhythm_is_not_an_anomaly():
    rows = synthetic_rows(spike=False, weekend=0.6)  # 91 days from a Monday: ends on a Sunday
    assert date.fromisoformat(rows[-1]["d"]).weekday() == 6
    f = weekday_factors(rows)
    assert abs(f[6] / f[2] - 0.6) < 0.05
    m = summarise(rows)
    assert m["weekday_adjusted"] and abs(m["z_attention"]) < 2
    assert robust_z(rows[-1]["s"], [r["s"] for r in rows[-29:-1]]) < -0.5  # unadjusted reads Sunday as quiet
    band = baseline_band(rows, f)
    assert band[-1][2] < band[-3][1]  # Sunday's expected range sits below a Friday's median
    assert summarise(synthetic_rows(weekend=0.6))["z_attention"] > 5  # real spikes still show


def test_weekday_factors_need_history():
    assert weekday_factors(synthetic_rows(spike=False, weekend=0.5, days=14)) == [1.0] * 7


def test_today_is_reported_not_scored():
    m = summarise(synthetic_rows(spike=False), today={"n": 400, "norm": 40000, "hours": 8.5})
    assert m["today_share"] == 100.0 and m["today_hours"] == 8.5 and abs(m["z_attention"]) < 2


def test_country_rows_use_complete_days_only():
    agg = defaultdict(lambda: defaultdict(float))
    for d, slots in (("2026-10-18", 96), ("2026-10-19", 91), ("2026-10-20", 34)):
        agg[(d, events.ALL)].update(slots=slots, articles=1000)
        agg[(d, "SDN")].update(articles=10, med=2)
    rows = build_data.country_rows(agg, "SDN", ["2026-10-18", "2026-10-19", "2026-10-20"])
    assert [r["d"] for r in rows] == ["2026-10-18", "2026-10-19"] and rows[-1]["m"] == 2
    assert build_data.today_so_far(agg, "SDN", "2026-10-20") == {"n": 10, "norm": 1000, "hours": 8.5}
    assert build_data.today_so_far(agg, "SDN", "2026-10-19") is None
    assert latest_index(rows) == 1


def test_missing_series_is_none_not_zero():
    m = summarise(synthetic_rows(framing=False))
    assert m["violence_share_7d"] is None and m["peace_share_7d"] is None and m["tone_7d"] is None
    assert m["mediation_share_7d"] is None


def test_empty_is_safe():
    assert summarise([]) == {}


def test_robust_z_trend_percentile():
    assert robust_z(5, [5] * 20) is None
    assert robust_z(10, [1, 2, 3]) is None
    assert robust_z(10, [1, 2, 3, 4, 5, 6, 7, 8]) == 1.85  # median 4.5, MAD 2 -> scale 2.965
    assert log_trend([100 * 1.1 ** (i / 7) for i in range(30)]) == 10.0
    assert percentile_rank(5, [1, 2, 3, 4]) == 100.0


# ---------------- GDELT event files
def test_parse_export_assigns_events_to_countries():
    fips, cameo = events.build_index(CFG["countries"])
    agg = events.load_daily(Path("/nonexistent"))
    arts = defaultdict(list)
    events.parse_export((FX / "export_sample.csv").read_text(), "20261018101500", fips, cameo, agg, arts)
    g = agg[("2026-10-18", events.ALL)]
    assert g["events"] == 4 and g["articles"] == 20  # malformed line skipped
    sdn = agg[("2026-10-18", "SDN")]
    assert sdn["events"] == 2 and sdn["articles"] == 8
    assert sdn["viol"] == 5 and sdn["peace"] == 3 and sdn["r19"] == 5 and sdn["r04"] == 3
    assert abs(sdn["tone_w"] - (-6.5 * 5 + 1.0 * 3)) < 1e-9
    assert agg[("2026-10-18", "SAU")]["articles"] == 3  # located in Saudi Arabia
    assert agg[("2026-10-18", "PSE")]["viol"] == 2  # Gaza FIPS GZ -> Palestine
    assert ("2026-10-18", "USA") not in agg
    # stories only from events located in the country (event 2 is in Saudi Arabia)
    assert [a[0] for a in arts["SDN"]] == [5] and [a[0] for a in arts["SAU"]] == [3]


def test_mediation_and_peace_codes():
    fips, cameo = events.build_index(CFG["countries"])
    agg = events.load_daily(Path("/nonexistent"))
    for base, n in (("039", 4), ("037", 2), ("042", 9)):  # offer to mediate, intent to settle, visit
        f = [""] * 61
        f[7], f[26], f[27], f[28], f[33], f[34], f[53] = "SDN", base, base, base[:2], str(n), "0", "SU"
        events.parse_export("\t".join(f), "20261018101500", fips, cameo, agg, None)
    sdn = agg[("2026-10-18", "SDN")]
    assert sdn["peace"] == 6 and sdn["med"] == 4 and sdn["articles"] == 15


def test_old_state_is_detected(tmp_path):
    old = tmp_path / "d.csv"
    old.write_text("date,key,slots,events,articles,tone_w,viol,peace,r01\n")
    assert not events.state_is_current(old)
    assert events.state_is_current(tmp_path / "missing.csv")
    events.save_daily(tmp_path / "new.csv", defaultdict(lambda: defaultdict(float)), "2026-01-01")
    assert events.state_is_current(tmp_path / "new.csv")


def test_recent_missing_files_are_retried():
    cut = "20261020060000"
    assert not events.slot_settled([("export", "x"), ("translation.export", None)], "20261020080000", cut)
    assert events.slot_settled([("export", None), ("translation.export", None)], "20261019080000", cut)
    assert events.slot_settled([("export", "x"), ("translation.export", "y")], "20261020080000", cut)


def test_daily_roundtrip(tmp_path):
    agg = defaultdict(lambda: defaultdict(float))
    agg[("2026-10-18", "SDN")]["articles"] = 8
    agg[("2026-10-18", "SDN")]["tone_w"] = -29.5
    agg[("2026-06-01", "SDN")]["articles"] = 1
    events.save_daily(tmp_path / "d.csv", agg, keep_from="2026-07-01")
    back = events.load_daily(tmp_path / "d.csv")
    assert back[("2026-10-18", "SDN")]["articles"] == 8 and back[("2026-10-18", "SDN")]["tone_w"] == -29.5
    assert ("2026-06-01", "SDN") not in back  # pruned outside the window


def test_slots_and_titles():
    s = events.slots_between(datetime(2026, 10, 18, 23, 0, tzinfo=timezone.utc), datetime(2026, 10, 19, 0, 7, tzinfo=timezone.utc))
    assert s == ["20261019000000", "20261018234500", "20261018233000", "20261018231500", "20261018230000"]
    assert events.slot_day(s[0]) == "2026-10-19"
    assert events.title_from_url("https://news.example.com/2026/10/18/sudan-rsf-shell-el-fasher-market-12345.html") == "Sudan rsf shell el fasher market"
    assert events.title_from_url("https://x.example.org/article/123456") == ""
    assert events.domain_of("https://www.bbc.co.uk/news/x") == "bbc.co.uk"


def test_merge_articles_dedupes_and_prunes():
    now = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    old = {"SDN": [{"url": "u1", "mentions": 3, "slot": "20261019000000", "root": "19"},
                   {"url": "old", "mentions": 99, "slot": "20261010000000", "root": "19"}]}
    new = {"SDN": [(7, "u1", "20261019110000", "19"), (5, "u2", "20261019110000", "04")]}
    out = events.merge_articles(old, new, now)
    assert [a["url"] for a in out["SDN"]] == ["u1", "u2"] and out["SDN"][0]["mentions"] == 7


# ---------------- Google News
def test_google_news_parse_strips_publisher_and_sorts():
    items = gnews.parse_rss((FX / "gnews.xml").read_text())
    assert items[0]["title"] == "Envoy visits region" and items[0]["source"] == "BBC"
    assert items[1]["title"] == "Talks in Doha stall"
    assert gnews.parse_rss("not xml") == []
    t = time.time()
    assert gnews.fetch("anything", deadline=t - 1) is None and time.time() - t < 1  # out of budget: no network call
    assert len(gnews.parse_rss((FX / "gnews.xml").read_text(), limit=1)) == 1


# ---------------- config
def test_config_is_valid():
    cs = CFG["countries"]
    assert len(cs) == len({c["iso3"] for c in cs})
    for c in cs:
        assert {"iso3", "name", "region", "tier", "atlas", "news", "fips", "cameo"} <= c.keys()
        assert c["tier"] in {"operates", "dialogue"} and c["fips"]
        assert all(len(f) == 2 for f in c["fips"]) and all(len(k) == 3 for k in c["cameo"])
