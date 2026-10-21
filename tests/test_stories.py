import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from monitor import archive, gnews, narrative
from monitor import stories as st

CFG = json.loads((Path(__file__).parent.parent / "config" / "countries.json").read_text())
C = {c["iso3"]: c for c in CFG["countries"]}


def h(title, source="Reuters", published="2026-10-20T10:00:00+00:00", url=None):
    return {"title": title, "source": source, "published": published, "url": url or "https://x/" + title[:20]}


# ---------------- relevance and noise
def test_headline_must_name_the_country():
    sdn, lbn, pse = st.Matcher(C["SDN"]), st.Matcher(C["LBN"]), st.Matcher(C["PSE"])
    assert sdn.mentions("At least 153 killed in drone strike as Sudan's war spills over")
    assert sdn.mentions("RSF shells El Fasher")
    assert not sdn.mentions("Korea expands farm technology support for war-scarred South Sudan")
    assert sdn.mentions("Sudan and South Sudan trade blame over Abyei")  # Sudan named in its own right
    assert not lbn.mentions("LeBron, Sixers spoil Knicks' ring night")
    assert not lbn.mentions("Lebanon Valley College falls in overtime")
    assert pse.mentions("Voting for survival: Palestinians under Israeli rule")  # plural
    assert st.Matcher(C["TUR"]).mentions("Erdoğan meets Türkiye's opposition")  # accents folded


def test_noise_is_dropped():
    assert st.is_noise("Light mag. 3.5 earthquake - Panama-Costa Rica Border Region")
    assert st.is_noise("LeBron, Sixers spoil Knicks' ring night as NBA season opens")
    assert st.is_noise("Hot, humid day ahead with chance of drizzle")
    assert st.is_noise("Colombia stocks higher at close of trade", "Investing.com UK")
    assert st.is_noise("Anything at all", "Volcano Discovery")
    assert not st.is_noise("Drone strike on Abyei market kills 150")
    assert not st.is_noise("Gunmen attack coach carrying pilgrims in Iraq")


def test_gdelt_slug_titles_kept_only_when_readable():
    assert st.readable_slug_title("More than people feared killed in sudan drone attack on market", "x.com")
    assert not st.readable_slug_title("Notio soudan dekades nekroi apo soudanika drone se agora", "skai.gr")
    assert not st.readable_slug_title("Article 16c6 aac6", "x.com")
    assert not st.readable_slug_title("english.news.cn", "english.news.cn")


# ---------------- stories, themes, names
def test_same_event_is_one_story_ranked_by_outlets():
    items = [
        h("Drone strike on Abyei market near Sudan-South Sudan border kills 150", "Al Jazeera"),
        h("Sudanese drone attack kills more than 150 people in Abyei market, official says", "Business Standard"),
        h("At least 153 killed in drone strike on disputed Abyei market as Sudan's war spills over", "Daily Pioneer"),
        h("Sudan gold miners found 'in pieces' after Egypt border airstrike", "Jacaranda FM"),
        h("Sudan's army chief meets envoy in Port Sudan on ceasefire proposal", "AFP"),
    ]
    out = st.analyse(items, st.ignore_words(C["SDN"]))
    top = out["stories"][0]
    assert top["outlets"] == 3 and "Abyei" in top["title"] and len(top["also"]) == 2
    assert top["source"] == "Al Jazeera"  # recognised outlet preferred as the representative
    assert len(out["stories"]) == 3
    assert out["themes"]["violence"] == 5 and out["themes"]["diplomacy"] == 1  # "army chief" counts as security
    assert out["n"] == 5


def test_themes_and_names():
    assert st.themes_of("UN envoy pushes ceasefire talks in Doha") == ["diplomacy"]
    assert "humanitarian" in st.themes_of("Cholera outbreak spreads in displacement camps")
    assert "economy" not in st.themes_of("Settlers attack village in the West Bank")
    items = [h("Talks stall as Hemedti rejects the plan"), h("Pressure grows on Hemedti after market attack"),
             h("Sudan Army Drone Strike Kills 153 In Market")]  # title case: skipped for names
    assert st.names(items, st.ignore_words(C["SDN"])) == [["Hemedti", 2]]


def test_dedupe_same_headline_same_outlet():
    assert len(st.dedupe([h("A b c"), h("A b c"), h("A b c", "BBC")])) == 2


# ---------------- plain language
def test_attention_levels_and_summary():
    assert narrative.attention(3.4)["key"] == "much_higher" and narrative.attention(-2.5)["key"] == "lower"
    assert narrative.attention(0.2)["label"] == "Usual level of attention" and narrative.attention(None)["key"] == "unknown"
    m = {"latest_day": "2026-10-20", "z_attention": 2.5, "attention_pctile_90d": 98.9, "share_change_7d_pct": -6,
         "violence_share_7d": 16, "violence_share_prev30d": 14, "tone_delta": -0.5}
    s = " ".join(narrative.country_summary("Sudan", m, {"themes": {"violence": 11, "diplomacy": 1}, "n": 12}))
    assert s.startswith("More attention than usual on Tue 20 Oct, one of the busiest days")
    assert "about the same as the week before" in s and "mostly about violence and security (92%)" in s
    assert narrative.country_summary("X", {}) == ["There isn't enough coverage history for X yet."]


def test_week_summary():
    wk = {"unusual_days": ["2026-10-20"], "quiet_days": [], "change_pct": 48.0, "violence": 17.6, "violence_prev": 16.5}
    s = narrative.week_summary("Sudan", wk, {"violence": 9, "diplomacy": 1}, 10, {"violence": 3, "diplomacy": 5}, 10)
    assert s[0] == "Sudan got unusually high attention on 1 day (Tue 20 Oct)."
    assert s[1] == "Its share of world news was up 48% on the week before."
    assert any("Violence and security featured much more" in x and "30% → 90%" in x for x in s)


# ---------------- archive
def test_mentions_merge_dedupes_and_tags(tmp_path):
    rows = []
    tag = lambda t: [c["name"] for c in CFG["countries"] if st.Matcher(c).mentions(t)]  # noqa: E731
    items = [h("Kosovo-Serbia dialogue at a standstill", "Kosovo Online"), h("How Syria can avoid the trap", "Atlantic Council")]
    assert archive.merge_mentions(rows, items, term="EIP", language="English", found="2026-10-21 04:52", tag_countries=tag) == 2
    assert archive.merge_mentions(rows, items[:1], term="EIP", language="French", found="x", tag_countries=tag) == 0
    assert rows[0]["countries"] == "Serbia; Kosovo" and rows[0]["published"] == "2026-10-20 10:00"
    archive.save_mentions(tmp_path / "m.csv", rows)
    assert archive.load_mentions(tmp_path / "m.csv")[0]["outlet"] in {"Kosovo Online", "Atlantic Council"}


def test_weeks_and_months():
    assert archive.week_id(date(2026, 10, 21)) == "2026-W43"
    assert archive.week_bounds("2026-W43") == (date(2026, 10, 19), date(2026, 10, 25))
    assert archive.recent_weeks(date(2026, 10, 21), 2) == ["2026-W43", "2026-W42"]
    assert archive.months_between("2026-09-01", date(2026, 10, 21)) == [("2026-10-01", "2026-11-01"), ("2026-09-01", "2026-10-01")]
    assert archive.in_week("2026-10-25T23:00:00+00:00", date(2026, 10, 19), date(2026, 10, 25))
    assert not archive.in_week("2026-10-26T00:10:00+00:00", date(2026, 10, 19), date(2026, 10, 25))


def test_google_news_urls():
    u = gnews.build_url('"Institut européen pour la paix"', edition="FR:fr", after="2026-09-01", before="2026-10-01")
    assert "hl=fr&gl=FR&ceid=FR%3Afr" in u and "after%3A2026-09-01+before%3A2026-10-01" in u
    assert "when%3A2d" in gnews.build_url("Sudan") and "hl=en-GB" in gnews.build_url("Sudan")
