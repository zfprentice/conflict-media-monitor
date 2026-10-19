import json
from datetime import datetime, timezone
from pathlib import Path

from monitor import events, gnews
from monitor.metrics import flags, latest_index, log_trend, merge_daily, percentile_rank, robust_z, summarise

FX = Path(__file__).parent / "fixtures"
CFG = json.loads((Path(__file__).parent.parent / "config" / "countries.json").read_text())


def synthetic_rows(spike=True, framing=True):
    """92 days: steady ~30 per 10k, last 3 days 90 per 10k; today partial (60% volume)."""
    vol, tone, viol = {}, {}, {}
    for i in range(92):
        d = f"2026-{7 + (19 + i) // 31:02d}-{(19 + i) % 31 + 1:02d}"
        norm = 100000 + (i * 37 % 7) * 1000
        base = 300 + (i * 13 % 9)
        if spike and i >= 89:
            base = 900
        if i == 91:
            norm, base = 60000, (540 if spike else 180)
        vol[d] = {"count": base, "norm": norm}
        tone[d] = -3.0 - (1.5 if spike and i >= 85 else 0)
        viol[d] = {"count": int(base * (0.5 if spike and i >= 85 else 0.3))}
    return merge_daily(vol, tone if framing else {}, viol if framing else {}, {})


# ---------------- metrics
def test_partial_today_is_kept_when_volume_sufficient():
    r = synthetic_rows()
    assert latest_index(r) == len(r) - 1


def test_spike_detected_with_share_not_raw_count():
    m = summarise(synthetic_rows())
    assert m["share_latest"] == 90.0 and m["z_attention"] > 5 and m["latest_partial"] is True
    assert m["violence_share_7d"] > m["violence_share_prev30d"] and m["tone_delta"] < -1
    texts = " ".join(f["text"] for f in flags(m))
    assert "spike" in texts and "Tone darkening" in texts and "Violent-event coverage up" in texts


def test_missing_series_is_none_not_zero():
    m = summarise(synthetic_rows(framing=False))
    assert m["violence_share_7d"] is None and m["peace_share_7d"] is None and m["tone_7d"] is None


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
    arts = {k: [] for k in ("SDN", "SAU", "PSE")}
    from collections import defaultdict
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
    assert len(arts["SDN"]) == 2 and arts["SDN"][0][0] == 5


def test_daily_roundtrip(tmp_path):
    from collections import defaultdict
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
    assert len(gnews.parse_rss((FX / "gnews.xml").read_text(), limit=1)) == 1


# ---------------- config
def test_config_is_valid():
    cs = CFG["countries"]
    assert len(cs) == len({c["iso3"] for c in cs})
    for c in cs:
        assert {"iso3", "name", "region", "tier", "atlas", "news", "fips", "cameo"} <= c.keys()
        assert c["tier"] in {"operates", "dialogue"} and c["fips"]
        assert all(len(f) == 2 for f in c["fips"]) and all(len(k) == 3 for k in c["cameo"])
