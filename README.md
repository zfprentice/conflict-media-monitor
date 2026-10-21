# Conflict Media Monitor

A self-updating site that shows what the media is reporting across 27 conflict-affected and dialogue countries: the main stories, whether a country is getting unusual attention, a weekly report, and every media mention of the European Institute of Peace. GitHub Actions refreshes it every three hours; GitHub Pages serves it. No servers, no API keys.

Written for readers who don't work with statistics: every page leads with real headlines and plain sentences, and the numbers sit in their own tab.

## What it shows

- **Overview.** "Needs a look": countries getting more attention than usual, or where coverage has turned more violent or more negative, each with a plain-language summary, its main stories (headlines about the same event grouped, ranked by how many outlets carried them), what coverage is about, and names in the headlines. Then the map, EIP's latest mentions, and a card for every country with its main story of the week.
- **Weekly report.** One page per calendar week, back to the start of the history: which countries had days of unusual attention, the most widely reported stories, EIP mentions that week, and for each country a summary, its main stories and how topics shifted from the week before. Every week is kept. "Copy text" per country, "Copy whole report", and "Print or save as PDF".
- **EIP in the news.** Every article Google News finds mentioning the Institute, in English, French, German, Spanish and Arabic, kept permanently: counts for 7 and 30 days, the quarter and the year, mentions per month, a searchable table and an **Excel workbook** (clickable links, "Relevant?" and notes columns, month-by-language counts).
- **Charts & data.** The analyst view: sortable country ledger with z-scores, 90-day small multiples with the usual range, violence versus diplomatic activity, tone ranking, the full wire of headlines, and the method.
- **Country panel** (click anything): summary, main stories with other reports of each, topic mix, attention/tone/framing charts, latest headlines, other outlets, and links to Google News, ReliefWeb, CrisisWatch, ACLED and GDELT. Each country has a shareable URL (`#/SDN`); tabs too (`#weekly`, `#eip`).
- **Excel:** `data/history.xlsx` has every country, every day since the monitor started, plus one row per country per week with its summary and main story.

## Stories and topics

Each run searches Google News (UK English edition) for each country over the past two and seven days. A headline is kept only if it names the country, its capital, people or main actors (the `gdelt`, `news` and `match` terms in the config, after removing `strip` phrases such as "South Sudan" for Sudan), and isn't sport, weather, markets, an earthquake bulletin or a press release. Headlines that share enough distinctive words (rare words count more than "kill" or "war") are grouped into one story; stories are ranked by the number of outlets. Each headline is keyword-tagged with zero or more topics: violence and security, humanitarian needs, talks and diplomacy, politics and governance, rights and justice, economy. "Names in the headlines" are capitalised names repeated across sentence-case headlines.

Nothing is generated: every story shown is a real headline with its link, and every sentence is a template filled from the numbers.

Finished weeks are searched again with a date range (`after:`/`before:`) so the weekly report covers the whole week, then frozen. The previous 13 weeks are filled in gradually, newest first.

## Attention metrics

GDELT machine-codes world news (English plus ~65 translated languages) every 15 minutes into events. The pipeline downloads those raw event files and counts an event toward a country if it happens there (ActionGeo FIPS code) or involves its actors (CAMEO country code).

| Metric | Definition |
|---|---|
| Coverage | Sum of NumArticles over the country's events (article mentions). |
| Share | Coverage per 10,000 of all coverage GDELT coded worldwide that day. |
| Anomaly | Robust z-score of the last complete day's share vs the previous 28 days, (x − median) / (1.4826 × MAD), after dividing out the country's weekday pattern. Plain-language levels: below −2 "unusually little", −2 to −1 "a little less", −1 to +1 "usual", +1 to +2 "a little more", +2 to +3 "more", above +3 "much more attention than usual". |
| Usual range | Weekday-adjusted rolling 28-day median ± 2 robust SDs. Days above it are "unusually high" in the weekly report. |
| 90-day percentile, 30-day trend, volatility | As before: percentile of the adjusted share, OLS slope of log share (% per week), coefficient of variation. |
| Tone | Article-weighted GDELT AvgTone over 7 days, and its change vs the prior 30 days. |
| Violence | Share of coverage on CAMEO roots 18–20 (assault, fight, mass violence). |
| Diplomatic activity | Share of coverage on CAMEO 026–028, 036–039, 045, 046, 057, 087 (appeals and intent to negotiate or mediate, mediation, negotiation, agreements, de-escalation). Dominated by routine meetings and visits, so it is shown as context only and never flagged. It was previously labelled "peace talk", with a narrower "mediation" share; both overstated what the codes measure and were dropped. |

Only complete UTC days (90+ of 96 files) are judged; today's partial share is shown but not scored.

## How it works

```
GitHub Actions (every 3 h, or "Run workflow")
  -> build_data.py
       monitor/events.py     download + parse GDELT 2.0 event files (30-min budget)
       monitor/gnews.py      Google News RSS (editions, date ranges)
       monitor/stories.py    relevance and noise filters, story grouping, topics, names
       monitor/metrics.py    pure metric functions
       monitor/narrative.py  plain-language sentences
       monitor/archive.py    EIP mentions and weekly story snapshots
       monitor/excel.py      Excel workbooks
  records, committed to the repo:
       data/daily.csv            per country per day, kept indefinitely
       data/slots_done.txt       which 15-minute GDELT files are counted (last 92 days)
       data/recent_articles.json GDELT's most-covered stories, last 72 h
       data/news.json            latest headlines and stories per country
       data/weekly/YYYY-Www.json each week's stories, topics and names
       data/eip_mentions.csv     every EIP mention, kept indefinitely
       data/backfill_done.txt    which past months of EIP mentions have been searched
  outputs, rebuilt every run and deployed (not committed):
       data/latest.json, data/weekly.json, data/eip_mentions.json, data/*.xlsx
  -> deploy to GitHub Pages
```

A code change pushed to `main` rebuilds the outputs from the records without fetching anything (`OFFLINE=1`). Runs on other branches (via "Run workflow") are dry runs: they fetch and build but neither commit nor deploy.

Google News gets its own time budget (`NEWS_BUDGET_MIN`, default 6) and stops early if Google refuses six requests in a row; a country whose searches fail keeps its previous stories, and the page says how old they are. Past weeks and past months of EIP mentions use at most 60 requests per run.

## Editing the country list and watch terms

Everything lives in `config/countries.json`. Per country: name, region, group (`operates` = field presence, `dialogue` = regional dialogue), FIPS and CAMEO codes for event matching, the Google News query (`news`), extra words that count as naming the country (`match`), phrases removed before that check (`strip`) and phrases that drop a headline (`exclude`). `watch_terms` lists the names to archive, each with one query per Google News edition and the date to search back to (`backfill_from`). Push the change and the next run picks it up; to refresh immediately, open **Actions → Update media data → Run workflow** on `main`.

## Local run

```bash
pip install -r requirements-dev.txt
OFFLINE=1 python build_data.py     # rebuild the page from the committed records (no network)
BUDGET_MIN=5 python build_data.py  # or a short live run
python -m http.server              # then open http://localhost:8000
pytest -q
```

## Caveats

Google News doesn't index every outlet, and many headlines in the EIP list won't name the Institute (it matches the article body), so check the article before citing it. Story grouping and topic tagging are keyword-based and will sometimes split one event into two stories or tag a headline oddly. GDELT's automated event coding misfires on some stories and over-weights online and wire-syndicated outlets; compare a country with its own history rather than ranking levels across countries. Coverage of a country includes events elsewhere involving its actors (an Iranian minister in Geneva counts for Iran).

Map data: world-atlas (Natural Earth, public domain). Libraries vendored in `assets/vendor` (d3-array, d3-geo, topojson-client; ISC licence).
