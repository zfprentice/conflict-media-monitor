"""Headlines -> stories, themes and names. Pure text processing, no network.

Google News returns many near-identical headlines for one event ("Drone strike
kills 150 in Abyei market", "At least 153 killed in Abyei drone strike...").
Grouping them into stories, counting how many outlets carried each, and tagging
what each is about lets the page say what happened rather than only how much
coverage there was. Everything here is keyword- and overlap-based, so it is
transparent and never invents text: every story shown is a real headline.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

# ---------------------------------------------------------------- normalising
def fold(text: str) -> str:
    """Lowercase and strip accents, so 'Türkiye' matches 'turkiye' and 'Vučić' matches 'vucic'."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def _phrase_rx(phrases: list[str]) -> re.Pattern | None:
    phrases = sorted({fold(p).strip() for p in phrases if p and p.strip()}, key=len, reverse=True)
    if not phrases:
        return None
    # plural or possessive endings count: 'Palestinians', 'Venezuelans'
    return re.compile(r"(?<![\w])(?:" + "|".join(re.escape(p) for p in phrases) + r")(?:s|es)?(?![\w])")


def query_terms(query: str) -> list[str]:
    """Terms of a search string: '(Sudan OR "Rapid Support Forces")' -> ['Sudan', 'Rapid Support Forces']."""
    quoted = re.findall(r'"([^"]+)"', query or "")
    rest = re.sub(r'"[^"]+"', " ", query or "")
    words = [w for w in re.split(r"[\s()]+", rest) if w and w.upper() not in {"OR", "AND"} and not w.startswith("-")]
    return quoted + words


class Matcher:
    """Decides whether a headline is really about a country.

    A headline must name the country (or its capital, people, main actors) once
    any `strip` phrases are removed ('South Sudan' is not Sudan), and must not
    contain an `exclude` phrase.
    """

    def __init__(self, country: dict):
        terms = [country["name"]] + query_terms(country.get("gdelt", "")) + query_terms(country.get("news", ""))
        terms += country.get("match", [])
        self.terms = _phrase_rx(terms)
        self.strip = _phrase_rx(country.get("strip", []))
        self.exclude = _phrase_rx(country.get("exclude", []))

    def mentions(self, title: str) -> bool:
        t = fold(title)
        if self.exclude and self.exclude.search(t):
            return False
        if self.strip:
            t = self.strip.sub(" ", t)
        return bool(self.terms and self.terms.search(t))


# Headlines that are never conflict or politics news: sport, weather, markets, quake bulletins, press releases.
NOISE = re.compile(
    r"\b(nba|nfl|nhl|mlb|cricket|t20|odi|test match|football|soccer|fifa|uefa|premier league|champions league|la liga|"
    r"world cup qualif\w*|match highlights|highlights|tennis|golf|formula 1|grand prix|motogp|basketball|rugby|volleyball|"
    r"olympic\w*|goalkeeper|striker signs|transfer window|grands? prix|fia|eurovision|united rugby championship|head coach|coach$|as coach|new coach|nrl|afl|semi-?final|quarter-?final|fixtures?|squad|"
    r"weather|forecast|drizzle|humid|horoscope|lottery|recipe\w*|"
    r"stock price|share price|price target|dividend|nasdaq|nyse|ipo|bitcoin|crypto\w*|appoints|close of trade|"
    r"stocks? (?:higher|lower|up|down|rise|fall)\w*|shares (?:higher|lower)|"
    r"mag(nitude)?\.? ?\d(\.\d)?|m\d\.\d)\b"
)
NOISE_SOURCES = {fold(s) for s in (
    "Volcano Discovery", "VolcanoDiscovery", "IQAir", "MarketScreener", "www.marketscreener.com", "ad-hoc-news.de",
    "ICC", "PR Newswire", "Business Wire", "GlobeNewswire", "EIN Presswire", "openPR", "Investing.com",
    "MarketBeat", "Zacks", "Earthquake List", "earthquakelist.org", "Weather.com", "AccuWeather",
)}


SPORT_FIXTURE = re.compile(r"\b[A-Z][\w'’.-]* vs?\.? [A-Z]")  # 'Ospreys v Black Lion', 'Lesotho vs Mozambique'


def is_noise(title: str, source: str = "") -> bool:
    src = fold(source).strip()
    return (src in NOISE_SOURCES or src.startswith(("investing.com", "marketscreener"))
            or bool(NOISE.search(fold(title))) or bool(SPORT_FIXTURE.search(title or "")))


ENGLISH = re.compile(r"\b(the|of|in|to|for|on|and|after|as|with|at|by|from|is|are|was|over|amid|says|into|against)\b")


def readable_slug_title(title: str, domain: str) -> bool:
    """GDELT story titles are rebuilt from URLs. Keep only ones that read as English sentences."""
    if not title or title == domain or re.match(r"(?i)^article\b", title):
        return False
    words = title.split()
    if len(words) < 5:
        return False
    hexish = sum(1 for w in words if re.fullmatch(r"[0-9a-f]{3,}", w, re.I) and re.search(r"\d", w))
    return hexish == 0 and len(ENGLISH.findall(fold(title))) >= 1


# ---------------------------------------------------------------- themes
def _theme_rx(words: str) -> re.Pattern:
    """'kill* | war' -> stems with * match any ending, other words match whole."""
    parts = []
    for w in (x.strip() for x in words.split("|")):
        if w:
            parts.append(re.escape(w[:-1]) + r"\w*" if w.endswith("*") else re.escape(w))
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b")


THEMES = [
    ("violence", "Violence and security", _theme_rx(
        "kill* | dead | death* | died | attack* | strike* | airstrike* | air strike* | drone* | bomb* | blast* | "
        "explosion* | shell* | missile* | rocket* | clash* | fighting | fighters | militant* | militia* | insurgen* | "
        "gunmen | gunfire | shooting | shot dead | troops | army | military | offensive | raid* | ambush* | massacre* | "
        "war | wars | warfare | hostage* | siege | security forces | jihadist* | terror* | wounded | injured | casualt* | "
        "shabaab | rsf | paramilitar* | armed group* | battle* | frontline | front line | invasion | occupation | "
        "violence | violent | weapons | arms | escalat*")),
    ("humanitarian", "Humanitarian needs", _theme_rx(
        "humanitarian | aid | famine | hunger | starv* | food insecurity | malnutrition | refugee* | displaced | "
        "displacement | evacuat* | cholera | outbreak | epidemic | disease* | shelter* | unhcr | wfp | unicef | ocha | "
        "relief | flood* | earthquake* | drought | cyclone | landslide* | migrant* | asylum | civilians | hospital* | "
        "medical | health | water shortage* | crisis")),
    ("diplomacy", "Talks and diplomacy", _theme_rx(
        "talks | negotiat* | ceasefire* | cease-fire* | truce | peace | mediat* | envoy* | summit* | dialogue | "
        "agreement* | accord* | deal | deals | diplomat* | foreign minister* | visit* | meets | meeting* | met with | "
        "delegation* | sanction* | ambassador* | security council | united nations | un | resolution | normali* | "
        "treaty | memorandum | reconcil* | de-escalat* | roadmap | road map | broker*")),
    ("politics", "Politics and governance", _theme_rx(
        "election* | vote* | voting | ballot* | parliament* | government* | cabinet | president* | prime minister* | "
        "opposition | party | parties | coalition | constitution* | court* | ruling | minister* | resign* | protest* | "
        "demonstrat* | rally | rallies | referendum | coup* | reform* | law | laws | bill | governance | corruption | "
        "campaign* | lawmakers | mp | mps | senate | congress | political | politic* | ban | leader* | regime")),
    ("rights", "Rights and justice", _theme_rx(
        "rights | arrest* | detain* | detention | prison* | jail* | sentenc* | tortur* | execut* | journalist* | "
        "press freedom | activist* | crackdown | abuse* | trial* | icc | war crime* | genocide | accountab* | "
        "disappear* | censorship | amnesty | human rights watch | investigation* | impunity | women | girls")),
    ("economy", "Economy", _theme_rx(
        "economy | economic* | inflation | currency | oil | gas | trade | investment* | invest* | budget* | gdp | imf | "
        "world bank | central bank* | banking | debt | export* | import* | tariff* | prices | fuel prices | energy | canal | "
        "mining | business* | stock market* | jobs | unemployment | growth | finance* | loan* | revenue*")),
]
THEME_LABELS = {k: label for k, label, _ in THEMES}


def themes_of(title: str) -> list[str]:
    t = fold(title)
    return [k for k, _, rx in THEMES if rx.search(t)]


def theme_counts(items: list[dict]) -> dict[str, int]:
    c = Counter(k for it in items for k in themes_of(it["title"]))
    return {k: c.get(k, 0) for k, _, _ in THEMES}


# ---------------------------------------------------------------- clustering
STOP = set("""a about above after again against all also am amid an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has have having he
her here hers him his how i if in into is it its just least less like may me more most much must my new no nor not
now of off on once only or other our out over own per said same say says she should so some such than that the their
them then there these they this those through to too under until up upon us very via was we were what when where which
while who whom why will with would you your after amid near over report reports reported latest live update updates
news video watch photos day days week year years first second one two three told amid""".split())


def _stem(w: str) -> str:
    for suf, min_len in (("ing", 6), ("ed", 5), ("es", 5), ("s", 4)):
        if len(w) >= min_len and w.endswith(suf) and not w.endswith("ss"):
            return w[: -len(suf)]
    return w


def tokens(title: str, ignore: set[str] = frozenset()) -> set[str]:
    words = re.findall(r"[a-z0-9]+", fold(title).replace("'s ", " "))
    out = set()
    for w in words:
        if w in STOP or w in ignore or (len(w) < 3 and not w.isdigit()):
            continue
        out.add(_stem(w))
    return out


# Outlets readers recognise, preferred when picking the headline that represents a story.
MAJOR = [fold(s) for s in (
    "Reuters", "Associated Press", "AP News", "AFP", "BBC", "Al Jazeera", "The Guardian", "The New York Times",
    "The Washington Post", "Financial Times", "The Economist", "Bloomberg", "France 24", "DW", "Deutsche Welle",
    "Le Monde", "Politico", "Politico Europe", "Euronews", "The Independent", "Sky News", "CNN", "NPR", "The Times",
    "Arab News", "The National", "Middle East Eye", "Haaretz", "The Times of Israel", "Kyiv Independent",
    "Africanews", "AllAfrica", "Sudan Tribune", "Radio Dabanga", "Crisis Group", "UN News", "ReliefWeb",
)]


def _major_rank(source: str) -> int:
    s = fold(source)
    return MAJOR.index(s) if s in MAJOR else len(MAJOR)


def cluster(items: list[dict], ignore: set[str] = frozenset(), threshold: float = 0.45) -> list[dict]:
    """Group headlines about the same event.

    Two headlines match when they share at least two content words and the
    shared words carry `threshold` of the shorter headline's weight, with rare
    words (by inverse frequency within this set) weighing more than common ones
    like 'kill' or 'war'. Country names are ignored so that every Sudan headline
    doesn't match every other.
    """
    toks = [tokens(it["title"], ignore) for it in items]
    df = Counter(t for ts in toks for t in ts)
    n = max(len(items), 1)
    idf = {t: math.log(1 + n / c) for t, c in df.items()}
    weight = lambda ts: sum(idf[t] for t in ts)  # noqa: E731

    groups: list[list[int]] = []
    order = sorted(range(len(items)), key=lambda i: items[i].get("published") or "", reverse=True)
    for i in order:
        best, best_s = None, 0.0
        for g in groups:
            for j in g:
                shared = toks[i] & toks[j]
                if len(shared) < 2:
                    continue
                s = weight(shared) / (min(weight(toks[i]), weight(toks[j])) or 1)
                if s > best_s:
                    best, best_s = g, s
        if best is not None and best_s >= threshold:
            best.append(i)
        else:
            groups.append([i])

    out = []
    for g in groups:
        members = [items[i] for i in g]
        sources = []
        for m in sorted(members, key=lambda m: _major_rank(m.get("source", ""))):
            if m.get("source") and m["source"] not in sources:
                sources.append(m["source"])

        def centrality(i):
            return sum(len(toks[i] & toks[j]) for j in g if j != i)
        rep_i = max(g, key=lambda i: (centrality(i) + (2 if _major_rank(items[i].get("source", "")) < len(MAJOR) else 0),
                                       items[i].get("published") or ""))
        rep = items[rep_i]
        dates = sorted(m["published"] for m in members if m.get("published"))
        also = [{"title": m["title"], "url": m["url"], "source": m.get("source", "")}
                for m in members if m is not rep][:4]
        out.append({
            "title": rep["title"], "url": rep["url"], "source": rep.get("source", ""),
            "outlets": len(sources) or 1, "sources": sources[:6], "n": len(members),
            "first": dates[0] if dates else None, "last": dates[-1] if dates else None,
            "themes": themes_of(rep["title"]), "also": also,
        })
    out.sort(key=lambda s: (s["outlets"], s["n"], s["last"] or ""), reverse=True)
    return out


# ---------------------------------------------------------------- names in the news
_CAP = re.compile(r"[A-Z][\w'’\-]*(?:\s+(?:al-|bin\s+|de\s+|of\s+)?[A-Z][\w'’\-]*)*")
TITLES = set("""President Prime Minister PM FM Mr Mrs Ms Dr King Queen Prince Princess Sultan Sheikh Emir Foreign
Defence Defense Interior General Gen Chief Envoy Former Ex""".split())
GENERIC = set("""The A An In On At For To Of And But Or After Before As With From By Over Under Amid Why How What
When Who Where Will Is Are Was Were Be New Latest Live Breaking Watch Video Exclusive Analysis Opinion Report Update
Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August September
October November December Jan Feb Mar Apr Jun Jul Aug Sept Sep Oct Nov Dec This That These Those Its It His Her Their
Our Says Said More Most Top Day Week Year Government Army Police Parliament Council Ministry State Court Forces
Military National Central City Region Officials People Here There Inside World Media West East North South
Middle Europe European Africa African Asia Gulf Western International UN US EU""".split()) | TITLES


def names(items: list[dict], ignore: set[str] = frozenset(), limit: int = 6) -> list[list]:
    """People, places and groups named most often, from headlines written in sentence case.

    Title-case headlines ('Army Drone Strike Kills 153') capitalise every word,
    so they are skipped rather than letting 'Strike' look like a name. Leading
    titles are dropped ('President Ruto' -> 'Ruto'), names made only of generic
    words ('Government', 'West') are skipped, and so are outlet names.
    """
    outlets = {fold(it.get("source", "")) for it in items}
    c = Counter()
    for it in items:
        words = it["title"].split()
        if len(words) < 4 or sum(w[:1].isupper() for w in words) / len(words) > 0.5:
            continue
        found = set()
        for m in _CAP.finditer(it["title"]):
            parts = re.sub(r"['’]s$", "", m.group().strip(" '’-")).split()
            if m.start() == 0 and len(parts) < 2:
                continue  # the first word is capitalised anyway
            while parts and parts[0] in TITLES:
                parts = parts[1:]
            if not parts or all(p in GENERIC for p in parts):
                continue
            name = " ".join(parts)
            words_ = {_stem(w) for w in re.findall(r"[a-z0-9]+", fold(name))}
            if len(name) < 3 or words_ & ignore or fold(name) in outlets:
                continue
            found.add(name)
        c.update(found)
    return [[k, v] for k, v in c.most_common(limit) if v >= 2]


def dedupe(items: list[dict]) -> list[dict]:
    """Same headline from the same outlet appears in several queries or runs; keep one."""
    seen, out = set(), []
    for it in items:
        key = (re.sub(r"\W+", "", fold(it["title"]))[:90], fold(it.get("source", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def analyse(items: list[dict], ignore: set[str], max_stories: int = 6) -> dict:
    """Stories, theme counts and names for one country's headlines."""
    items = dedupe(items)
    return {
        "n": len(items),
        "stories": cluster(items, ignore)[:max_stories],
        "themes": theme_counts(items),
        "names": names(items, ignore),
    }


def ignore_words(country: dict) -> set[str]:
    """Words that identify the country itself, ignored when matching stories and listing names."""
    terms = [country["name"]] + query_terms(country.get("gdelt", "")) + query_terms(country.get("news", "")) + country.get("match", [])
    out = set()
    for t in terms:
        out.add(fold(t))
        out.update(_stem(w) for w in re.findall(r"[a-z0-9]+", fold(t)))
    return out
