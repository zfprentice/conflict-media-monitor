/* Conflict Media Monitor — front end. Vanilla JS, no build step.
   Reads data/latest.json (and, when their tab opens, data/weekly.json and data/eip_mentions.json),
   all written by build_data.py in GitHub Actions. */
(() => {
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const TZ = "Europe/Brussels";
const TABS = ["overview", "weekly", "eip", "charts"];

const S = {
  data: null, world: null, weekly: null, mentions: null, tab: "overview",
  metric: "z", tier: "all", q: "", week: null,
  sort: { key: "z", dir: -1 }, wireCountry: "all", wireKind: "all", wireN: 40,
  eipLang: "all", eipN: 50, open: null,
};

/* ---------------- formatting ---------------- */
const nf0 = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const f0 = (x) => (x == null ? "–" : nf0.format(x));
const f1 = (x) => (x == null ? "–" : nf1.format(x));
const sgn = (x, d = 1) => (x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d));
const pct = (x) => (x == null ? "–" : sgn(x, 0) + "%");
function ago(iso) {
  if (!iso) return "";
  const m = (Date.now() - new Date(iso.replace(" ", "T") + (iso.length === 16 ? ":00Z" : "")).getTime()) / 60000;
  if (Number.isNaN(m)) return "";
  if (m < 1) return "just now";
  if (m < 60) return `${Math.round(m)} min ago`;
  if (m < 60 * 24) return `${Math.round(m / 60)} h ago`;
  if (m < 60 * 24 * 60) return `${Math.round(m / 1440)} d ago`;
  return dateLabel(iso);
}
const dayLabel = (d) => new Date(d + "T12:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const dateLabel = (d) => new Date(d.slice(0, 10) + "T12:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const weekdayLabel = (d) => new Date(d + "T12:00:00Z").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
const stampFmt = (iso) => new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: TZ });
const tierLabel = (t) => (t === "operates" ? "Field presence" : "Regional dialogue");
const weekRange = (w) => {
  const a = new Date(w.start + "T12:00:00Z"), b = new Date(w.end + "T12:00:00Z");
  const sameMonth = a.getUTCMonth() === b.getUTCMonth();
  return `${a.getUTCDate()}${sameMonth ? "" : " " + a.toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" })}–${b.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })}`;
};

/* ---------------- colour ---------------- */
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
function hex2rgb(h) { h = h.replace("#", ""); if (h.length === 3) h = h.split("").map((c) => c + c).join(""); const n = parseInt(h, 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; }
function mix(a, b, t) { const A = hex2rgb(a), B = hex2rgb(b); t = Math.max(0, Math.min(1, t)); return `rgb(${A.map((v, i) => Math.round(v + (B[i] - v) * t)).join(",")})`; }
function ramp(stops, t) { // stops: array of hex, t in [0,1]
  if (t == null || Number.isNaN(t)) return css("--land");
  t = Math.max(0, Math.min(1, t)); const seg = (stops.length - 1) * t; const i = Math.min(Math.floor(seg), stops.length - 2);
  return mix(stops[i], stops[i + 1], seg - i);
}

/* Map metrics */
const METRICS = {
  z: {
    label: "Unusual attention", long: "How much attention each country got on the last full day, compared with its own recent past",
    get: (c) => c.metrics?.z_attention, fmt: (x) => sgn(x),
    color: (x) => x == null ? null : x < 0 ? ramp([css("--neutral"), css("--ink-3")], -x / 3) : ramp([css("--neutral"), css("--attn-1"), css("--attn-2"), css("--attn-3")], x / 4),
    legend: () => ({ grad: [css("--ink-3"), css("--neutral"), css("--attn-1"), css("--attn-2"), css("--attn-3")], lo: "quieter", hi: "busier than usual" }),
  },
  share: {
    label: "Share of news", long: "Share of all news coverage worldwide, per 10,000 articles, last 7 days",
    get: (c) => c.metrics?.share_7d, fmt: (x) => f1(x),
    color: (x, ext) => x == null ? null : ramp([css("--attn-0"), css("--attn-1"), css("--attn-2"), css("--attn-3")], Math.log(x / ext.min) / Math.log(ext.max / ext.min || 2)),
    legend: (ext) => ({ grad: [css("--attn-0"), css("--attn-1"), css("--attn-2"), css("--attn-3")], lo: f1(ext.min), hi: f1(ext.max) + " per 10k" }),
  },
  tone: {
    label: "Tone", long: "Average tone of coverage, last 7 days (more negative = grimmer, more hostile language)",
    get: (c) => c.metrics?.tone_7d, fmt: (x) => sgn(x, 2),
    color: (x) => x == null ? null : x < -2.5 ? ramp([css("--neutral"), css("--neg")], (-2.5 - x) / 3.5) : ramp([css("--neutral"), css("--pos")], (x + 2.5) / 3),
    legend: () => ({ grad: [css("--neg"), css("--neutral"), css("--pos")], lo: "grim", hi: "neutral" }),
  },
  violence: {
    label: "Violence", long: "Share of each country's coverage about attacks, armed clashes or mass violence (7 days)",
    get: (c) => c.metrics?.violence_share_7d, fmt: (x) => f0(x) + "%",
    color: (x) => x == null ? null : ramp([css("--neutral"), css("--neg")], x / 35),
    legend: () => ({ grad: [css("--neutral"), css("--neg")], lo: "0%", hi: "35%+" }),
  },
  diplomacy: {
    label: "Diplomatic activity", long: "Share of coverage about meetings, appeals, negotiations, agreements and ceasefires (7 days); mostly routine diplomacy",
    get: (c) => c.metrics?.peace_share_7d, fmt: (x) => f0(x) + "%",
    color: (x) => x == null ? null : ramp([css("--neutral"), css("--pos")], x / 20),
    legend: () => ({ grad: [css("--neutral"), css("--pos")], lo: "0%", hi: "20%+" }),
  },
};

/* ---------------- data helpers ---------------- */
const inTier = (c) => S.tier === "all" || c.tier === S.tier;
const qMatch = (...xs) => !S.q || xs.some((x) => String(x || "").toLowerCase().includes(S.q));
const visible = () => S.data.countries.filter((c) => inTier(c) && qMatch(c.name, c.region));
const byIso = (iso) => S.data.countries.find((c) => c.iso3 === iso);
const THEMES = () => S.data.method?.themes || {};
const bandOf = (series) => series.map((p) => (p.b ? { lo: p.b[0], med: p.b[1], hi: p.b[2] } : null));
function rollingRatio(series, num, den, win = 7) {
  return series.map((_, i) => {
    const w = series.slice(Math.max(0, i - win + 1), i + 1);
    const d = w.reduce((a, r) => a + (r[den] || 0), 0); const n = w.reduce((a, r) => a + (r[num] || 0), 0);
    return d && w.some((r) => r[num] != null) ? (100 * n) / d : null;
  });
}
function rollingMean(vals, win = 7) {
  return vals.map((_, i) => { const w = vals.slice(Math.max(0, i - win + 1), i + 1).filter((v) => v != null); return w.length ? w.reduce((a, b) => a + b, 0) / w.length : null; });
}
const PILL = { much_higher: "hot", higher: "hot", bit_higher: "warm", usual: "", bit_lower: "cool", lower: "cool", unknown: "" };
const pill = (a) => `<span class="pill ${PILL[a?.key] || ""}">${esc(a?.label || "–")}</span>`;
const needsLook = (c) => (c.metrics?.z_attention ?? 0) >= 2 || (c.flags || []).some((f) => f.level === "high" || f.level === "mid");
function themeShares(themes, n) {
  if (!themes || !n) return [];
  return Object.entries(themes).filter(([, v]) => v).map(([k, v]) => [k, Math.round((100 * v) / n)]).sort((a, b) => b[1] - a[1]);
}

/* ---------------- story rendering (shared by overview, drawer, weekly) ---------------- */
function storyMeta(s) {
  const src = s.sources || [];
  const who = src.length ? (src.length > 3 ? `${src.slice(0, 3).join(", ")} and ${s.outlets - 3} more` : src.join(", ")) : s.source;
  return `${s.outlets > 1 ? `<b>${s.outlets} outlets</b>: ` : ""}${esc(who)}${s.last ? `, ${ago(s.last)}` : ""}`;
}
function storyList(list, { max = 3, also = false, cls = "stories" } = {}) {
  if (!list?.length) return `<p class="empty">No stories collected for this period.</p>`;
  return `<ol class="${cls}">${list.slice(0, max).map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>
    <div class="meta">${storyMeta(s)}</div>
    ${also && s.also?.length ? `<details class="also"><summary>Other reports</summary><ul>${s.also.map((a) => `<li><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a> <span class="faint">${esc(a.source)}</span></li>`).join("")}</ul></details>` : ""}</li>`).join("")}</ol>`;
}
function themeChips(themes, n, max = 3) {
  const top = themeShares(themes, n).filter(([, p]) => p >= 15).slice(0, max);
  return top.length ? `<div class="chips">${top.map(([k, p]) => `<span class="tchip t-${k}">${esc(THEMES()[k] || k)} <b>${p}%</b></span>`).join("")}</div>` : "";
}
function themeBars(themes, n, prev, prevN) {
  const now = Object.fromEntries(themeShares(themes, n)), before = Object.fromEntries(themeShares(prev, prevN));
  const keys = Object.keys(THEMES());
  if (!n) return `<p class="empty">No headlines collected.</p>`;
  return `<div class="tbars">${keys.map((k) => `<div class="row"><span>${esc(THEMES()[k])}</span><span class="track"><span class="fill t-${k}" style="width:${now[k] || 0}%"></span></span><span class="num">${now[k] || 0}%</span>${prev && prevN ? `<span class="faint num was">was ${before[k] || 0}%</span>` : ""}</div>`).join("")}</div>
    <p class="faint small">Share of ${f0(n)} headlines touching each topic (a headline can touch several).</p>`;
}
const namesLine = (names) => (names?.length ? `<p class="names"><span class="faint">Names in the headlines:</span> ${names.map(([k, v]) => `${esc(k)} <span class="faint">(${v})</span>`).join(", ")}</p>` : "");

/* ---------------- SVG charts ---------------- */
function sparkline(vals, w = 110, h = 26, hot = false) {
  const v = vals.map((x) => (x == null ? null : x)); const ok = v.filter((x) => x != null);
  if (ok.length < 2) return "";
  const max = Math.max(...ok), min = Math.min(...ok, 0);
  const X = (i) => (i / (v.length - 1)) * (w - 4) + 2, Y = (x) => h - 3 - ((x - min) / (max - min || 1)) * (h - 6);
  let d = "";
  v.forEach((x, i) => { if (x == null) return; d += (d ? "L" : "M") + X(i).toFixed(1) + "," + Y(x).toFixed(1); });
  const a = d + `L${X(v.length - 1).toFixed(1)},${h}L${X(0)},${h}Z`;
  const li = v.length - 1;
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">
    <path d="${a}" fill="var(--attn-0)" opacity=".8"/><path d="${d}" fill="none" stroke="var(--attn-2)" stroke-width="1.3"/>
    ${v[li] != null ? `<circle cx="${X(li)}" cy="${Y(v[li])}" r="2.6" fill="${hot ? "var(--signal)" : "var(--attn-2)"}"/>` : ""}</svg>`;
}

function zBar(z) {
  const w = 70, h = 10, mid = w / 2, clamp = Math.max(-4, Math.min(4, z ?? 0)), x = mid + (clamp / 4) * mid;
  const col = z >= 2 ? "var(--signal)" : z < 0 ? "var(--ink-3)" : "var(--attn-2)";
  return `<svg width="${w}" height="${h}" aria-hidden="true"><rect x="0" y="4" width="${w}" height="2" fill="var(--rule-2)"/>
    <line x1="${mid}" x2="${mid}" y1="0" y2="${h}" stroke="var(--rule)"/>${z == null ? "" : `<rect x="${Math.min(mid, x)}" y="2" width="${Math.abs(x - mid)}" height="6" rx="2" fill="${col}"/>`}</svg>`;
}

/* Generic time-series chart. lines: [{vals, color, width, dash}] */
function tsChart({ dates, lines, band, marks = [], height = 180, yfmt = f1, zero = false, refLine = null, width = 660 }) {
  const W = width, H = height, L = 40, R = 10, T = 10, B = 22;
  const all = lines.flatMap((l) => l.vals).concat(band ? band.flatMap((b) => (b ? [b.lo, b.hi] : [])) : []).filter((v) => v != null);
  if (!all.length) return `<p class="empty">No data in this window.</p>`;
  let min = Math.min(...all), max = Math.max(...all);
  if (zero) min = Math.min(0, min);
  if (refLine != null) { min = Math.min(min, refLine); max = Math.max(max, refLine); }
  const pad = (max - min) * 0.08 || 1; min -= zero && min === 0 ? 0 : pad; max += pad;
  const n = dates.length, X = (i) => L + (i / (n - 1 || 1)) * (W - L - R), Y = (v) => T + (1 - (v - min) / (max - min)) * (H - T - B);
  const ticks = 4, grid = [];
  for (let k = 0; k <= ticks; k++) { const v = min + ((max - min) * k) / ticks; grid.push(`<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${L - 6}" y="${Y(v) + 3.5}" text-anchor="end">${yfmt(v)}</text>`); }
  const xt = []; for (let i = 0; i < n; i += Math.ceil(n / (W < 500 ? 4 : 6))) xt.push(`<text x="${X(i)}" y="${H - 6}" text-anchor="middle">${dayLabel(dates[i])}</text>`);
  let bandPath = "";
  if (band) {
    let top = ""; const bot = [];
    band.forEach((b, i) => { if (!b) return; top += (top ? "L" : "M") + X(i).toFixed(1) + "," + Y(b.hi).toFixed(1); bot.unshift(X(i).toFixed(1) + "," + Y(b.lo).toFixed(1)); });
    if (top) bandPath = `<path d="${top}L${bot.join("L")}Z" fill="var(--attn-0)" opacity=".7"/>`;
    let med = ""; band.forEach((b, i) => { if (b) med += (med ? "L" : "M") + X(i).toFixed(1) + "," + Y(b.med).toFixed(1); });
    if (med) bandPath += `<path d="${med}" fill="none" stroke="var(--attn-1)" stroke-dasharray="3 3" stroke-width="1"/>`;
  }
  const paths = lines.map((l) => { let d = ""; l.vals.forEach((v, i) => { if (v == null) { return; } d += (d ? "L" : "M") + X(i).toFixed(1) + "," + Y(v).toFixed(1); });
    return `<path d="${d}" fill="none" stroke="${l.color}" stroke-width="${l.width || 1.8}" ${l.dash ? `stroke-dasharray="${l.dash}"` : ""} stroke-linejoin="round"/>`; }).join("");
  const mk = marks.map((i) => `<circle cx="${X(i)}" cy="${Y(lines[0].vals[i])}" r="3.6" fill="var(--signal)" stroke="var(--panel)" stroke-width="1.2"><title>${dayLabel(dates[i])}: unusually high</title></circle>`).join("");
  const ref = refLine != null ? `<line x1="${L}" x2="${W - R}" y1="${Y(refLine)}" y2="${Y(refLine)}" stroke="var(--ink-3)" stroke-width="1"/>` : "";
  return `<svg viewBox="0 0 ${W} ${H}" role="img">${grid.join("")}${xt.join("")}${bandPath}${ref}${paths}${mk}</svg>`;
}

function bars(pairs, empty = "Not enough articles in the last 3 days.") {
  if (!pairs?.length) return `<p class="empty">${empty}</p>`;
  const max = Math.max(...pairs.map((p) => p[1]));
  return `<div class="bars">${pairs.map(([k, v]) => `<div class="row"><span title="${esc(k)}">${esc(k)}</span><span class="track"><span class="fill" style="display:block;width:${(100 * v) / max}%"></span></span><span class="num faint">${f0(v)}</span></div>`).join("")}</div>`;
}

/* ---------------- masthead / footer ---------------- */
function renderStamp() {
  const d = S.data, r = d.run || {};
  const age = (Date.now() - new Date(d.generated_at)) / 36e5;
  const scored = d.method?.scored_day;
  $("#stamp").innerHTML = `Updated <b>${stampFmt(d.generated_at)}</b> Brussels time (${ago(d.generated_at)}). Stories come from Google News; attention figures from GDELT, which reads world news in over 65 languages.` +
    (scored ? ` Attention is judged on <b>${weekdayLabel(scored)}</b>, the last full day.` : "") +
    (r.news_failed ? ` <span class="stale-note">Google News didn't answer ${r.news_failed} of ${r.news_total} searches; some stories are from an earlier update.</span>` : "") +
    (r.complete_days != null && r.complete_days < 35 ? ` <span class="stale-note">History is still loading (${r.complete_days} of 92 days), so "usual" levels firm up over the next few updates.</span>` : "") +
    (age > 9 ? ` <span class="stale-note">The scheduled update looks overdue.</span>` : "");
  document.title = `${d.site_title}: ${d.countries.length} countries`;
  $("#title").innerHTML = `What the media is reporting across <span class="count">${d.countries.length}</span> countries`;
}

function renderFooter() {
  const r = S.data.run || {};
  $("#footer").innerHTML = `<div class="cols"><div>
    <h3>How this works</h3>
    <p><b>Stories.</b> Every few hours the monitor searches Google News for each country, throws away headlines that don't name the country (and sport, weather, market and earthquake bulletins), and groups headlines about the same event into one story. A story carried by more outlets ranks higher. Every story shown is a real headline with a link.</p>
    <p><b>Topics.</b> Each headline is tagged by keywords as violence and security, humanitarian needs, talks and diplomacy, politics and governance, rights and justice, or economy. A headline can have several topics or none. Keyword tagging is rough: treat the percentages as a guide to emphasis, not a measurement.</p>
    <p><b>Attention.</b> GDELT machine-reads world news in English and about 65 other languages and counts how many articles report events in or involving each country. The monitor compares each country with <i>its own</i> recent past (the previous four weeks, allowing for weekday rhythms), so "more attention than usual" means unusual for that country, not compared with others. Only full days are judged.</p>
    <p><b>Limits.</b> Google News doesn't index every outlet, and GDELT's automatic coding misfires on some stories. Use this to spot what to read, then read the reporting itself before drawing conclusions. The Charts &amp; data tab has the full method.</p>
  </div><div>
    <h3>Data</h3>
    <dl><dt>Excel</dt><dd><a href="data/history.xlsx">Coverage history</a> (every country, every day, plus weekly summaries), <a href="data/eip_mentions.xlsx">EIP mentions</a></dd>
    <dt>Raw files</dt><dd><a href="data/daily.csv">daily.csv</a>, <a href="data/latest.json">latest.json</a>, <a href="data/eip_mentions.csv">eip_mentions.csv</a></dd>
    <dt>History</dt><dd>${f0(r.history_days)} full days kept, growing by one each day</dd>
    <dt>Schedule</dt><dd>Every 3 hours via GitHub Actions</dd>
    <dt>Sources</dt><dd><a href="https://www.gdeltproject.org/data.html#rawdatafiles" rel="noopener">GDELT 2.0 event files</a>, <a href="https://news.google.com" rel="noopener">Google News</a></dd></dl>
  </div></div>`;
}

/* ---------------- tabs ---------------- */
function setTab(tab, push = true) {
  if (!TABS.includes(tab)) tab = "overview";
  S.tab = tab;
  document.querySelectorAll(".tabs-nav a").forEach((a) => a.setAttribute("aria-selected", a.dataset.tab === tab));
  TABS.forEach((t) => { $("#tab-" + t).hidden = t !== tab; });
  if (push && location.hash !== "#" + tab) history.replaceState(null, "", "#" + tab);
  renderTab();
}
function renderTab() {
  if (!S.data) return;
  ({ overview: renderOverview, weekly: renderWeekly, eip: renderEip, charts: renderCharts })[S.tab]();
}

/* ---------------- OVERVIEW ---------------- */
function renderOverview() {
  const el = $("#tab-overview");
  if (!el.dataset.built) {
    el.innerHTML = `
      <section class="block">
        <div class="block-head"><h2>Needs a look</h2><p>Countries getting more attention than usual, or where coverage has turned more violent or more negative, with the stories behind it.</p></div>
        <div class="hot-cards" id="hotCards"></div>
      </section>
      <div class="hero">
        <div class="mapcard">
          <div class="map-head"><h2 id="mapTitle"></h2>
            <div class="seg" id="metricSeg" role="group" aria-label="Map shows">${Object.entries(METRICS).map(([k, m]) => `<button data-metric="${k}" aria-pressed="${k === S.metric}">${m.label}</button>`).join("")}</div>
          </div>
          <svg id="map" viewBox="0 0 1000 520" role="img" aria-label="Map of tracked countries"></svg>
          <div class="legend" id="legend"></div>
        </div>
        <div class="side"><div class="panel watch" id="watch"></div></div>
      </div>
      <section class="block">
        <div class="block-head"><h2>Every country at a glance</h2><p>The main story of the past seven days and what coverage is about. Click a country for its stories, charts and links.</p></div>
        <div class="country-grid" id="allCards"></div>
      </section>`;
    $("#metricSeg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S.metric = b.dataset.metric; pressed("#metricSeg", b); renderMap(); });
    el.addEventListener("click", (e) => { const b = e.target.closest("[data-open]"); if (b) { e.preventDefault(); openCountry(b.dataset.open); } });
    el.dataset.built = "1";
  }
  const cs = S.data.countries.filter((c) => inTier(c) && qMatch(c.name, c.region, ...(c.recent?.stories || []).map((s) => s.title)));
  const hot = cs.filter(needsLook).sort((a, b) => (b.metrics?.z_attention ?? -9) - (a.metrics?.z_attention ?? -9));
  $("#hotCards").innerHTML = hot.length ? hot.map(hotCard).join("") :
    `<div class="panel calm"><p><b>Nothing stands out.</b> No country ${S.q || S.tier !== "all" ? "matching the filter " : ""}got unusually high attention on ${S.data.method?.scored_day ? weekdayLabel(S.data.method.scored_day) : "the last full day"}, and coverage hasn't turned sharply more violent or negative anywhere. The main stories for every country are below.</p></div>`;
  const rest = cs.filter((c) => !hot.includes(c)).sort((a, b) => S.data.countries.indexOf(a) - S.data.countries.indexOf(b));
  $("#allCards").innerHTML = rest.map(smallCard).join("") || (hot.length ? "" : `<p class="empty">No countries match the filter.</p>`);
  renderMap(); renderWatch();
}
function hotCard(c) {
  const r = c.recent || {};
  const extra = (c.flags || []).filter((f) => !/attention/.test(f.text)).map((f) => `<div class="flag ${f.level}">${esc(f.text)}</div>`).join("");
  return `<article class="panel hot-card">
    <header><h3><a href="#/${c.iso3}" data-open="${c.iso3}">${esc(c.name)}</a></h3>${pill(c.attention)}</header>
    <p class="summary">${esc((c.summary || []).join(" "))}</p>${extra}
    <h4>Main stories, last 7 days</h4>${storyList(r.stories, { max: 3, also: true })}
    ${themeChips(r.themes, r.n)}${namesLine(r.names)}
    <button class="link-btn" data-open="${c.iso3}">Charts, all headlines and links for ${esc(c.name)} →</button>
  </article>`;
}
function smallCard(c) {
  const r = c.recent || {}, s = (r.stories || [])[0];
  return `<article class="panel small-card">
    <header><h3><a href="#/${c.iso3}" data-open="${c.iso3}">${esc(c.name)}</a></h3>${pill(c.attention)}</header>
    ${s ? `<p class="lead"><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a></p><div class="meta">${storyMeta(s)}</div>` : `<p class="empty">No headlines in the past week.</p>`}
    ${themeChips(r.themes, r.n, 2)}
  </article>`;
}
function pressed(sel, btn) { document.querySelectorAll(sel + " button").forEach((b) => b.setAttribute("aria-pressed", b === btn)); }

function renderWatch() {
  const w = (S.data.watch || [])[0];
  if (!w) { $("#watch").innerHTML = ""; return; }
  $("#watch").innerHTML = `<h2>${esc(w.label)} <small>in the news</small></h2>
    <div class="watch-nums"><div><div class="big num">${f0(w.count_30d)}</div><div class="muted small">mentions, last 30 days</div></div>
      <div><div class="big num">${f0(w.count_quarter)}</div><div class="muted small">in ${esc(w.quarter_label)}</div></div></div>
    ${w.recent?.length ? `<ul>${w.recent.slice(0, 4).map((i) => `<li><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a><div class="faint small">${esc(i.source)}${i.language !== "English" ? `, ${esc(i.language)}` : ""}, ${ago(i.published)}</div></li>`).join("")}</ul>` : `<p class="empty">No mentions recorded yet.</p>`}
    <a class="link-btn" href="#eip">All mentions and the Excel file →</a>`;
}

/* ---------------- map ---------------- */
function renderMap() {
  const svg = $("#map"); if (!svg) return; const m = METRICS[S.metric];
  $("#mapTitle").textContent = m.long;
  if (!S.world) { svg.innerHTML = `<text x="500" y="270" text-anchor="middle" fill="var(--ink-2)">Map unavailable</text>`; return; }
  const feats = topojson.feature(S.world, S.world.objects.countries).features;
  const nameToIso = {};
  S.data.countries.forEach((c) => { nameToIso[c.atlas] = c.iso3; (c.atlas_also || []).forEach((a) => (nameToIso[a] = c.iso3)); });
  const tracked = feats.filter((f) => nameToIso[f.properties.name]);
  const focus = { type: "FeatureCollection", features: tracked };
  const proj = d3.geoNaturalEarth1().fitWidth(960, focus);
  const path = d3.geoPath(proj);
  const [[bx0, by0], [, by1]] = path.bounds(focus);
  proj.translate([proj.translate()[0] - bx0 + 20, proj.translate()[1] - by0 + 24]);
  const MH = Math.round(by1 - by0 + 48);
  svg.setAttribute("viewBox", `0 0 1000 ${MH}`);
  const vis = new Set(visible().map((c) => c.iso3));
  const vals = S.data.countries.map(m.get).filter((v) => v != null && v > 0);
  const ext = { min: Math.min(...vals), max: Math.max(...vals) };
  let html = `<rect width="1000" height="${MH}" fill="transparent"/>`;
  html += feats.filter((f) => !nameToIso[f.properties.name]).map((f) => `<path class="land" d="${path(f) || ""}"/>`).join("");
  const pulses = [];
  tracked.forEach((f) => {
    const c = byIso(nameToIso[f.properties.name]); const v = m.get(c);
    const fill = m.color(v, ext) || css("--land");
    html += `<path class="tracked ${vis.has(c.iso3) ? "" : "dim"}" data-iso="${c.iso3}" d="${path(f) || ""}" fill="${fill}" tabindex="0" role="button" aria-label="${esc(c.name)}: ${esc(c.attention?.label || "")}"/>`;
    if (f.properties.name === c.atlas && (c.metrics?.z_attention ?? 0) >= 2 && vis.has(c.iso3)) {
      const [x, y] = path.centroid(f); if (!Number.isNaN(x)) pulses.push({ x, y, c });
    }
  });
  const placed = [];
  pulses.sort((a, b) => b.c.metrics.z_attention - a.c.metrics.z_attention).forEach(({ x, y, c }) => {
    html += `<circle class="pulse" cx="${x}" cy="${y}" r="14"/><circle class="dot" cx="${x}" cy="${y}" r="4"/>`;
    const text = c.name, w = text.length * 6.2 + 4;
    const tries = [[x + 8, y - 7, "start"], [x - 8, y - 7, "end"], [x + 8, y + 15, "start"], [x - 8, y + 15, "end"]];
    for (const [lx, ly, anchor] of tries) {
      const box = anchor === "start" ? [lx, ly - 10, lx + w, ly + 3] : [lx - w, ly - 10, lx, ly + 3];
      if (placed.some((b) => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]))) continue;
      placed.push(box); html += `<text class="lbl" x="${lx}" y="${ly}" text-anchor="${anchor}">${esc(text)}</text>`; break;
    }
  });
  svg.innerHTML = html;
  const lg = m.legend(ext);
  $("#legend").innerHTML = `<div>${esc(m.label)}</div><div class="bar" style="background:linear-gradient(90deg,${lg.grad.join(",")})"></div><div class="ends"><span>${lg.lo}</span><span>${lg.hi}</span></div>`;

  const tip = $("#tip");
  svg.querySelectorAll(".tracked").forEach((p) => {
    const c = byIso(p.dataset.iso);
    const show = (e) => {
      const s = c.recent?.stories?.[0];
      tip.innerHTML = `<b>${esc(c.name)}</b>${esc(c.attention?.label || "")}<br>${m.label}: ${m.fmt(m.get(c))}${s ? `<br><i>${esc(s.title)}</i>` : ""}`;
      tip.style.opacity = 1; const r = e.clientX != null ? e : p.getBoundingClientRect();
      const x = (r.clientX ?? r.left) + 14, y = (r.clientY ?? r.top) + 14;
      tip.style.left = Math.min(x, innerWidth - 250) + "px"; tip.style.top = Math.min(y, innerHeight - 130) + "px";
    };
    p.addEventListener("mousemove", show); p.addEventListener("focus", show);
    p.addEventListener("mouseleave", () => (tip.style.opacity = 0)); p.addEventListener("blur", () => (tip.style.opacity = 0));
    p.addEventListener("click", () => openCountry(c.iso3));
    p.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openCountry(c.iso3); } });
  });
}

/* ---------------- WEEKLY REPORT ---------------- */
async function loadJSON(url) { const r = await fetch(url + "?t=" + Date.now()); if (!r.ok) throw new Error(r.status); return r.json(); }

async function renderWeekly() {
  const el = $("#tab-weekly");
  if (!S.weekly) {
    el.innerHTML = `<div class="loading">Loading the weekly report…</div>`;
    try { S.weekly = (await loadJSON("data/weekly.json")).weeks; } catch (_) { el.innerHTML = `<div class="error"><h2>Weekly report unavailable</h2><p>It will appear after the next update.</p></div>`; return; }
    S.week = S.week || S.weekly[0]?.week;
  }
  const w = S.weekly.find((x) => x.week === S.week) || S.weekly[0];
  if (!w) { el.innerHTML = `<p class="empty">No weeks yet.</p>`; return; }
  const names = Object.fromEntries(S.data.countries.map((c) => [c.iso3, c]));
  const entries = Object.entries(w.countries).filter(([iso]) => names[iso] && inTier(names[iso]) && qMatch(names[iso].name, names[iso].region))
    .map(([iso, x]) => ({ c: names[iso], x }))
    .sort((a, b) => (b.x.stats?.unusual_days?.length || 0) - (a.x.stats?.unusual_days?.length || 0) || Math.abs(b.x.stats?.change_pct || 0) - Math.abs(a.x.stats?.change_pct || 0));
  const days = Math.max(0, ...entries.map((e) => e.x.stats?.days || 0));
  const unusual = entries.filter((e) => e.x.stats?.unusual_days?.length);
  const top = entries.flatMap((e) => (e.x.stories || []).slice(0, 1).map((s) => ({ s, c: e.c }))).sort((a, b) => b.s.outlets - a.s.outlets).slice(0, 6);
  const eip = (w.mentions?.eip || []);
  const collected = entries.some((e) => e.x.collected);
  const label = (x) => `Week ${+x.week.slice(6)}: ${weekRange(x)}${x.current ? " (so far)" : ""}`;
  el.innerHTML = `
    <div class="wk-tools">
      <label>Week <select id="weekSel">${S.weekly.map((x) => `<option value="${x.week}" ${x.week === w.week ? "selected" : ""}>${esc(label(x))}</option>`).join("")}</select></label>
      <button class="btn" id="copyAll">Copy whole report</button>
      <button class="btn" id="printBtn">Print or save as PDF</button>
    </div>
    <article class="report" id="report">
      <header class="report-head">
        <div class="kicker">Weekly media report</div>
        <h2>${esc(label(w))}</h2>
        <p class="muted">${w.current ? `This week is still in progress: figures cover ${days} full ${days === 1 ? "day" : "days"} so far and stories are updated every few hours.` : "Final for this week."} ${collected ? "" : "Stories for this week haven't been collected yet; they are filled in gradually, newest weeks first."}</p>
      </header>
      <section class="panel report-summary">
        <h3>The week in brief</h3>
        <ul class="brief">
          <li>${unusual.length ? `<b>${unusual.length} of ${entries.length} countries</b> had days of unusually high attention: ${unusual.map((e) => `<a href="#/${e.c.iso3}" data-open="${e.c.iso3}">${esc(e.c.name)}</a> (${e.x.stats.unusual_days.length} ${e.x.stats.unusual_days.length === 1 ? "day" : "days"})`).join(", ")}.` : `No country had a day of unusually high attention${w.current ? " so far" : ""}.`}</li>
          ${eip.length || (S.data.watch || [])[0] ? `<li>The European Institute of Peace was mentioned in <b>${eip.length}</b> ${eip.length === 1 ? "article" : "articles"} found on Google News${eip.length ? ": " + eip.slice(0, 3).map((m) => `<a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.title)}</a> <span class="faint">(${esc(m.source)})</span>`).join("; ") + (eip.length > 3 ? `; and ${eip.length - 3} more in the EIP tab` : "") : ""}.</li>` : ""}
        </ul>
        ${top.length ? `<h4>Most widely reported stories</h4><ol class="stories">${top.map(({ s, c }) => `<li><span class="chip">${esc(c.name)}</span><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a><div class="meta">${storyMeta(s)}</div></li>`).join("")}</ol>` : ""}
      </section>
      ${entries.map(({ c, x }) => weekCountry(c, x)).join("") || `<p class="empty">No countries match the filter.</p>`}
      <p class="faint small report-foot">Conflict Media Monitor. Stories from Google News, grouped automatically; attention figures from GDELT. "Unusual" compares each country with its own previous four weeks.</p>
    </article>`;
  $("#weekSel").onchange = (e) => { S.week = e.target.value; renderWeekly(); };
  $("#printBtn").onclick = () => window.print();
  $("#copyAll").onclick = (e) => copyText([`Weekly media report: ${label(w)}`, "", ...entries.map(({ c, x }) => weekText(c, x, w)), "Source: Conflict Media Monitor (Google News, GDELT)"].join("\n"), e.target);
  el.onclick = (e) => {
    const o = e.target.closest("[data-open]"); if (o) { e.preventDefault(); openCountry(o.dataset.open); return; }
    const b = e.target.closest("[data-copy]"); if (b) { const c = names[b.dataset.copy]; copyText(weekText(c, w.countries[c.iso3], w) + "Source: Conflict Media Monitor (Google News, GDELT)", b); }
  };
}
function weekCountry(c, x) {
  const st = x.stats || {}, u = st.unusual_days?.length || 0;
  const badge = u ? `<span class="pill hot">${u} ${u === 1 ? "day" : "days"} of unusual attention</span>` : st.quiet_days?.length >= 3 ? `<span class="pill cool">Quieter than usual</span>` : `<span class="pill">Usual attention</span>`;
  return `<article class="panel wk-country">
    <header><h3><a href="#/${c.iso3}" data-open="${c.iso3}">${esc(c.name)}</a> <small>${esc(c.region)}</small></h3>${badge}<button class="btn small" data-copy="${c.iso3}">Copy text</button></header>
    <p class="summary">${esc(x.summary.join(" "))}</p>
    <div class="wk-grid">
      <div><h4>Main stories</h4>${x.collected ? storyList(x.stories, { max: 5, also: true }) : `<p class="empty">Not collected yet.</p>`}</div>
      <div><h4>What headlines were about</h4>${x.collected ? themeBars(x.themes, x.n, x.themes_prev, x.n_prev) : `<p class="empty">Not collected yet.</p>`}
        ${st.share != null ? `<p class="faint small">Share of world news: ${f1(st.share)} per 10,000 articles${st.share_prev != null ? ` (week before: ${f1(st.share_prev)})` : ""}. Violence: ${f0(st.violence)}% of coverage.</p>` : ""}</div>
    </div>${namesLine(x.names)}
  </article>`;
}
function weekText(c, x, w) {
  const lines = [`${c.name}, ${weekRange(w)}${w.current ? " (so far)" : ""}`, x.summary.join(" ")];
  if (x.stories?.length) { lines.push("Main stories:"); x.stories.slice(0, 5).forEach((s) => lines.push(`- ${s.title} (${s.source}${s.outlets > 1 ? `; ${s.outlets} outlets` : ""}) ${s.url}`)); }
  return lines.join("\n") + "\n\n";
}
async function copyText(text, btn) {
  try { await navigator.clipboard.writeText(text); }
  catch (_) { const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove(); }
  const was = btn.textContent; btn.textContent = "Copied"; setTimeout(() => (btn.textContent = was), 1500);
}

/* ---------------- EIP IN THE NEWS ---------------- */
async function renderEip() {
  const el = $("#tab-eip"), w = (S.data.watch || [])[0];
  if (!w) { el.innerHTML = `<p class="empty">No watch term configured.</p>`; return; }
  if (!S.mentions) {
    el.innerHTML = `<div class="loading">Loading mentions…</div>`;
    try { S.mentions = await loadJSON(w.files.json); } catch (_) { S.mentions = []; }
  }
  const langs = [...new Set(S.mentions.map((m) => m.language))].sort();
  const rows = S.mentions.filter((m) => (S.eipLang === "all" || m.language === S.eipLang) && qMatch(m.title, m.source, m.countries));
  const months = w.by_month.slice(-24), mmax = Math.max(1, ...months.map((m) => m[1]));
  const BW = 640, BH = 150, bw = BW / months.length;
  const chart = `<svg viewBox="0 0 ${BW} ${BH + 22}" role="img" aria-label="Mentions per month">${months.map(([m, n], i) => {
    const h = (n / mmax) * BH; const lab = new Date(m + "-15T12:00:00Z").toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" });
    return `<g><rect x="${i * bw + 2}" y="${BH - h}" width="${bw - 4}" height="${h}" rx="2" fill="var(--attn-2)"><title>${m}: ${n}</title></rect>${n ? `<text x="${i * bw + bw / 2}" y="${BH - h - 4}" text-anchor="middle">${n}</text>` : ""}${i % 2 === 0 || months.length < 13 ? `<text x="${i * bw + bw / 2}" y="${BH + 15}" text-anchor="middle">${lab}${m.endsWith("-01") ? " " + m.slice(2, 4) : ""}</text>` : ""}</g>`;
  }).join("")}</svg>`;
  const k = (v, l) => `<div class="kpi"><div class="v num">${f0(v)}</div><div class="l">${l}</div></div>`;
  el.innerHTML = `
    <div class="block-head"><h2>${esc(w.label)} in the news</h2><p>Every article Google News finds that mentions the Institute by name, in ${esc(w.languages.join(", "))}. Collected automatically and kept permanently.</p></div>
    <div class="kpis five">${k(w.count_7d, "Last 7 days")}${k(w.count_30d, "Last 30 days")}${k(w.count_quarter, "This quarter (" + esc(w.quarter_label) + ")")}${k(w.count_year, "This year")}${k(w.total, "All recorded, since " + dateLabel(w.since))}</div>
    ${w.backfill_done < w.backfill_total ? `<p class="stale-note">Still searching older months (${w.backfill_done} of ${w.backfill_total} month-by-language searches done). Counts for earlier months will rise over the next few updates.</p>` : ""}
    <div class="grid2">
      <div class="panel chart"><h3>Mentions per month</h3>${chart}</div>
      <div class="panel"><h3>Download</h3>
        <p><a class="btn primary" href="${esc(w.files.xlsx)}">Excel workbook</a> <a class="btn" href="${esc(w.files.csv)}">CSV</a></p>
        <p class="small muted">The Excel file has every mention with a clickable link, columns for your own "Relevant?" and notes, and a month-by-language count. It is rebuilt every few hours, so copy rows into your own file before adding notes you want to keep.</p>
        <p class="small muted"><b>Read before citing:</b> Google News matches the name anywhere in an article, so many headlines won't mention it; open the link to check context. It doesn't index every outlet, so counts are a minimum. Syndicated stories appear once per outlet.</p>
      </div>
    </div>
    <section class="block spaced">
      <div class="wire-tools"><select id="eipLang" aria-label="Language"><option value="all">All languages</option>${langs.map((l) => `<option ${l === S.eipLang ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>
        <span class="muted small">${f0(rows.length)} ${rows.length === 1 ? "mention" : "mentions"}${S.q ? ` matching "${esc(S.q)}"` : ""}</span></div>
      <div class="ledger-wrap"><table class="mentions"><thead><tr><th>Published</th><th>Headline</th><th>Outlet</th><th>Language</th><th>Countries named</th></tr></thead>
        <tbody>${rows.slice(0, S.eipN).map((m) => `<tr><td class="num">${m.published ? dateLabel(m.published) : "–"}</td><td><a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.title)}</a></td><td>${esc(m.source)}</td><td>${esc(m.language)}</td><td>${esc(m.countries)}</td></tr>`).join("") || `<tr><td colspan="5" class="empty">No mentions match.</td></tr>`}</tbody></table></div>
      ${rows.length > S.eipN ? `<button class="more" id="eipMore">Show 50 more</button>` : ""}
    </section>`;
  $("#eipLang").onchange = (e) => { S.eipLang = e.target.value; S.eipN = 50; renderEip(); };
  const more = $("#eipMore"); if (more) more.onclick = () => { S.eipN += 50; renderEip(); };
}

/* ---------------- CHARTS & DATA ---------------- */
function renderCharts() {
  const el = $("#tab-charts");
  if (!el.dataset.built) {
    el.innerHTML = `
      <div class="block-head"><h2>Charts &amp; data</h2><p>The numbers behind the overview, for anyone who wants to dig in. Click any country for its own charts.</p></div>
      <div class="kpis" id="kpis"></div>
      <section class="block">
        <div class="block-head"><h3>Country ledger</h3><p>Click a row for details, a column to sort. "Anomaly" is a robust z-score: how far the last full day sits from the country's usual level, in units of typical day-to-day variation. Above +2 is unusual, above +3 a spike.</p></div>
        <div class="ledger-wrap"><table class="ledger" id="ledger"></table></div>
      </section>
      <section class="block">
        <div class="block-head"><h3>Ninety days at a glance</h3><p>Daily share of world coverage, full days only. The shaded band is the usual range (rolling 28-day median ± 2 robust SDs, adjusted for day of week); orange dots are days above it.</p></div>
        <div class="panel"><div class="small-multiples" id="multiples"></div></div>
      </section>
      <section class="block">
        <div class="block-head"><h3>How each crisis is framed</h3><p>Last 7 days. Right means more violence-heavy coverage; up means more coverage of meetings, negotiations and agreements (mostly routine diplomacy, which is why Gulf states sit high). Circle area follows coverage volume.</p></div>
        <div class="grid2"><div class="panel chart" id="scatter"></div><div class="panel chart" id="toneRank"></div></div>
      </section>
      <section class="block">
        <div class="block-head"><h3>Wire</h3><p>Every headline from the latest update, newest first. "Other outlets" are GDELT's most-covered stories, with titles rebuilt from web addresses; only English titles that name the country are kept.</p></div>
        <div class="panel">
          <div class="wire-tools">
            <select id="wireCountry" aria-label="Filter by country"><option value="all">All countries</option>${S.data.countries.map((c) => `<option value="${c.iso3}">${esc(c.name)}</option>`).join("")}</select>
            <div class="seg" id="wireKind" role="group" aria-label="Source"><button data-kind="all" aria-pressed="true">All</button><button data-kind="news" aria-pressed="false">Google News</button><button data-kind="gdelt" aria-pressed="false">Other outlets</button></div>
          </div>
          <ul class="wire" id="wire"></ul>
          <button class="more" id="wireMore">Show 40 more</button>
        </div>
      </section>
      <section class="block"><div class="block-head"><h3>Method in full</h3></div><div class="panel method">${methodHtml()}</div></section>`;
    $("#wireKind").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S.wireKind = b.dataset.kind; S.wireN = 40; pressed("#wireKind", b); renderWire(); });
    $("#wireCountry").addEventListener("change", (e) => { S.wireCountry = e.target.value; S.wireN = 40; renderWire(); });
    $("#wireMore").addEventListener("click", () => { S.wireN += 40; renderWire(); });
    el.dataset.built = "1";
  }
  renderKpis(); renderLedger(); renderMultiples(); renderScatter(); renderWire();
}
function methodHtml() {
  const m = S.data.method || {};
  return `<p><b>Coverage.</b> Every 15 minutes GDELT machine-codes world news (English plus about 65 translated languages) into events: who did what to whom, where, and how many articles reported it. A country's coverage is the article count of events located in it or involving its government, groups or people. One article can report several events, so the unit is article mentions.</p>
    <p><b>Share</b> divides coverage by all coverage GDELT coded worldwide that day, per 10,000, so it stays comparable when global news volume swings. <b>Anomaly</b> is a robust z-score for the last full day: share minus the median of the previous 28 days, divided by 1.4826 × the median absolute deviation, after removing each country's usual weekday pattern. The plain-language levels map onto it: below −2 "unusually little", −2 to −1 "a little less", −1 to +1 "usual", +1 to +2 "a little more", +2 to +3 "more", above +3 "much more attention than usual". Today's partial figure is never judged.</p>
    <p><b>Tone</b> is GDELT's article-weighted average tone (roughly −10 to +10). <b>Violence</b> is the share of coverage about CAMEO event types ${esc((m.violence_roots || []).join(", "))} (assault, armed clashes, mass violence). <b>Diplomatic activity</b> is the share about CAMEO ${esc((m.diplomacy_bases || []).join(", "))}: appeals and intent to negotiate or mediate, mediation, negotiation, signing agreements, de-escalation and ceasefires. It is dominated by routine meetings and visits, so it is not a measure of peace-process progress; an earlier "peace talk" and "mediation" label overstated it and was dropped.</p>
    <p><b>Stories and topics</b> come from Google News (UK English edition), searched every few hours per country for the past two and seven days. Headlines that don't name the country, its capital, people or main actors are dropped, as are sport, weather, market and earthquake-bulletin items. Headlines sharing enough distinctive words are grouped into one story and ranked by how many outlets carried them. Topics are keyword-tagged per headline. Finished weeks are searched again with a date range so the weekly report covers the whole week.</p>
    <p><b>Caveats.</b> GDELT over-weights online and wire-syndicated outlets and its coding misfires on some stories; compare a country with its own history rather than ranking levels across countries. Coverage of a country includes events elsewhere involving its actors (an Iranian minister in Geneva counts for Iran).</p>`;
}
function renderKpis() {
  const cs = visible().filter((c) => c.metrics && Object.keys(c.metrics).length);
  const above = cs.filter((c) => c.metrics.z_attention >= 2);
  const top = [...cs].sort((a, b) => (b.metrics.share_7d || 0) - (a.metrics.share_7d || 0))[0];
  const riser = [...cs].filter((c) => c.metrics.share_change_7d_pct != null).sort((a, b) => b.metrics.share_change_7d_pct - a.metrics.share_change_7d_pct)[0];
  const viol = [...cs].filter((c) => c.metrics.violence_share_7d != null).sort((a, b) => b.metrics.violence_share_7d - a.metrics.violence_share_7d)[0];
  const dark = [...cs].filter((c) => c.metrics.tone_delta != null).sort((a, b) => a.metrics.tone_delta - b.metrics.tone_delta)[0];
  const k = (v, l, s) => `<div class="kpi"><div class="v num">${v}</div><div class="l">${l}</div><div class="s">${s}</div></div>`;
  $("#kpis").innerHTML = [
    k(above.length, "Above usual range", above.length ? esc(above.map((c) => c.name).join(", ")) : "nobody above +2 on the last full day"),
    k(top ? esc(top.name) : "–", "Most covered", top ? `${f1(top.metrics.share_7d)} per 10k articles, 7 days` : ""),
    k(riser ? esc(riser.name) : "–", "Fastest riser", riser ? `share ${pct(riser.metrics.share_change_7d_pct)} week on week` : ""),
    k(viol ? esc(viol.name) : "–", "Most violence-heavy", viol ? `${f0(viol.metrics.violence_share_7d)}% of coverage` : ""),
    k(dark ? esc(dark.name) : "–", "Tone darkened most", dark ? `${sgn(dark.metrics.tone_delta, 2)} vs prior 30 days` : ""),
    k(f0(S.data.run?.history_days), "Days of history", "kept indefinitely; see the Excel file"),
  ].join("");
}

const COLS = [
  { key: "name", label: "Country", get: (c) => c.name, cell: (c) => `<span class="tier ${c.tier}" title="${tierLabel(c.tier)}"></span>${esc(c.name)}${(c.flags || []).some((f) => f.level !== "info" && f.level !== "low") ? `<span class="flagdot" title="${esc(c.flags.map((f) => f.text).join("; "))}"></span>` : ""}<span class="reg">${esc(c.region)}${c.pending ? ", metrics loading" : ""}</span>`, cls: "c" },
  { key: "share", label: "Last full day<br>per 10k", get: (c) => c.metrics?.share_latest, cell: (c) => f1(c.metrics?.share_latest) },
  { key: "z", label: "Anomaly<br>robust z", get: (c) => c.metrics?.z_attention, cell: (c) => `<span class="zbar"><span class="num ${c.metrics?.z_attention >= 2 ? "hot" : ""}">${sgn(c.metrics?.z_attention)}</span>${zBar(c.metrics?.z_attention)}</span>` },
  { key: "pctile", label: "90-day<br>percentile", get: (c) => c.metrics?.attention_pctile_90d, cell: (c) => f0(c.metrics?.attention_pctile_90d) },
  { key: "a7", label: "Coverage<br>7 days", get: (c) => c.metrics?.articles_7d, cell: (c) => f0(c.metrics?.articles_7d) },
  { key: "ch7", label: "Share, week<br>on week", get: (c) => c.metrics?.share_change_7d_pct, cell: (c) => `<span class="${c.metrics?.share_change_7d_pct > 0 ? "up" : c.metrics?.share_change_7d_pct < 0 ? "down" : ""}">${pct(c.metrics?.share_change_7d_pct)}</span>` },
  { key: "trend", label: "30-day trend<br>per week", get: (c) => c.metrics?.trend_30d_pct_per_week, cell: (c) => pct(c.metrics?.trend_30d_pct_per_week) },
  { key: "tone", label: "Tone<br>7 days", get: (c) => c.metrics?.tone_7d, cell: (c) => `${sgn(c.metrics?.tone_7d, 2)} <span class="faint" style="font-size:12px">${c.metrics?.tone_delta != null ? "(" + sgn(c.metrics.tone_delta, 1) + ")" : ""}</span>` },
  { key: "viol", label: "Violence<br>share", get: (c) => c.metrics?.violence_share_7d, cell: (c) => c.metrics?.violence_share_7d == null ? "–" : f0(c.metrics.violence_share_7d) + "%" },
  { key: "dipl", label: "Diplomatic<br>activity", get: (c) => c.metrics?.peace_share_7d, cell: (c) => c.metrics?.peace_share_7d == null ? "–" : f0(c.metrics.peace_share_7d) + "%" },
  { key: "spark", label: "90 days", get: () => 0, cell: (c) => sparkline((c.series || []).map((p) => p.s), 120, 26, c.metrics?.z_attention >= 2), nosort: true },
];
function renderLedger() {
  const col = COLS.find((c) => c.key === S.sort.key);
  const rows = visible().slice().sort((a, b) => {
    const x = col.get(a), y = col.get(b);
    if (x == null) return 1; if (y == null) return -1;
    return (typeof x === "string" ? x.localeCompare(y) : x - y) * S.sort.dir;
  });
  $("#ledger").innerHTML = `<thead><tr>${COLS.map((c) => `<th scope="col" ${c.key === S.sort.key ? `aria-sort="${S.sort.dir < 0 ? "descending" : "ascending"}"` : ""}>${c.nosort ? c.label : `<button data-sort="${c.key}">${c.label}</button>`}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((c) => `<tr data-iso="${c.iso3}" tabindex="0">${COLS.map((k) => `<td class="${k.cls || "num"}">${k.cell(c)}</td>`).join("")}</tr>`).join("") ||
      `<tr><td colspan="${COLS.length}" class="empty">No countries match "${esc(S.q)}". Clear the search to see all.</td></tr>`}</tbody>`;
  $("#ledger").onclick = (e) => {
    const s = e.target.closest("button[data-sort]");
    if (s) { const k = s.dataset.sort; S.sort = { key: k, dir: S.sort.key === k ? -S.sort.dir : k === "name" ? 1 : -1 }; renderLedger(); return; }
    const tr = e.target.closest("tr[data-iso]"); if (tr) openCountry(tr.dataset.iso);
  };
  $("#ledger").onkeydown = (e) => { const tr = e.target.closest("tr[data-iso]"); if (tr && e.key === "Enter") openCountry(tr.dataset.iso); };
}

function renderMultiples() {
  const order = [...new Set(S.data.countries.map((c) => c.region))];
  const cs = visible().slice().sort((a, b) => order.indexOf(a.region) - order.indexOf(b.region) || (b.metrics?.share_7d || 0) - (a.metrics?.share_7d || 0));
  $("#multiples").innerHTML = cs.map((c) => {
    const vals = (c.series || []).map((p) => p.s), band = bandOf(c.series || []);
    const W = 220, H = 64, n = vals.length; const ok = vals.concat(band.flatMap((b) => (b ? [b.hi] : []))).filter((v) => v != null);
    if (n < 2 || !ok.length) return "";
    const max = Math.max(...ok) * 1.05, X = (i) => (i / (n - 1)) * W, Y = (v) => H - 2 - (v / max) * (H - 6);
    let top = "", line = "", dots = ""; const bot = [];
    band.forEach((b, i) => { if (!b) return; top += (top ? "L" : "M") + X(i).toFixed(1) + "," + Y(b.hi).toFixed(1); bot.unshift(X(i).toFixed(1) + "," + Y(b.lo).toFixed(1)); });
    vals.forEach((v, i) => { if (v == null) return; line += (line ? "L" : "M") + X(i).toFixed(1) + "," + Y(v).toFixed(1); if (band[i] && v > band[i].hi) dots += `<circle cx="${X(i)}" cy="${Y(v)}" r="2.4" fill="var(--signal)"/>`; });
    const m = c.metrics || {};
    return `<button class="sm" data-iso="${c.iso3}">
      <h4>${esc(c.name)} <span class="num ${m.z_attention >= 2 ? "hot" : "faint"}" style="font-weight:600">${sgn(m.z_attention)}</span></h4>
      <div class="meta">${esc(c.region)}, ${f1(m.share_7d)} per 10k this week</div>
      <svg viewBox="0 0 ${W} ${H}" width="100%" aria-hidden="true">${top ? `<path d="${top}L${bot.join("L")}Z" fill="var(--attn-0)"/>` : ""}<path d="${line}" fill="none" stroke="var(--attn-2)" stroke-width="1.4"/>${dots}</svg></button>`;
  }).join("") || `<p class="empty">No countries match the filter.</p>`;
  $("#multiples").onclick = (e) => { const b = e.target.closest("[data-iso]"); if (b) openCountry(b.dataset.iso); };
}

function renderScatter() {
  const cs = visible().filter((c) => c.metrics?.violence_share_7d != null && c.metrics?.peace_share_7d != null);
  if (!cs.length) { $("#scatter").innerHTML = `<p class="empty">No framing data yet.</p>`; $("#toneRank").innerHTML = ""; return; }
  const W = 620, H = 420, L = 44, R = 16, T = 14, B = 36;
  const xs = cs.map((c) => c.metrics.violence_share_7d), ys = cs.map((c) => c.metrics.peace_share_7d);
  const xmax = Math.max(...xs) * 1.1 || 1, ymax = Math.max(...ys) * 1.15 || 1, amax = Math.max(...cs.map((c) => c.metrics.articles_7d || 0)) || 1;
  const X = (v) => L + (v / xmax) * (W - L - R), Y = (v) => H - B - (v / ymax) * (H - T - B);
  const xm = xs.reduce((a, b) => a + b) / xs.length, ym = ys.reduce((a, b) => a + b) / ys.length;
  let g = "";
  for (let k = 0; k <= 4; k++) { const vx = (xmax * k) / 4, vy = (ymax * k) / 4;
    g += `<line class="grid" x1="${X(vx)}" x2="${X(vx)}" y1="${T}" y2="${H - B}"/><text x="${X(vx)}" y="${H - B + 14}" text-anchor="middle">${f0(vx)}%</text>`;
    g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(vy)}" y2="${Y(vy)}"/><text x="${L - 6}" y="${Y(vy) + 3.5}" text-anchor="end">${f0(vy)}%</text>`; }
  g += `<line x1="${X(xm)}" x2="${X(xm)}" y1="${T}" y2="${H - B}" stroke="var(--ink-3)" stroke-dasharray="2 3"/><line x1="${L}" x2="${W - R}" y1="${Y(ym)}" y2="${Y(ym)}" stroke="var(--ink-3)" stroke-dasharray="2 3"/>`;
  g += `<text x="${W - R}" y="${H - 4}" text-anchor="end">violence share →</text><text x="${L}" y="${T - 2}" >↑ diplomatic activity</text>`;
  const pts = cs.sort((a, b) => (b.metrics.articles_7d || 0) - (a.metrics.articles_7d || 0)).map((c) => {
    const r = 4 + 18 * Math.sqrt((c.metrics.articles_7d || 0) / amax), x = X(c.metrics.violence_share_7d), y = Y(c.metrics.peace_share_7d);
    const hot = c.metrics.z_attention >= 2;
    return `<g class="pt" data-iso="${c.iso3}"><circle cx="${x}" cy="${y}" r="${r}" fill="${hot ? "var(--signal)" : "var(--attn-2)"}" fill-opacity=".35" stroke="${hot ? "var(--signal)" : "var(--attn-2)"}"><title>${esc(c.name)}: ${f0(c.metrics.violence_share_7d)}% violence, ${f0(c.metrics.peace_share_7d)}% diplomatic activity</title></circle><text class="lab" x="${x}" y="${y - r - 3}" text-anchor="middle">${esc(c.name)}</text></g>`;
  }).join("");
  $("#scatter").innerHTML = `<h3>Violence versus diplomatic activity</h3><svg viewBox="0 0 ${W} ${H}">${g}${pts}</svg>`;
  $("#scatter").onclick = (e) => { const p = e.target.closest(".pt"); if (p) openCountry(p.dataset.iso); };

  const ts = visible().filter((c) => c.metrics?.tone_7d != null).sort((a, b) => a.metrics.tone_7d - b.metrics.tone_7d);
  const rowH = 17, H2 = T + ts.length * rowH + 30, W2 = 560, L2 = 130;
  const tv = ts.flatMap((c) => [c.metrics.tone_7d, c.metrics.tone_prev30d]).filter((v) => v != null);
  const tmin = Math.floor(Math.min(...tv)), tmax = Math.ceil(Math.max(...tv, -1));
  const TX = (v) => L2 + ((v - tmin) / (tmax - tmin || 1)) * (W2 - L2 - 16);
  let t = "";
  for (let v = tmin; v <= tmax; v++) t += `<line class="grid" x1="${TX(v)}" x2="${TX(v)}" y1="${T}" y2="${H2 - 22}"/><text x="${TX(v)}" y="${H2 - 8}" text-anchor="middle">${v}</text>`;
  ts.forEach((c, i) => {
    const y = T + i * rowH + 8, a = c.metrics.tone_prev30d, b = c.metrics.tone_7d, worse = a != null && b < a;
    t += `<g class="pt" data-iso="${c.iso3}"><text x="${L2 - 8}" y="${y + 3.5}" text-anchor="end" class="lab">${esc(c.name)}</text>`;
    if (a != null) t += `<line x1="${TX(a)}" x2="${TX(b)}" y1="${y}" y2="${y}" stroke="${worse ? "var(--neg)" : "var(--pos)"}" stroke-width="2"/><circle cx="${TX(a)}" cy="${y}" r="2.5" fill="var(--ink-3)"/>`;
    t += `<circle cx="${TX(b)}" cy="${y}" r="4" fill="${worse ? "var(--neg)" : "var(--pos)"}"><title>${esc(c.name)}: ${sgn(b, 2)} (was ${sgn(a, 2)})</title></circle></g>`;
  });
  $("#toneRank").innerHTML = `<h3>Tone, grimmest first <small>grey dot is the prior 30 days, coloured dot the last 7</small></h3><svg viewBox="0 0 ${W2} ${H2}">${t}</svg>`;
  $("#toneRank").onclick = (e) => { const p = e.target.closest(".pt"); if (p) openCountry(p.dataset.iso); };
}

function wireItems() {
  const items = [];
  S.data.countries.forEach((c) => {
    if (!inTier(c)) return;
    if (S.wireCountry !== "all" && c.iso3 !== S.wireCountry) return;
    if (S.wireKind !== "gdelt") (c.headlines || []).forEach((h) => items.push({ c, title: h.title, url: h.url, src: h.source, when: h.published, kind: "news" }));
    if (S.wireKind !== "news") (c.gdelt?.articles || []).forEach((a) => items.push({ c, title: a.title, url: a.url, src: a.domain, when: a.seen, kind: "gdelt", from: a.mentions ? `${a.mentions} articles` : "" }));
  });
  const seen = new Set();
  return items.filter((i) => qMatch(i.title, i.c.name, i.src))
    .sort((a, b) => (b.when || "").localeCompare(a.when || ""))
    .filter((i) => { const k = i.title.toLowerCase().slice(0, 70); if (seen.has(k)) return false; seen.add(k); return true; });
}
function renderWire() {
  const all = wireItems(), items = all.slice(0, S.wireN);
  $("#wire").innerHTML = items.map((i) => `<li><button class="chip" data-iso="${i.c.iso3}" title="Open ${esc(i.c.name)}">${esc(i.c.name)}</button><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a>
    <div class="meta">${esc(i.src)}${i.from ? `, ${esc(i.from)}` : ""}, ${ago(i.when)}</div></li>`).join("") || `<li class="empty">No headlines match. Try another country or clear the search.</li>`;
  $("#wireMore").hidden = all.length <= S.wireN;
  $("#wire").onclick = (e) => { const b = e.target.closest(".chip"); if (b) openCountry(b.dataset.iso); };
}

/* ---------------- country drawer ---------------- */
const staleNews = (at) => (at && new Date(S.data.generated_at) - new Date(at) > 36e5
  ? `<p class="stale-note">Google News didn't answer in the latest update; these are from ${ago(at)}.</p>` : "");
let lastFocus = null;
function openCountry(iso) {
  const c = byIso(iso); if (!c) return;
  S.open = iso; lastFocus = document.activeElement;
  if (location.hash !== "#/" + iso) history.replaceState(null, "", "#/" + iso);
  const m = c.metrics || {}, ser = c.series || [], dates = ser.map((p) => p.d), r = c.recent || {};
  const shares = ser.map((p) => p.s), band = bandOf(ser);
  const marks = shares.map((v, i) => (band[i] && v != null && v > band[i].hi ? i : -1)).filter((i) => i >= 0);
  const tone = ser.map((p) => p.t), viol = rollingRatio(ser, "v", "n"), dipl = rollingRatio(ser, "p", "n");
  const kp = (v, l, s = "") => `<div class="kpi"><div class="v num">${v}</div><div class="l">${l}</div>${s ? `<div class="s">${s}</div>` : ""}</div>`;
  const gq = encodeURIComponent(c.gdelt || c.name), nq = encodeURIComponent(c.news || c.name);
  const d = $("#drawer");
  const cw = Math.max(320, Math.min(660, Math.min(innerWidth, 760) - 70));
  const ch = (h) => Math.round(h * (cw < 500 ? 1.15 : 1));
  const others = c.gdelt?.articles || [];
  d.innerHTML = `<div class="d-head"><div><h2 id="dTitle">${esc(c.name)}</h2>
      <div class="sub">${esc(c.region)}, ${tierLabel(c.tier).toLowerCase()}. ${pill(c.attention)}</div></div>
      <button class="close" id="dClose" aria-label="Close">×</button></div>
    <div class="d-body">
      <div class="panel"><p class="summary big-summary">${esc((c.summary || []).join(" "))}</p>
        ${(c.flags || []).filter((f) => !/attention/.test(f.text)).map((f) => `<div class="flag ${f.level}">${esc(f.text)}</div>`).join("")}
        ${m.today_share != null ? `<p class="faint small">Today so far (${f1(m.today_hours)} hours of data): ${f1(m.today_share)} per 10,000 articles. Part-days aren't judged because they depend on which time zones are awake.</p>` : ""}</div>
      <div class="panel"><h3>Main stories <small>last 7 days, Google News, grouped by event</small></h3>${staleNews(c.headlines_at)}${storyList(r.stories, { max: 6, also: true })}</div>
      <div class="panel"><h3>What the coverage is about <small>${f0(r.n)} headlines, last 7 days</small></h3>${themeBars(r.themes, r.n)}${namesLine(r.names)}</div>
      <div class="panel chart"><h3>Attention over 90 days <small>share of world news per 10,000 articles; shaded band = usual range; orange = unusually high days</small></h3>${tsChart({ dates, lines: [{ vals: shares, color: "var(--attn-2)" }], band, marks, zero: true, width: cw, height: ch(180) })}</div>
      <div class="d-kpis">
        ${kp(`<span class="${m.z_attention >= 2 ? "hot" : ""}">${sgn(m.z_attention)}</span>`, "Anomaly (robust z)", `${f0(m.attention_pctile_90d)}th percentile of 90 days`)}
        ${kp(f1(m.share_latest), `Share on ${m.latest_day ? dayLabel(m.latest_day) : "last day"}`, `${f0(m.articles_latest)} article mentions`)}
        ${kp(pct(m.share_change_7d_pct), "Share, week on week", `${f0(m.articles_7d)} mentions in 7 days`)}
        ${kp(pct(m.trend_30d_pct_per_week), "30-day trend", "share, per week")}
        ${kp(sgn(m.tone_7d, 2), "Tone, 7 days", `${sgn(m.tone_delta, 2)} vs prior 30 days`)}
        ${kp(m.violence_share_7d == null ? "–" : f0(m.violence_share_7d) + "%", "Violence in coverage", `was ${f0(m.violence_share_prev30d)}%`)}
        ${kp(m.peace_share_7d == null ? "–" : f0(m.peace_share_7d) + "%", "Diplomatic activity", `was ${f0(m.peace_share_prev30d)}%`)}
        ${kp(f0(m.articles_90d), "Mentions, 90 days", "all languages")}
      </div>
      <div class="panel chart"><h3>Tone <small>daily (thin) and 7-day average; line = prior 30 days</small></h3>${tsChart({ dates, lines: [{ vals: tone, color: "var(--ink-3)", width: 1 }, { vals: rollingMean(tone), color: "var(--neg)", width: 2 }], height: ch(150), width: cw, yfmt: (v) => v.toFixed(1), refLine: m.tone_prev30d })}</div>
      <div class="panel chart"><h3>Framing <small>7-day rolling share of coverage: <span style="color:var(--neg)">violence</span>, <span style="color:var(--pos)">diplomatic activity</span></small></h3>${tsChart({ dates, lines: [{ vals: viol, color: "var(--neg)" }, { vals: dipl, color: "var(--pos)" }], height: ch(150), width: cw, yfmt: (v) => f0(v) + "%", zero: true })}</div>
      <div class="panel"><h3>Latest headlines <small>Google News, newest first</small></h3>
        ${(c.headlines || []).length ? `<ul class="list">${c.headlines.slice(0, 15).map((h) => `<li><a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a><div class="meta">${esc(h.source)}, ${ago(h.published)}</div></li>`).join("")}</ul>` : `<p class="empty">No headlines in this update.</p>`}</div>
      <details class="panel"><summary><h3>Other outlets <small>${others.length} most-covered GDELT stories, last 3 days</small></h3></summary>
        <p class="faint small">Titles are rebuilt from web addresses because GDELT doesn't publish headlines; only English ones naming ${esc(c.name)} are kept.</p>
        ${others.length ? `<ul class="list">${others.slice(0, 25).map((a) => `<li><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a><div class="meta">${esc(a.domain)}${a.kind ? `, ${esc(a.kind.toLowerCase())}` : ""}, ${a.mentions} ${a.mentions === 1 ? "article" : "articles"}, ${ago(a.seen)}</div></li>`).join("")}</ul>` : `<p class="empty">None in this update.</p>`}</details>
      <details class="panel"><summary><h3>Outlets and event types <small>GDELT</small></h3></summary>
        <div class="grid2"><div><h4>Top outlets <small>most-covered stories, 3 days</small></h4>${bars(c.gdelt?.top_domains)}</div>
        <div><h4>What is being reported <small>machine-coded event types, 7 days</small></h4>${bars(c.gdelt?.event_mix)}</div></div></details>
      <div class="panel"><h3>Go deeper</h3><div class="links">
        <a href="https://news.google.com/search?q=${nq}&hl=en-GB&gl=GB&ceid=GB:en" target="_blank" rel="noopener">Google News search</a>
        <a href="https://reliefweb.int/country/${c.iso3.toLowerCase()}" target="_blank" rel="noopener">ReliefWeb</a>
        <a href="https://www.crisisgroup.org/crisiswatch/database" target="_blank" rel="noopener">CrisisWatch</a>
        <a href="https://acleddata.com/conflict-data/" target="_blank" rel="noopener">ACLED</a>
        <a href="https://api.gdeltproject.org/api/v2/doc/doc?query=${gq}&mode=artlist&maxrecords=250&timespan=1d&sort=datedesc" target="_blank" rel="noopener">GDELT live article list</a>
        <a href="https://api.gdeltproject.org/api/v2/doc/doc?query=${gq}&mode=timelinevol&timespan=1y" target="_blank" rel="noopener">GDELT 12-month timeline</a>
      </div></div>
    </div>`;
  d.classList.add("open"); d.setAttribute("aria-hidden", "false"); $("#scrim").classList.add("open");
  document.body.style.overflow = "hidden"; d.scrollTop = 0; $("#dClose").onclick = closeCountry; $("#dClose").focus();
}
function closeCountry() {
  S.open = null; const d = $("#drawer");
  d.classList.remove("open"); d.setAttribute("aria-hidden", "true"); $("#scrim").classList.remove("open"); document.body.style.overflow = "";
  history.replaceState(null, "", "#" + S.tab);
  if (lastFocus) lastFocus.focus();
}

/* ---------------- wiring ---------------- */
function route() {
  const h = location.hash.replace("#", "");
  if (h.startsWith("/")) { const iso = h.slice(1); if (byIso(iso)) openCountry(iso); return; }
  if (S.open) closeCountry();
  setTab(TABS.includes(h) ? h : S.tab, false);
}

function initControls() {
  $("#tierSeg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S.tier = b.dataset.tier; pressed("#tierSeg", b); renderTab(); });
  let t; $("#search").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { S.q = e.target.value.trim().toLowerCase(); S.eipN = 50; renderTab(); }, 150); });
  document.querySelector(".tabs-nav").addEventListener("click", (e) => { const a = e.target.closest("a[data-tab]"); if (!a) return; e.preventDefault(); if (S.open) closeCountry(); setTab(a.dataset.tab); scrollTo({ top: 0 }); });
  $("#scrim").addEventListener("click", closeCountry);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.open) closeCountry(); });
  window.addEventListener("hashchange", route);
  const root = document.documentElement;
  let theme = null; try { theme = localStorage.getItem("cmm-theme"); } catch (_) {}
  if (theme) root.dataset.theme = theme;
  $("#themeBtn").addEventListener("click", () => {
    const cur = root.dataset.theme || "auto", next = cur === "auto" ? "dark" : cur === "dark" ? "light" : "auto";
    if (next === "auto") delete root.dataset.theme; else root.dataset.theme = next;
    try { next === "auto" ? localStorage.removeItem("cmm-theme") : localStorage.setItem("cmm-theme", next); } catch (_) {}
    $("#themeBtn").textContent = "Theme: " + next; renderMap(); if (S.open) openCountry(S.open);
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => renderMap());
}

async function boot() {
  initControls();
  try {
    const [data, world] = await Promise.all([
      loadJSON("data/latest.json"),
      fetch("assets/vendor/countries-50m.json").then((r) => r.json()).catch(() => null),
    ]);
    S.data = data; S.world = world;
  } catch (err) {
    $("#tab-overview").innerHTML = `<div class="error"><h2>No data yet</h2><p>The first data run hasn't finished. Open the repository's Actions tab, run "Update media data", and reload this page in about 15 minutes.</p></div>`;
    $("#stamp").textContent = "Waiting for the first data run.";
    return;
  }
  renderStamp(); renderFooter();
  const h = location.hash.replace("#", "");
  setTab(TABS.includes(h) ? h : "overview", false);
  if (h.startsWith("/") && byIso(h.slice(1))) openCountry(h.slice(1));
}
boot();
})();
