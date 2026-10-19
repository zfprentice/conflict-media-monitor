import json
from pathlib import Path

from monitor import gdelt, gnews
from monitor.metrics import flags, latest_index, merge_daily, robust_z, summarise, log_trend, percentile_rank

FX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FX / name).read_text())


def rows():
    vol = gdelt.parse_timeline_volraw(load("volraw.json"))
    tone = gdelt.parse_timeline_tone(load("tone.json"))
    viol = gdelt.parse_timeline_volraw(load("viol.json"))
    return merge_daily(vol, tone, viol, {})


def test_volraw_daily_buckets():
    vol = gdelt.parse_timeline_volraw(load("volraw.json"))
    assert len(vol) == 92
    first = next(iter(vol))
    assert first == "2026-07-20"
    assert vol[first]["norm"] > 90000


def test_empty_payloads_are_safe():
    assert gdelt.parse_timeline_volraw({}) == {}
    assert gdelt.parse_timeline_tone(None) == {}
    assert gdelt.parse_artlist(None)["articles"] == []
    assert summarise([]) == {}


def test_artlist_dedupes_titles_and_counts_outlets():
    out = gdelt.parse_artlist(load("artlist.json"))
    assert [a["title"] for a in out["articles"]] == ["Ceasefire talks resume", "Aid convoy reaches city"]
    assert out["top_domains"][0] == ("b.example", 2)
    assert out["articles"][0]["seen"].startswith("2026-10-18T10:15")


def test_partial_today_is_kept_when_volume_sufficient():
    r = rows()
    assert latest_index(r) == len(r) - 1  # 60% of a normal day -> keep


def test_spike_detected_with_share_not_raw_count():
    m = summarise(rows())
    # partial day: 540 / 60000 = 90 per 10k, baseline ~30 -> large positive z
    assert m["share_latest"] == 90.0
    assert m["z_attention"] > 5
    assert m["latest_partial"] is True
    assert m["violence_share_7d"] > m["violence_share_prev30d"]
    assert m["tone_delta"] < -1
    texts = " ".join(f["text"] for f in flags(m))
    assert "spike" in texts and "Tone darkening" in texts and "Violence framing" in texts


def test_robust_z_handles_flat_history():
    assert robust_z(5, [5] * 20) is None
    assert robust_z(10, [1, 2, 3]) is None  # too short
    # median 4.5, MAD 2 -> scale 2.965; (10 - 4.5) / 2.965 = 1.85
    assert robust_z(10, [1, 2, 3, 4, 5, 6, 7, 8]) == 1.85


def test_trend_and_percentile():
    assert log_trend([100 * 1.1 ** (i / 7) for i in range(30)]) == 10.0
    assert percentile_rank(5, [1, 2, 3, 4]) == 100.0


def test_google_news_parse_strips_publisher_and_sorts():
    items = gnews.parse_rss((FX / "gnews.xml").read_text())
    assert items[0]["title"] == "Envoy visits region"
    assert items[0]["source"] == "BBC"
    assert items[1]["title"] == "Talks in Doha stall"
    assert gnews.parse_rss("not xml") == []


def test_config_is_valid():
    cfg = json.loads((Path(__file__).parent.parent / "config" / "countries.json").read_text())
    cs = cfg["countries"]
    assert len(cs) == len({c["iso3"] for c in cs})
    for c in cs:
        assert {"iso3", "name", "region", "tier", "atlas", "gdelt", "news"} <= c.keys()
        assert c["tier"] in {"operates", "dialogue"}
        # GDELT rejects OR lists that are not wrapped in parentheses
        if " OR " in c["gdelt"]:
            assert c["gdelt"].startswith("(") and c["gdelt"].endswith(")")


def test_url_builder():
    u = gdelt.build_url('(Sudan OR "Rapid Support Forces")', "timelinevolraw")
    assert "mode=timelinevolraw" in u and "format=json" in u and "Rapid+Support" in u


def test_missing_framing_series_is_none_not_zero():
    vol = gdelt.parse_timeline_volraw(load("volraw.json"))
    m = summarise(merge_daily(vol, {}, {}, {}))
    assert m["violence_share_7d"] is None and m["peace_share_7d"] is None
    assert m["tone_7d"] is None
    assert m["share_latest"] == 90.0


def test_merge_keeps_old_metrics_when_gdelt_fails():
    import build_data
    old = {"iso3": "SDN", "metrics": {"z_attention": 1}, "series": [1], "headlines": [{"title": "old"}], "fetched_at": "x"}
    rec = build_data.merge(old, {"iso3": "SDN", "name": "Sudan"}, {"headlines": [{"title": "new"}]})
    assert rec["stale"] is True and rec["pending"] is False
    assert rec["metrics"] == {"z_attention": 1} and rec["headlines"][0]["title"] == "new"
    rec = build_data.merge(None, {"iso3": "SDN"}, {"headlines": None})
    assert rec["pending"] is True and rec["stale"] is False
