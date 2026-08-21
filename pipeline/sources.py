#!/usr/bin/env python3
"""
Il registro delle fonti, con la panchina.

Una fonte non si cancella mai. Se smette di servire — muta, o diventata l'eco
di qualcun altro — passa in **panchina**: esce dalla raccolta quotidiana, ma
resta scritta con la sua data e il suo motivo, e ogni sette giorni viene
riprovata. Se torna a pubblicare cose che gli altri non hanno, si propone di
rimetterla dentro.

Il file e' data/sources.json e ha una riga per fonte:

    "Wired Italia": {
      "url": "https://www.wired.it/feed/rss",
      "state": "panchina",           attiva | panchina
      "tier": "redazionale",         primaria | redazionale | larga | ai | banco
      "since": "2026-08-09",         da quando e' in questo stato
      "reason": "fermo da 39 giorni",
      "checked": "2026-08-16",       ultima riprova
      "history": ["2026-08-09 panchina: fermo da 39 giorni"]
    }

fetch.py raccoglie solo le attive. feedcheck.py --retest riprova le altre.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_FILE = os.path.join(ROOT, "data", "sources.json")

# ogni quanto si riprova una fonte in panchina
RETEST_DAYS = 7

# Fonti primarie: pubblicano di rado ma sono la parola di Apple. Il silenzio
# non e' un sintomo, quindi non finiscono mai in panchina per inattivita'.
PRIMARY = {"Apple Newsroom", "Apple Developer"}

# Fonti larghe: non parlano di Apple, servono al radar. Sono la materia prima
# delle sonde — senza, il radar esplora fra gli avanzi delle testate Apple.
BROAD = {"Ars Technica", "TechCrunch"}

# Fonti AI: i laboratori quando parlano in prima persona, piu' chi li segue di
# mestiere. Alimentano il presidio AI del radar, che e' una casella fissa.
# Anthropic non ha un feed: il suo sito non espone RSS a nessun indirizzo noto
# (provati news/rss.xml, rss.xml, feed.xml, index.xml — tutti 404 il 9 agosto
# 2026). Passa dalle testate qui sotto, che la coprono tutte.
AI = {"OpenAI", "Google DeepMind", "The Decoder", "TechCrunch AI",
      "Ars Technica AI", "MIT Technology Review AI"}

# Fonti da banco: la concorrenza e chi la prova. Non sono materia da rassegna
# Apple, sono materia da lavoro — un cliente che chiede del pieghevole Samsung
# ha visto la recensione, non il comunicato. Da qui nasce la sezione "Sul banco".
BANCO = {"DDay.it", "HDblog", "GSMArena", "Android Authority",
         "Andrea Galeazzi", "MKBHD"}


def _tier(name):
    if name in PRIMARY:
        return "primaria"
    if name in AI:
        return "ai"
    if name in BANCO:
        return "banco"
    return "larga" if name in BROAD else "redazionale"

# Il seme: da qui nasce data/sources.json la prima volta. Dopo di che il file
# comanda, e questo dizionario serve solo a ricordare gli indirizzi.
SEED = {
    "Apple Newsroom": "https://www.apple.com/newsroom/rss-feed.rss",
    "Apple Developer": "https://developer.apple.com/news/rss/news.rss",
    "9to5Mac": "https://9to5mac.com/feed/",
    "BGR": "https://bgr.com/feed/",
    "Macitynet": "https://www.macitynet.it/feed",
    "iSpazio": "https://www.ispazio.net/feed",
    "Tom's Hardware IT": "https://www.tomshw.it/feed",
    "Wired Italia": "https://www.wired.it/feed/rss",
    "MacRumors": "https://feeds.macrumors.com/MacRumors-All",
    "The Verge": "https://www.theverge.com/rss/index.xml",
    "Ars Technica": "https://feeds.arstechnica.com/arstechnica/index",
    "TechCrunch": "https://techcrunch.com/feed/",

    # AI — i laboratori e chi li segue
    "OpenAI": "https://openai.com/news/rss.xml",
    "Google DeepMind": "https://deepmind.google/blog/rss.xml",
    "The Decoder": "https://the-decoder.com/feed/",
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "Ars Technica AI": "https://arstechnica.com/ai/feed/",
    "MIT Technology Review AI": "https://www.technologyreview.com/topic/artificial-intelligence/feed",

    # Banco — la concorrenza e chi la prova, video compresi. I due canali
    # YouTube passano dal feed Atom pubblico, che non richiede chiave:
    # /feeds/videos.xml?channel_id=UC...
    "DDay.it": "https://www.dday.it/rss",
    "HDblog": "https://www.hdblog.it/feed/",
    "GSMArena": "https://www.gsmarena.com/rss-news-reviews.php3",
    "Android Authority": "https://www.androidauthority.com/feed/",
    "Andrea Galeazzi": "https://www.youtube.com/feeds/videos.xml?channel_id=UC5yXB_ThsufRJYMRlzIGoeQ",
    "MKBHD": "https://www.youtube.com/feeds/videos.xml?channel_id=UCBJycsmduvYEL83R_U4JriQ",
}


def _io():
    """Import ritardato: sources.py viene importato da fetch.py, che non deve
    dipendere da common.py per una cosa cosi' piccola."""
    import json
    return json


def load():
    """Il registro. Se non esiste ancora, lo crea dal seme."""
    json = _io()
    if not os.path.exists(SOURCES_FILE):
        today = _today()
        reg = {name: {"url": url, "state": "attiva",
                      "tier": _tier(name),
                      "since": today, "reason": "", "checked": None, "history": []}
               for name, url in SEED.items()}
        save(reg)
        return reg
    with open(SOURCES_FILE, encoding="utf-8") as fh:
        reg = json.load(fh)
    # una fonte nuova nel seme entra da sola, senza toccare le altre
    changed = False
    for name, url in SEED.items():
        if name not in reg:
            reg[name] = {"url": url, "state": "attiva",
                         "tier": _tier(name),
                         "since": _today(), "reason": "", "checked": None, "history": []}
            changed = True
    if changed:
        save(reg)
    return reg


def save(reg):
    json = _io()
    os.makedirs(os.path.dirname(SOURCES_FILE), exist_ok=True)
    with open(SOURCES_FILE, "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(reg.items())), fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def _today():
    from datetime import date
    return date.today().isoformat()


def active(reg=None):
    """Le fonti da raccogliere oggi: nome -> indirizzo."""
    reg = reg if reg is not None else load()
    return {n: e["url"] for n, e in reg.items() if e.get("state") == "attiva"}


def tiers(reg=None):
    """Il girone di ogni fonte attiva: nome -> tier. Serve a fetch.py per
    marcare gli articoli, cosi' in scrittura si sa da che mucchio arrivano
    senza doverlo indovinare dal nome della testata."""
    reg = reg if reg is not None else load()
    return {n: e.get("tier") or _tier(n)
            for n, e in reg.items() if e.get("state") == "attiva"}


def by_tier(tier, reg=None):
    """Le fonti attive di un girone: nome -> indirizzo."""
    reg = reg if reg is not None else load()
    return {n: e["url"] for n, e in reg.items()
            if e.get("state") == "attiva" and (e.get("tier") or _tier(n)) == tier}


def benched(reg=None):
    reg = reg if reg is not None else load()
    return {n: e for n, e in reg.items() if e.get("state") == "panchina"}


def move(name, state, reason=""):
    """Sposta una fonte fra attiva e panchina, lasciando traccia."""
    reg = load()
    if name not in reg:
        return None
    entry = reg[name]
    if entry.get("state") == state:
        return entry
    today = _today()
    entry["state"] = state
    entry["since"] = today
    entry["reason"] = reason
    entry.setdefault("history", []).append(
        f"{today} {state}" + (f": {reason}" if reason else ""))
    save(reg)
    return entry


def mark_checked(name, note=""):
    reg = load()
    if name not in reg:
        return
    reg[name]["checked"] = _today()
    if note:
        reg[name].setdefault("history", []).append(f"{_today()} riprova: {note}")
    save(reg)


def due_for_retest(reg=None):
    """Le fonti in panchina che oggi tocca riprovare."""
    from datetime import date, datetime, timedelta
    reg = reg if reg is not None else load()
    out = []
    limit = (date.today() - timedelta(days=RETEST_DAYS)).isoformat()
    for name, e in benched(reg).items():
        last = e.get("checked") or e.get("since") or "0000-00-00"
        if last <= limit:
            out.append(name)
    return sorted(out)


def resolve(name, reg=None):
    """Accetta anche un pezzo di nome, cosi' da riga di comando si scrive poco."""
    reg = reg if reg is not None else load()
    if name in reg:
        return name
    hits = [n for n in reg if name.lower() in n.lower()]
    return hits[0] if len(hits) == 1 else None
