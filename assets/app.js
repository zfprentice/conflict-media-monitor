/* Conflict Media Monitor — front end. Vanilla JS, no build step.
   Reads data/latest.json (written by build_data.py in GitHub Actions). */
(() => {
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const TZ = "Europe/Brussels";

const S = {
  data: null, world: null, metric: "z", tier: "all", q: "",
  sort: { key: "z", dir: -1 }, wireCountry: "all", wireKind: "all", wireN: 40, open: null,
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
  const m = (Date.now() - new Date(iso).getTime()) / 60000;
  if (m < 1) return "just now";
  if (m < 60) return `${Math.round(m)} min ago`;
  if (m < 60 * 24) return `${Math.round(m / 60)} h ago`;
  return `${Math.round(m / 1440)} d ago`;
}
const dayLabel = (d) => new Date(d + "T12:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const stampFmt = (iso) => new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: TZ });
const tierLabel = (t) => (t === "operates" ? "Field presence" : "Regional dialogue");

/* ---------------- colour ---------------- */
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
function hex2rgb(h) { h = h.replace("#", ""); if (h.length === 3) h = h.split("").map((c) => c + c).join(""); const n = parseInt(h, 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; }
function mix(a, b, t) { const A = hex2rgb(a), B = hex2rgb(b); t = Math.max(0, Math.min(1, t)); return `rgb(${A.map((v, i) => Math.round(v + (B[i] - v) * t)).join(",")})`; }
function ramp(stops, t) { // stops: array of hex, t in [0,1]
  if (t == null || Number.isNaN(t)) return css("--land");
  t = Math.max(0, Math.min(1, t)); const seg = (stops.length - 1) * t; const i = Math.min(Math.floor(seg), stops.length - 2);
  return mix(stops[i], stops[i + 1], seg - i);
}

/* Map/table metrics */
const METRICS = {
  z: {
    label: "Anomaly", long: "Coverage on the last full day vs its own 28-day baseline, adjusted for day of week (robust z-score)",
    get: (c) => c.metrics?.z_attention, fmt: (x) => sgn(x),
    color: (x) => x == null ? null : x < 0 ? ramp([css("--neutral"), css("--ink-3")], -x / 3) : ramp([css("--neutral"), css("--attn-1"), css("--attn-2"), css("--attn-3")], x / 4),
    legend: () => ({ grad: [css("--ink-3"), css("--neutral"), css("--attn-1"), css("--attn-2"), css("--attn-3")], lo: "−3 quiet", hi: "+4 spike" }),
  },
  share: {
    label: "Share", long: "Share of all news coverage GDELT coded worldwide, per 10,000, last 7 days",
    get: (c) => c.metrics?.share_7d, fmt: (x) => f1(x),
    color: (x, ext) => x == null ? null : ramp([css("--attn-0"), css("--attn-1"), css("--attn-2"), css("--attn-3")], Math.log(x / ext.min) / Math.log(ext.max / ext.min || 2)),
    legend: (ext) => ({ grad: [css("--attn-0"), css("--attn-1"), css("--attn-2"), css("--attn-3")], lo: f1(ext.min), hi: f1(ext.max) + " per 10k" }),
  },
  tone: {
    label: "Tone", long: "Average GDELT tone of coverage, last 7 days (negative = hostile/grim)",
    get: (c) => c.metrics?.tone_7d, fmt: (x) => sgn(x, 2),
    color: (x) => x == null ? null : x < -2.5 ? ramp([css("--neutral"), css("--neg")], (-2.5 - x) / 3.5) : ramp([css("--neutral"), css("--pos")], (x + 2.5) / 3),
    legend: () => ({ grad: [css("--neg"), css("--neutral"), css("--pos")], lo: "−6 grim", hi: "+0.5" }),
  },
  violence: {
    label: "Violence", long: "Share of a country's coverage about assaults, armed clashes or mass violence (7 days)",
    get: (c) => c.metrics?.violence_share_7d, fmt: (x) => f0(x) + "%",
    color: (x) => x == null ? null : ramp([css("--neutral"), css("--neg")], x / 70),
    legend: () => ({ grad: [css("--neutral"), css("--neg")], lo: "0%", hi: "70%+" }),
  },
  peace: {
    label: "Peace talk", long: "Share of coverage about negotiations, mediation, agreements or ceasefires (7 days)",
    get: (c) => c.metrics?.peace_share_7d, fmt: (x) => f0(x) + "%",
    color: (x) => x == null ? null : ramp([css("--neutral"), css("--pos")], x / 40),
    legend: () => ({ grad: [css("--neutral"), css("--pos")], lo: "0%", hi: "40%+" }),
  },
  mediation: {
    label: "Mediation", long: "Share of coverage about mediation: calls for it, offers to mediate, accepting it or mediating (7 days)",
    get: (c) => c.metrics?.mediation_share_7d, fmt: (x) => f1(x) + "%",
    color: (x) => x == null ? null : ramp([css("--neutral"), css("--pos")], x / 8),
    legend: () => ({ grad: [css("--neutral"), css("--pos")], lo: "0%", hi: "8%+" }),
  },
};

/* ---------------- data helpers ---------------- */
const visible = () => S.data.countries.filter((c) => (S.tier === "all" || c.tier === S.tier) &&
  (!S.q || c.name.toLowerCase().includes(S.q) || c.region.toLowerCase().includes(S.q)));
const byIso = (iso) => S.data.countries.find((c) => c.iso3 === iso);
// Expected range per day, computed by the pipeline (weekday-adjusted 28-day median ± 2 robust SDs).
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

/* ---------------- SVG charts ---------------- */
function sparkline(vals, w = 110, h = 26, hot = false) {
  const v = vals.map((x) => (x == null ? null : x)); const ok = v.filter((x) => x != null);
  if (ok.length < 2) return "";
  const max = Math.max(...ok), min = Math.min(...ok, 0);
  const X = (i) => (i / (v.length - 1)) * (w - 4) + 2, Y = (x) => h - 3 - ((x - min) / (max - min || 1)) * (h - 6);
  let d = "", a = "";
  v.forEach((x, i) => { if (x == null) return; d += (d ? "L" : "M") + X(i).toFixed(1) + "," + Y(x).toFixed(1); });
  a = d + `L${X(v.length - 1).toFixed(1)},${h}L${X(0)},${h}Z`;
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
    let top = "", bot = [];
    band.forEach((b, i) => { if (!b) return; top += (top ? "L" : "M") + X(i).toFixed(1) + "," + Y(b.hi).toFixed(1); bot.unshift(X(i).toFixed(1) + "," + Y(b.lo).toFixed(1)); });
    if (top) bandPath = `<path d="${top}L${bot.join("L")}Z" fill="var(--attn-0)" opacity=".7"/>`;
    let med = ""; band.forEach((b, i) => { if (b) med += (med ? "L" : "M") + X(i).toFixed(1) + "," + Y(b.med).toFixed(1); });
    if (med) bandPath += `<path d="${med}" fill="none" stroke="var(--attn-1)" stroke-dasharray="3 3" stroke-width="1"/>`;
  }
  const paths = lines.map((l) => { let d = ""; l.vals.forEach((v, i) => { if (v == null) { return; } d += (d ? "L" : "M") + X(i).toFixed(1) + "," + Y(v).toFixed(1); });
    return `<path d="${d}" fill="none" stroke="${l.color}" stroke-width="${l.width || 1.8}" ${l.dash ? `stroke-dasharray="${l.dash}"` : ""} stroke-linejoin="round"/>`; }).join("");
  const mk = marks.map((i) => `<circle cx="${X(i)}" cy="${Y(lines[0].vals[i])}" r="3.6" fill="var(--signal)" stroke="var(--panel)" stroke-width="1.2"><title>${dayLabel(dates[i])}: anomaly</title></circle>`).join("");
  const ref = refLine != null ? `<line x1="${L}" x2="${W - R}" y1="${Y(refLine)}" y2="${Y(refLine)}" stroke="var(--ink-3)" stroke-width="1"/>` : "";
  return `<svg viewBox="0 0 ${W} ${H}" role="img">${grid.join("")}${xt.join("")}${bandPath}${ref}${paths}${mk}</svg>`;
}

function bars(pairs) {
  if (!pairs?.length) return `<p class="empty">Not enough articles in the last 3 days.</p>`;
  const max = Math.max(...pairs.map((p) => p[1]));
  return `<div class="bars">${pairs.map(([k, v]) => `<div class="row"><span title="${esc(k)}">${esc(k)}</span><span class="track"><span class="fill" style="display:block;width:${(100 * v) / max}%"></span></span><span class="num faint">${v}</span></div>`).join("")}</div>`;
}

/* ---------------- render: masthead/footer ---------------- */
function renderStamp() {
  const d = S.data, r = d.run || {};
  const pending = d.countries.filter((c) => c.pending).length;
  const age = (Date.now() - new Date(d.generated_at)) / 36e5;
  const scored = d.method?.scored_day;
  $("#stamp").innerHTML = `Updated <b>${stampFmt(d.generated_at)}</b> Brussels time (${ago(d.generated_at)}), from GDELT event data and Google News.` +
    (scored ? ` Scores are for <b>${dayLabel(scored)}</b>, the last full day (UTC).` : "") +
    (r.news_failed ? ` <span class="stale-note">Google News didn't answer ${r.news_failed} of ${r.news_total} queries; those headlines are from an earlier run.</span>` : "") +
    (r.complete_days != null && r.complete_days < 35 ? ` <span class="stale-note">History is still backfilling (${r.complete_days} of 92 days so far), so baselines and anomaly scores firm up over the next few updates.</span>` : "") +
    (pending ? ` <span class="stale-note">No coverage yet for ${pending} ${pending === 1 ? "country" : "countries"}.</span>` : "") +
    (age > 7 ? ` <span class="stale-note">The scheduled update looks overdue.</span>` : "");
  document.title = `${d.site_title} — ${d.countries.length} countries`;
  $("#title").innerHTML = `Media attention across <span class="count">${d.countries.length}</span> countries`;
}

function renderFooter() {
  const r = S.data.run || {};
  $("#footer").innerHTML = `<div class="cols"><div>
    <h3>How to read this</h3>
    <p>Every 15 minutes GDELT machine-codes world news (in English and translated from about 65 languages) into events: who did what to whom, where, and how many articles reported it.
    A country's <b>coverage</b> is the article count of events located in it or involving its government, groups or people. Because one article can report several events, the unit is article mentions, not unique articles.</p>
    <p><b>Share</b> divides that coverage by all coverage GDELT coded worldwide the same day, so it stays comparable when global news volume swings.
    <b>Anomaly</b> is a robust z-score for the last full day: its share minus the median of the previous 28 days, divided by 1.4826 × the median absolute deviation, after removing each country's usual weekday pattern (Gulf coverage rises at weekends, Moldova's falls). Above +2 is unusual; above +3 is a spike.
    Today's partial figure is shown for context but never scored, because a part-day's share depends on which time zones have been awake.</p>
    <p><b>Tone</b> is GDELT's article-weighted average tone (roughly −10 to +10). <b>Violence</b> is the share of coverage about CAMEO event types 18–20 (assault, armed clashes, mass violence).
    <b>Peace talk</b> is the share about CAMEO 026–028, 036–039, 045, 046, 057 and 087 (appeals and intent to negotiate, settle or mediate, mediation, negotiation, signing agreements, de-escalation and ceasefires).
    <b>Mediation</b> is the narrower share about CAMEO 028, 038, 039 and 045 (calls for mediation, accepting or offering it, and mediating).</p>
    <p>Story titles in the long-tail lists come from article URLs, since GDELT doesn't publish headlines; mainstream headlines come from Google News. GDELT's automatic coding misfires on some stories, so lean on changes within a country more than exact levels.</p>
  </div><div>
    <h3>Data</h3>
    <dl><dt>Download</dt><dd><a href="data/latest.json">latest.json</a>, <a href="data/daily.csv">daily.csv</a> (per country per day, with event-type counts)</dd>
    <dt>Last run</dt><dd>${f0(r.slots_ingested)} new GDELT files in ${f0(r.seconds / 60)} min${r.slots_remaining ? `, ${f0(r.slots_remaining)} older ones queued` : ""}</dd>
    <dt>Schedule</dt><dd>Every 3 hours via GitHub Actions</dd>
    <dt>Sources</dt><dd><a href="https://www.gdeltproject.org/data.html#rawdatafiles" rel="noopener">GDELT 2.0 event files</a>, <a href="https://news.google.com" rel="noopener">Google News</a></dd></dl>
  </div></div>`;
}

/* ---------------- render: hero ---------------- */
function renderShell() {
  $("#app").innerHTML = `
  <div class="hero">
    <div class="mapcard">
      <div class="map-head"><h2 id="mapTitle"></h2>
        <div class="seg" id="metricSeg" role="group" aria-label="Map metric">${Object.entries(METRICS).map(([k, m]) => `<button data-metric="${k}" aria-pressed="${k === S.metric}">${m.label}</button>`).join("")}</div>
      </div>
      <svg id="map" viewBox="0 0 1000 520" role="img" aria-label="Map of tracked countries"></svg>
      <div class="legend" id="legend"></div>
    </div>
    <div class="side">
      <div class="panel"><h2>Moving now <small>biggest anomalies</small></h2><ul class="movers" id="movers"></ul></div>
      <div class="panel watch" id="watch"></div>
    </div>
  </div>
  <div class="kpis" id="kpis"></div>

  <section class="block">
    <div class="block-head"><h2>Country ledger</h2><p>Click a row for charts, outlets and every link. Click a column to sort.</p></div>
    <div class="ledger-wrap"><table class="ledger" id="ledger"></table></div>
  </section>

  <section class="block">
    <div class="block-head"><h2>Ninety days at a glance</h2><p>Daily share of world coverage, full days only. Shaded band is the expected range (rolling 28-day median ± 2 MAD, adjusted for day of week); orange dots are days above it.</p></div>
    <div class="panel"><div class="small-multiples" id="multiples"></div></div>
  </section>

  <section class="block">
    <div class="block-head"><h2>How each crisis is framed</h2><p>Last 7 days. Right means more violence-heavy coverage, up means more talk of ceasefires and negotiations. Circle area follows article volume.</p></div>
    <div class="grid2">
      <div class="panel chart" id="scatter"></div>
      <div class="panel chart" id="toneRank"></div>
    </div>
  </section>

  <section class="block">
    <div class="block-head"><h2>Wire</h2><p>Every headline and article pulled in the latest run, newest first.</p></div>
    <div class="panel">
      <div class="wire-tools">
        <select id="wireCountry" aria-label="Filter by country"><option value="all">All countries</option></select>
        <div class="seg" id="wireKind" role="group" aria-label="Source type">
          <button data-kind="all" aria-pressed="true">All</button><button data-kind="news" aria-pressed="false">Mainstream</button><button data-kind="gdelt" aria-pressed="false">Long tail</button>
        </div>
      </div>
      <ul class="wire" id="wire"></ul>
      <button class="more" id="wireMore">Show 40 more</button>
    </div>
  </section>`;

  $("#metricSeg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S.metric = b.dataset.metric; pressed("#metricSeg", b); renderMap(); });
  $("#wireKind").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S.wireKind = b.dataset.kind; S.wireN = 40; pressed("#wireKind", b); renderWire(); });
  $("#wireCountry").innerHTML += S.data.countries.map((c) => `<option value="${c.iso3}">${esc(c.name)}</option>`).join("");
  $("#wireCountry").addEventListener("change", (e) => { S.wireCountry = e.target.value; S.wireN = 40; renderWire(); });
  $("#wireMore").addEventListener("click", () => { S.wireN += 40; renderWire(); });
}
function pressed(sel, btn) { document.querySelectorAll(sel + " button").forEach((b) => b.setAttribute("aria-pressed", b === btn)); }

/* ---------------- render: map ---------------- */
function renderMap() {
  const svg = $("#map"), m = METRICS[S.metric];
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
    html += `<path class="tracked ${vis.has(c.iso3) ? "" : "dim"}" data-iso="${c.iso3}" d="${path(f) || ""}" fill="${fill}" tabindex="0" role="button" aria-label="${esc(c.name)}: ${m.label} ${m.fmt(v)}"/>`;
    if (f.properties.name === c.atlas && (c.metrics?.z_attention ?? 0) >= 2 && vis.has(c.iso3)) {
      const [x, y] = path.centroid(f); if (!Number.isNaN(x)) pulses.push({ x, y, c });
    }
  });
  // Rings for every spike; labels placed greedily (biggest first), skipping or flipping on collision.
  const placed = [];
  pulses.sort((a, b) => b.c.metrics.z_attention - a.c.metrics.z_attention).forEach(({ x, y, c }) => {
    html += `<circle class="pulse" cx="${x}" cy="${y}" r="14"/><circle class="dot" cx="${x}" cy="${y}" r="4"/>`;
    const text = `${c.name} ${sgn(c.metrics.z_attention)}`, w = text.length * 6.2 + 4;
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
      const mm = c.metrics || {};
      tip.innerHTML = `<b>${esc(c.name)}</b>${m.label}: ${m.fmt(m.get(c))}<br>Anomaly ${sgn(mm.z_attention)}, ${f0(mm.articles_7d)} articles in 7 days<br>${esc((c.flags || [])[0]?.text || tierLabel(c.tier))}`;
      tip.style.opacity = 1; const r = e.clientX != null ? e : p.getBoundingClientRect();
      const x = (r.clientX ?? r.left) + 14, y = (r.clientY ?? r.top) + 14;
      tip.style.left = Math.min(x, innerWidth - 250) + "px"; tip.style.top = Math.min(y, innerHeight - 110) + "px";
    };
    p.addEventListener("mousemove", show); p.addEventListener("focus", show);
    p.addEventListener("mouseleave", () => (tip.style.opacity = 0)); p.addEventListener("blur", () => (tip.style.opacity = 0));
    p.addEventListener("click", () => openCountry(c.iso3));
    p.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openCountry(c.iso3); } });
  });
}

/* ---------------- render: side panels + KPIs ---------------- */
function renderMovers() {
  const list = visible().filter((c) => c.metrics?.z_attention != null).sort((a, b) => b.metrics.z_attention - a.metrics.z_attention).slice(0, 6);
  $("#movers").innerHTML = list.length ? list.map((c) => {
    const m = c.metrics, why = (c.flags || []).find((f) => !f.text.startsWith("Coverage"))?.text ||
      `${f1(m.share_latest)} per 10k on ${dayLabel(m.latest_day)}, ${pct(m.change_7d_pct)} articles week on week`;
    return `<li><button data-iso="${c.iso3}"><span class="name">${esc(c.name)}</span><span class="z num ${m.z_attention >= 2 ? "hot" : ""}">${sgn(m.z_attention)}</span><span class="why">${esc(why)}</span></button></li>`;
  }).join("") : `<li class="empty">No countries match the filter.</li>`;
  $("#movers").onclick = (e) => { const b = e.target.closest("button"); if (b) openCountry(b.dataset.iso); };
}

function renderWatch() {
  const w = (S.data.watch || [])[0];
  if (!w) { $("#watch").innerHTML = ""; return; }
  const items = (w.headlines || []).slice(0, 5);
  $("#watch").innerHTML = `<h2>${esc(w.label)} <small>in the news</small></h2>
    <div class="big">${f0(w.count_7d)}${w.count_7d >= 100 ? "+" : ""}</div><div class="muted" style="font-size:13px">Google News results in the last 7 days</div>${staleNews(w.headlines_at)}
    ${items.length ? `<ul>${items.map((i) => `<li><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a><div class="faint" style="font-size:12px">${esc(i.source)}, ${ago(i.published)}</div></li>`).join("")}</ul>`
      : `<p class="empty">No mentions in the last 7 days.</p>`}`;
}

function renderKpis() {
  const cs = visible().filter((c) => c.metrics && Object.keys(c.metrics).length);
  const sum = cs.reduce((a, c) => a + (c.metrics.articles_7d || 0), 0);
  const spikes = cs.filter((c) => c.metrics.z_attention >= 2);
  const top = [...cs].sort((a, b) => (b.metrics.share_7d || 0) - (a.metrics.share_7d || 0))[0];
  const riser = [...cs].filter((c) => c.metrics.share_change_7d_pct != null).sort((a, b) => b.metrics.share_change_7d_pct - a.metrics.share_change_7d_pct)[0];
  const grim = [...cs].filter((c) => c.metrics.tone_7d != null).sort((a, b) => a.metrics.tone_7d - b.metrics.tone_7d)[0];
  const peace = [...cs].filter((c) => c.metrics.peace_share_7d != null).sort((a, b) => b.metrics.peace_share_7d - a.metrics.peace_share_7d)[0];
  const k = (v, l, s) => `<div class="kpi"><div class="v num">${v}</div><div class="l">${l}</div><div class="s">${s}</div></div>`;
  $("#kpis").innerHTML = [
    k(f0(sum), "Coverage in 7 days", `article mentions across ${cs.length} countries`),
    k(spikes.length, "Countries spiking", spikes.length ? esc(spikes.map((c) => c.name).join(", ")) : "nothing above +2 on the last full day"),
    k(top ? esc(top.name) : "–", "Most covered", top ? `${f1(top.metrics.share_7d)} per 10k articles` : ""),
    k(riser ? esc(riser.name) : "–", "Fastest riser", riser ? `share ${pct(riser.metrics.share_change_7d_pct)} week on week` : ""),
    k(grim ? esc(grim.name) : "–", "Grimmest tone", grim ? `average tone ${sgn(grim.metrics.tone_7d, 2)}` : ""),
    k(peace ? esc(peace.name) : "–", "Most peace talk", peace ? `${f0(peace.metrics.peace_share_7d)}% of coverage` : ""),
  ].join("");
}

/* ---------------- render: ledger ---------------- */
const COLS = [
  { key: "name", label: "Country", get: (c) => c.name, cell: (c) => `<span class="tier ${c.tier}" title="${tierLabel(c.tier)}"></span>${esc(c.name)}${(c.flags || []).some((f) => f.level !== "info" && f.level !== "low") ? `<span class="flagdot" title="${esc(c.flags.map((f) => f.text).join("; "))}"></span>` : ""}<span class="reg">${esc(c.region)}${c.pending ? ", metrics loading" : ""}</span>`, cls: "c" },
  { key: "share", label: "Last full day<br>per 10k", get: (c) => c.metrics?.share_latest, cell: (c) => f1(c.metrics?.share_latest) },
  { key: "z", label: "Anomaly<br>robust z", get: (c) => c.metrics?.z_attention, cell: (c) => `<span class="zbar"><span class="num ${c.metrics?.z_attention >= 2 ? "hot" : ""}">${sgn(c.metrics?.z_attention)}</span>${zBar(c.metrics?.z_attention)}</span>` },
  { key: "pctile", label: "90-day<br>percentile", get: (c) => c.metrics?.attention_pctile_90d, cell: (c) => f0(c.metrics?.attention_pctile_90d) },
  { key: "a7", label: "Coverage<br>7 days", get: (c) => c.metrics?.articles_7d, cell: (c) => f0(c.metrics?.articles_7d) },
  { key: "ch7", label: "Week on<br>week", get: (c) => c.metrics?.change_7d_pct, cell: (c) => `<span class="${c.metrics?.change_7d_pct > 0 ? "up" : c.metrics?.change_7d_pct < 0 ? "down" : ""}">${pct(c.metrics?.change_7d_pct)}</span>` },
  { key: "trend", label: "30-day trend<br>per week", get: (c) => c.metrics?.trend_30d_pct_per_week, cell: (c) => pct(c.metrics?.trend_30d_pct_per_week) },
  { key: "tone", label: "Tone<br>7 days", get: (c) => c.metrics?.tone_7d, cell: (c) => `${sgn(c.metrics?.tone_7d, 2)} <span class="faint" style="font-size:12px">${c.metrics?.tone_delta != null ? "(" + sgn(c.metrics.tone_delta, 1) + ")" : ""}</span>` },
  { key: "viol", label: "Violence<br>share", get: (c) => c.metrics?.violence_share_7d, cell: (c) => c.metrics?.violence_share_7d == null ? "–" : f0(c.metrics.violence_share_7d) + "%" },
  { key: "peace", label: "Peace talk<br>share", get: (c) => c.metrics?.peace_share_7d, cell: (c) => c.metrics?.peace_share_7d == null ? "–" : f0(c.metrics.peace_share_7d) + "%" },
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

/* ---------------- render: small multiples ---------------- */
function renderMultiples() {
  const order = [...new Set(S.data.countries.map((c) => c.region))];
  const cs = visible().slice().sort((a, b) => order.indexOf(a.region) - order.indexOf(b.region) || (b.metrics?.share_7d || 0) - (a.metrics?.share_7d || 0));
  $("#multiples").innerHTML = cs.map((c) => {
    const vals = (c.series || []).map((p) => p.s), band = bandOf(c.series || []);
    const W = 220, H = 64, n = vals.length; const ok = vals.concat(band.flatMap((b) => (b ? [b.hi] : []))).filter((v) => v != null);
    if (n < 2 || !ok.length) return "";
    const max = Math.max(...ok) * 1.05, X = (i) => (i / (n - 1)) * W, Y = (v) => H - 2 - (v / max) * (H - 6);
    let top = "", bot = [], line = "", dots = "";
    band.forEach((b, i) => { if (!b) return; top += (top ? "L" : "M") + X(i).toFixed(1) + "," + Y(b.hi).toFixed(1); bot.unshift(X(i).toFixed(1) + "," + Y(b.lo).toFixed(1)); });
    vals.forEach((v, i) => { if (v == null) return; line += (line ? "L" : "M") + X(i).toFixed(1) + "," + Y(v).toFixed(1); if (band[i] && v > band[i].hi) dots += `<circle cx="${X(i)}" cy="${Y(v)}" r="2.4" fill="var(--signal)"/>`; });
    const m = c.metrics || {};
    return `<button class="sm" data-iso="${c.iso3}" style="background:none;border:0;padding:0;text-align:left;cursor:pointer">
      <h4>${esc(c.name)} <span class="num ${m.z_attention >= 2 ? "hot" : "faint"}" style="font-weight:600">${sgn(m.z_attention)}</span></h4>
      <div class="meta">${esc(c.region)}, ${f1(m.share_7d)} per 10k this week</div>
      <svg viewBox="0 0 ${W} ${H}" width="100%" aria-hidden="true">${top ? `<path d="${top}L${bot.join("L")}Z" fill="var(--attn-0)"/>` : ""}<path d="${line}" fill="none" stroke="var(--attn-2)" stroke-width="1.4"/>${dots}</svg></button>`;
  }).join("") || `<p class="empty">No countries match the filter.</p>`;
  $("#multiples").onclick = (e) => { const b = e.target.closest("[data-iso]"); if (b) openCountry(b.dataset.iso); };
}

/* ---------------- render: framing scatter + tone ranking ---------------- */
function renderScatter() {
  const cs = visible().filter((c) => c.metrics?.violence_share_7d != null && c.metrics?.peace_share_7d != null);
  if (!cs.length) { $("#scatter").innerHTML = `<p class="empty">No framing data yet.</p>`; return; }
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
  g += `<text x="${W - R}" y="${H - 4}" text-anchor="end">violence share →</text><text x="${L}" y="${T - 2}" >↑ peace-talk share</text>`;
  const pts = cs.sort((a, b) => (b.metrics.articles_7d || 0) - (a.metrics.articles_7d || 0)).map((c) => {
    const r = 4 + 18 * Math.sqrt((c.metrics.articles_7d || 0) / amax), x = X(c.metrics.violence_share_7d), y = Y(c.metrics.peace_share_7d);
    const hot = c.metrics.z_attention >= 2;
    return `<g class="pt" data-iso="${c.iso3}"><circle cx="${x}" cy="${y}" r="${r}" fill="${hot ? "var(--signal)" : "var(--attn-2)"}" fill-opacity=".35" stroke="${hot ? "var(--signal)" : "var(--attn-2)"}"><title>${esc(c.name)}: ${f0(c.metrics.violence_share_7d)}% violence, ${f0(c.metrics.peace_share_7d)}% peace</title></circle><text class="lab" x="${x}" y="${y - r - 3}" text-anchor="middle">${esc(c.name)}</text></g>`;
  }).join("");
  $("#scatter").innerHTML = `<h3>Violence versus peace talk</h3><svg viewBox="0 0 ${W} ${H}">${g}${pts}</svg>`;
  $("#scatter").onclick = (e) => { const p = e.target.closest(".pt"); if (p) openCountry(p.dataset.iso); };

  // Tone ranking: dot plot with arrow from prior-30d tone to 7d tone
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

/* ---------------- render: wire ---------------- */
function wireItems() {
  const items = [];
  S.data.countries.forEach((c) => {
    if (S.tier !== "all" && c.tier !== S.tier) return;
    if (S.wireCountry !== "all" && c.iso3 !== S.wireCountry) return;
    if (S.wireKind !== "gdelt") (c.headlines || []).forEach((h) => items.push({ c, title: h.title, url: h.url, src: h.source, when: h.published, kind: "news" }));
    if (S.wireKind !== "news") (c.gdelt?.articles || []).forEach((a) => items.push({ c, title: a.title, url: a.url, src: a.domain, when: a.seen, kind: "gdelt", from: a.mentions ? `${a.mentions} articles` : "" }));
  });
  const seen = new Set();
  return items.filter((i) => (!S.q || i.title.toLowerCase().includes(S.q) || i.c.name.toLowerCase().includes(S.q)))
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

/* ---------------- drawer ---------------- */
// Headlines kept from an earlier run because Google News failed this time.
const staleNews = (at) => (at && new Date(S.data.generated_at) - new Date(at) > 36e5
  ? `<p class="stale-note">Google News didn't answer this run; these are from ${ago(at)}.</p>` : "");
let lastFocus = null;
function openCountry(iso) {
  const c = byIso(iso); if (!c) return;
  S.open = iso; lastFocus = document.activeElement;
  if (location.hash !== "#/" + iso) history.replaceState(null, "", "#/" + iso);
  const m = c.metrics || {}, ser = c.series || [], dates = ser.map((p) => p.d);
  const shares = ser.map((p) => p.s), band = bandOf(ser);
  const marks = shares.map((v, i) => (band[i] && v != null && v > band[i].hi ? i : -1)).filter((i) => i >= 0);
  const tone = ser.map((p) => p.t), viol = rollingRatio(ser, "v", "n"), peace = rollingRatio(ser, "p", "n"), med = rollingRatio(ser, "m", "n");
  const kp = (v, l, s = "") => `<div class="kpi"><div class="v num">${v}</div><div class="l">${l}</div>${s ? `<div class="s">${s}</div>` : ""}</div>`;
  const gq = encodeURIComponent(c.gdelt || c.name), nq = encodeURIComponent(c.news || c.name);
  const d = $("#drawer");
  const cw = Math.max(320, Math.min(660, Math.min(innerWidth, 760) - 70));
  const ch = (h) => Math.round(h * (cw < 500 ? 1.15 : 1));
  d.innerHTML = `<div class="d-head"><div><h2 id="dTitle">${esc(c.name)}</h2>
      <div class="sub">${esc(c.region)}, ${tierLabel(c.tier).toLowerCase()}. Scores for ${m.latest_day ? dayLabel(m.latest_day) : "–"}, the last full day.${m.today_share != null ? ` Today so far: ${f1(m.today_share)} per 10k over ${f1(m.today_hours)} h (not scored; part-days are skewed by time zone).` : ""}${c.pending ? " <span class='stale-note'>Metrics still loading; headlines are live.</span>" : ""}</div></div>
      <button class="close" id="dClose" aria-label="Close">×</button></div>
    <div class="d-body">
      ${(c.flags || []).length ? `<div class="flags">${c.flags.map((f) => `<div class="flag ${f.level}">${esc(f.text)}</div>`).join("")}</div>` : ""}
      <div class="d-kpis">
        ${kp(f1(m.share_latest), `${m.latest_day ? dayLabel(m.latest_day) : "Latest day"} per 10k`, `${f0(m.articles_latest)} articles`)}
        ${kp(`<span class="${m.z_attention >= 2 ? "hot" : ""}">${sgn(m.z_attention)}</span>`, "Anomaly (robust z)", `${f0(m.attention_pctile_90d)}th percentile of 90 days`)}
        ${kp(f0(m.articles_7d), "Coverage, 7 days", `${pct(m.change_7d_pct)} week on week`)}
        ${kp(pct(m.trend_30d_pct_per_week), "30-day trend", "share, per week")}
        ${kp(sgn(m.tone_7d, 2), "Tone, 7 days", `${sgn(m.tone_delta, 2)} vs prior 30 days`)}
        ${kp(m.violence_share_7d == null ? "–" : f0(m.violence_share_7d) + "%", "Violence share", `was ${f0(m.violence_share_prev30d)}%`)}
        ${kp(m.peace_share_7d == null ? "–" : f0(m.peace_share_7d) + "%", "Peace-talk share", `was ${f0(m.peace_share_prev30d)}%`)}
        ${kp(m.mediation_share_7d == null ? "–" : f1(m.mediation_share_7d) + "%", "Mediation share", `was ${f1(m.mediation_share_prev30d)}%`)}
      </div>
      <div class="panel chart"><h3>Share of world coverage <small>per 10k articles, full days; band = expected range, adjusted for day of week</small></h3>${tsChart({ dates, lines: [{ vals: shares, color: "var(--attn-2)" }], band, marks, zero: true, width: cw, height: ch(180) })}</div>
      <div class="panel chart"><h3>Tone <small>daily (thin) and 7-day average</small></h3>${tsChart({ dates, lines: [{ vals: tone, color: "var(--ink-3)", width: 1 }, { vals: rollingMean(tone), color: "var(--neg)", width: 2 }], height: ch(150), width: cw, yfmt: (v) => v.toFixed(1), refLine: m.tone_prev30d })}</div>
      <div class="panel chart"><h3>Framing <small>7-day rolling share of coverage: <span style="color:var(--neg)">violence</span>, <span style="color:var(--pos)">peace talk</span>, <span style="color:var(--pos)">mediation (dashed)</span></small></h3>${tsChart({ dates, lines: [{ vals: viol, color: "var(--neg)" }, { vals: peace, color: "var(--pos)" }, { vals: med, color: "var(--pos)", dash: "4 3", width: 1.4 }], height: ch(150), width: cw, yfmt: (v) => f0(v) + "%", zero: true })}</div>
      <div class="grid2">
        <div class="panel"><h3>Top outlets <small>most-covered stories, 3 days</small></h3>${bars(c.gdelt?.top_domains)}</div>
        <div class="panel"><h3>What is being reported <small>event types, 7 days</small></h3>${bars(c.gdelt?.event_mix)}</div>
      </div>
      <div class="panel"><h3>Mainstream headlines <small>Google News, last 2 days</small></h3>${staleNews(c.headlines_at)}
        ${(c.headlines || []).length ? `<ul class="list">${c.headlines.map((h) => `<li><a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a><div class="meta">${esc(h.source)}, ${ago(h.published)}</div></li>`).join("")}</ul>` : `<p class="empty">No headlines in this run.</p>`}</div>
      <div class="panel"><h3>Most-covered stories <small>GDELT, last 3 days, all languages</small></h3>
        ${(c.gdelt?.articles || []).length ? `<ul class="list">${c.gdelt.articles.slice(0, 25).map((a) => `<li><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a><div class="meta">${esc(a.domain)}${a.kind ? `, ${esc(a.kind.toLowerCase())}` : ""}, ${a.mentions} ${a.mentions === 1 ? "article" : "articles"}, ${ago(a.seen)}</div></li>`).join("")}</ul>` : `<p class="empty">No articles in this run.</p>`}</div>
      <div class="panel"><h3>Go deeper</h3><div class="links">
        <a href="https://news.google.com/search?q=${nq}&hl=en-GB&gl=GB&ceid=GB:en" target="_blank" rel="noopener">Google News search</a>
        <a href="https://api.gdeltproject.org/api/v2/doc/doc?query=${gq}&mode=artlist&maxrecords=250&timespan=1d&sort=datedesc" target="_blank" rel="noopener">GDELT live article list</a>
        <a href="https://api.gdeltproject.org/api/v2/doc/doc?query=${gq}&mode=timelinevol&timespan=1y" target="_blank" rel="noopener">GDELT 12-month timeline</a>
        <a href="https://reliefweb.int/country/${c.iso3.toLowerCase()}" target="_blank" rel="noopener">ReliefWeb</a>
        <a href="https://www.crisisgroup.org/crisiswatch/database" target="_blank" rel="noopener">CrisisWatch</a>
        <a href="https://acleddata.com/conflict-data/" target="_blank" rel="noopener">ACLED</a>
      </div></div>
    </div>`;
  d.classList.add("open"); d.setAttribute("aria-hidden", "false"); $("#scrim").classList.add("open");
  document.body.style.overflow = "hidden"; d.scrollTop = 0; $("#dClose").onclick = closeCountry; $("#dClose").focus();
}
function closeCountry() {
  S.open = null; const d = $("#drawer");
  d.classList.remove("open"); d.setAttribute("aria-hidden", "true"); $("#scrim").classList.remove("open"); document.body.style.overflow = "";
  history.replaceState(null, "", location.pathname + location.search);
  if (lastFocus) lastFocus.focus();
}

/* ---------------- wiring ---------------- */
function renderAll() { renderMap(); renderMovers(); renderWatch(); renderKpis(); renderLedger(); renderMultiples(); renderScatter(); renderWire(); }

function initControls() {
  $("#tierSeg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S.tier = b.dataset.tier; pressed("#tierSeg", b); renderAll(); });
  let t; $("#search").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { S.q = e.target.value.trim().toLowerCase(); renderAll(); }, 150); });
  $("#scrim").addEventListener("click", closeCountry);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.open) closeCountry(); });
  window.addEventListener("hashchange", () => { const iso = location.hash.replace("#/", ""); if (iso && byIso(iso)) openCountry(iso); });
  // theme toggle: auto -> dark -> light -> auto
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
      fetch("data/latest.json?t=" + Date.now()).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }),
      fetch("assets/vendor/countries-50m.json").then((r) => r.json()).catch(() => null),
    ]);
    S.data = data; S.world = world;
  } catch (err) {
    $("#app").innerHTML = `<div class="error"><h2>No data yet</h2><p>The first data run hasn't finished. Open the repository's Actions tab, run "Update media data", and reload this page in about 15 minutes.</p></div>`;
    $("#stamp").textContent = "Waiting for the first data run.";
    return;
  }
  renderStamp(); renderShell(); renderFooter(); renderAll();
  const iso = location.hash.replace("#/", ""); if (iso && byIso(iso)) openCountry(iso);
}
boot();
})();
