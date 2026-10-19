# Conflict Media Monitor

A self-updating dashboard of media attention, tone and framing across 27 conflict-affected and dialogue countries. GitHub Actions pulls fresh data every three hours; GitHub Pages serves the site. No servers, no API keys, no build step.

## What it shows

- **Map** of the 27 countries, switchable between anomaly, share of coverage, tone, violence share and peace-talk share. Countries spiking above +2 get a ring.
- **Moving now**: the biggest coverage anomalies with the reason in plain words.
- **Watch term**: Google News mentions of the European Institute of Peace.
- **Country ledger**: sortable table with today's share, anomaly z-score, 90-day percentile, 7-day volume and change, 30-day trend, tone, violence and peace-talk shares and a 90-day sparkline.
- **Ninety days at a glance**: small multiples with a rolling baseline band and anomaly dots.
- **Framing**: violence-versus-peace scatter and a tone ranking with the shift from the prior 30 days.
- **Wire**: every Google News headline and GDELT article from the latest run, filterable.
- **Country panel** (click anything): KPIs, share/tone/framing charts, top outlets, event mix, most-covered stories, all headlines, and links to Google News, GDELT, ReliefWeb, CrisisWatch and ACLED. Each country has a shareable URL (`#/SDN`).

## Data and metrics

Every 15 minutes GDELT machine-codes world news (English plus ~65 translated languages) into events: who did what to whom, where, and how many articles reported it. The pipeline downloads those raw event files directly (the GDELT query API rate-limits GitHub's servers; the files don't) and counts an event toward a country if it happens there (ActionGeo FIPS code) or involves its actors (CAMEO country code). Matching on codes rather than keywords means "Georgia" no longer picks up Atlanta.

| Metric | Definition |
|---|---|
| Coverage | Sum of NumArticles over the country's events. One article can report several events, so the unit is article mentions. |
| Share | Coverage per 10,000 of all coverage GDELT coded worldwide that day. Comparable across days. |
| Anomaly | Robust z-score of today's share vs the previous 28 days: (x − median) / (1.4826 × MAD). |
| 90-day percentile | Where today's share sits in the country's own 90-day history. |
| 30-day trend | OLS slope of log(share) over 30 days, as % change per week. |
| Volatility | Coefficient of variation of daily share over 30 days. |
| Tone | Article-weighted GDELT AvgTone over 7 days, and its change vs the prior 30 days. |
| Violence share | Share of coverage on CAMEO roots 18–20 (assault, fight, mass violence). |
| Peace-talk share | Share of coverage on CAMEO 036, 045, 046, 057, 087 (intent to negotiate, mediate, negotiate, sign agreement, de-escalate/ceasefire). |
| Event mix | Coverage by CAMEO root category over 7 days. |

Story titles in the GDELT lists are reconstructed from article URLs, because GDELT does not publish headlines. Mainstream headlines come from Google News RSS.

## How it works

```
GitHub Actions (every 3 h, or "Run workflow")
  -> build_data.py
       monitor/events.py   download + parse GDELT 2.0 event files (16 parallel downloads, 30-min budget)
       monitor/gnews.py    Google News RSS headlines
       monitor/metrics.py  pure metric functions (unit-tested)
  -> data/daily.csv          per country per day aggregates, incl. event-type counts (92-day window)
  -> data/slots_done.txt     which 15-minute files are already counted
  -> data/recent_articles.json  most-covered stories, last 72 h
  -> data/latest.json        everything the page renders
  -> deploy to GitHub Pages
```

The first run backfills as much of the 92-day window as the budget allows, newest first; later runs finish the backlog and then only fetch the ~24 new files since the previous run. While history is short the page says so, because baselines need a few weeks to settle.

## Editing the country list

Everything lives in `config/countries.json`: name, region, group (`operates` = field presence, `dialogue` = regional dialogue), FIPS and CAMEO codes for event matching, the Google News query and the map name. Push the change and the next run picks it up; to refresh immediately, open **Actions → Update media data → Run workflow**.

## Local run

```bash
BUDGET_MIN=5 python build_data.py   # short run; repeat to continue the backfill
python -m http.server              # then open http://localhost:8000
pip install -r requirements-dev.txt && pytest -q
```

## Caveats

GDELT's automated event coding misfires on some stories and over-weights online and wire-syndicated outlets. Compare a country against its own history rather than ranking levels across countries too literally. Coverage of a country includes events elsewhere involving its actors (an Iranian minister in Geneva counts for Iran).

Map data: world-atlas (Natural Earth, public domain). Libraries vendored in `assets/vendor` (d3-array, d3-geo, topojson-client; ISC licence).
