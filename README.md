# Conflict Media Monitor

A self-updating dashboard of media attention, tone and framing across 27 conflict-affected and dialogue countries. GitHub Actions pulls fresh data every six hours; GitHub Pages serves the site. No servers, no API keys, no build step.

## What it shows

- **Map** of the 27 countries, switchable between anomaly, share of coverage, tone, violence framing and peace framing. Countries spiking above +2 get a ring.
- **Moving now**: the biggest coverage anomalies with the reason in plain words.
- **Watch term**: articles mentioning the European Institute of Peace.
- **Country ledger**: sortable table with today's share, anomaly z-score, 90-day percentile, 7-day volume and change, 30-day trend, tone, framing and a 90-day sparkline.
- **Ninety days at a glance**: small multiples with a rolling baseline band and anomaly dots.
- **Framing**: violence-versus-peace scatter and a tone ranking with the shift from the prior 30 days.
- **Wire**: every Google News headline and GDELT article from the latest run, filterable.
- **Country panel** (click anything): KPIs, share/tone/framing charts, top outlets, source countries, all headlines, and links to Google News, GDELT, ReliefWeb, CrisisWatch and ACLED. Each country has a shareable URL (`#/SDN`).

## Metrics

| Metric | Definition |
|---|---|
| Share | Country articles per 10,000 articles GDELT monitored worldwide that day. Comparable across days. |
| Anomaly | Robust z-score of today's share vs the previous 28 days: (x − median) / (1.4826 × MAD). |
| 90-day percentile | Where today's share sits in the country's own 90-day history. |
| 30-day trend | OLS slope of log(share) over 30 days, as % change per week. |
| Volatility | Coefficient of variation of daily share over 30 days. |
| Tone | GDELT average document tone, article-weighted over 7 days, and its change vs the prior 30 days. |
| Violence / peace framing | Share of a country's articles that also match the keyword sets in `config/countries.json`. |

Today's bucket is partial; it is used once GDELT has seen at least 30% of a normal day's volume, since share (unlike raw count) is already a fair estimate at that point.

## How it works

```
GitHub Actions (every 6 h, or "Run workflow")
  -> build_data.py
       monitor/gdelt.py    GDELT DOC 2.0: volume, tone, framing timelines + article lists (rate-limited, 1 call / 6 s)
       monitor/gnews.py    Google News RSS headlines
       monitor/metrics.py  pure metric functions (unit-tested)
  -> data/latest.json      everything the page renders
  -> data/history.csv      daily archive that grows past GDELT's 3-month window
  -> deploy to GitHub Pages
index.html + assets/app.js read data/latest.json in the browser
```

If GDELT fails for one country, the previous run's data is kept and marked stale on the page. The job only fails if nothing at all came back.

## Editing the country list

Everything lives in `config/countries.json`: name, region, group (`operates` = field presence, `dialogue` = regional dialogue), the GDELT query, the Google News query and the map name. GDELT queries need OR-lists in parentheses and terms of three or more characters. Push the change and the next run picks it up; to refresh immediately, open **Actions → Update media data → Run workflow**.

## Local run

```bash
python build_data.py              # all countries, ~15 minutes
ONLY=UKR,SDN python build_data.py  # quick subset
python -m http.server              # then open http://localhost:8000
pip install -r requirements-dev.txt && pytest -q
```

## Caveats

Keyword queries are noisy for ambiguous names (Georgia, Panama, Oman). GDELT over-weights online, English-language and wire-syndicated outlets, so compare a country against its own history rather than ranking levels across countries too literally.

Map data: world-atlas (Natural Earth, public domain). Libraries vendored in `assets/vendor` (d3-array, d3-geo, topojson-client; ISC licence).
