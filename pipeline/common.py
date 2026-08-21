#!/usr/bin/env python3
"""
Funzioni condivise da threads.py, claims.py e feedcheck.py.

Qui stanno tre cose: la lettura e riscrittura dell'archivio locale
(data/briefs/), la normalizzazione del testo usata per confrontare titoli
fra loro, e le stampe a colonne dei rapporti.

L'archivio e' la fonte di verita': fili e pagelle non vivono in una tabella
separata ma dentro le edizioni stesse, cosi' viaggiano gia' verso Supabase
con push.py e restano dentro la copia Artifact, che non puo' fare rete.
"""

import glob
import json
import os
import re
import unicodedata
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIEFS_DIR = os.path.join(ROOT, "data", "briefs")
RAW_DIR = os.path.join(ROOT, "data", "raw")
THREADS_FILE = os.path.join(ROOT, "data", "threads.json")


# ---------------------------------------------------------------- archivio

def brief_paths():
    return sorted(glob.glob(os.path.join(BRIEFS_DIR, "*.json")))


def raw_paths():
    return sorted(glob.glob(os.path.join(RAW_DIR, "*.json")))


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path, payload):
    """Riscrive con lo stesso stile dei file gia' presenti: rientro di uno
    spazio e accenti veri, cosi' i diff restano leggibili."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


# Le edizioni gia' lette in questa corsa, per percorso: (mtime, payload).
# Un'edizione con le immagini incorporate pesa ~180 KB, e taste.py e lint.py
# rileggevano l'intero archivio piu' volte nella stessa corsa — tre passate su
# un anno di rassegne sono duecento megabyte di JSON per stampare una tabella.
# La chiave e' l'mtime: se un sync riscrive un'edizione, la copia decade da se'.
_CACHE = {}


def briefs(reverse=False):
    """Tutte le edizioni, dalla piu' vecchia. Ritorna (percorso, payload).

    Il payload e' condiviso fra le chiamate della stessa corsa: chi lo modifica
    deve poi salvarlo (threads.py e facts.py lo fanno), altrimenti si porta
    dietro la modifica senza scriverla."""
    out = []
    for p in brief_paths():
        stamp = os.stat(p).st_mtime_ns
        hit = _CACHE.get(p)
        if hit and hit[0] == stamp:
            payload = hit[1]
        else:
            payload = load_json(p)
            _CACHE[p] = (stamp, payload)
        out.append((p, payload))
    out.sort(key=lambda x: x[1].get("date", ""), reverse=reverse)
    return out


def stories(reverse=False):
    """Scorre tutte le notizie di tutte le edizioni: (data, edizione, notizia)."""
    for _, brief in briefs(reverse=reverse):
        for news in brief.get("news", []):
            yield brief.get("date", ""), brief, news


def today():
    return date.today().isoformat()


def days_between(a, b):
    """Giorni interi fra due date ISO (a - b). Tollera stringhe corte."""
    try:
        da = datetime.fromisoformat(str(a)[:10]).date()
        db = datetime.fromisoformat(str(b)[:10]).date()
    except ValueError:
        return None
    return (da - db).days


# ------------------------------------------------------------ testo, slug

STOPWORDS = {
    "che", "con", "per", "nel", "nei", "nella", "delle", "degli", "dei", "del",
    "della", "dal", "dalla", "una", "uno", "gli", "alla", "alle", "agli", "sul",
    "sulla", "sui", "come", "dopo", "anche", "ancora", "sono", "essere", "piu",
    "meno", "solo", "tutto", "tutti", "tutte", "quando", "dove", "questo",
    "questa", "queste", "questi", "suo", "sua", "loro", "the", "and", "for",
    "with", "from", "that", "this", "has", "have", "will", "why", "how", "what",
    "your", "you", "its", "are", "was", "were", "not", "but", "all", "new",
    "here", "now", "gets", "get", "could", "would", "may", "might", "into",
    "about", "over", "after", "before", "than", "then", "more", "most",
}


def deaccent(text):
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def slugify(text, limit=48):
    s = deaccent(str(text or "")).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:limit].strip("-")


def stem(word):
    """Taglia il plurale inglese, che altrimenti spezza i confronti:
    'prices' e 'price' sono la stessa parola in due titoli diversi."""
    if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokens(text):
    """Parole significative di un titolo, senza accenti ne' stopword.

    Numeri e sigle corte restano (iOS 27, M6, A20): sono proprio quelle che
    identificano una notizia Apple e sopravvivono alla traduzione."""
    s = deaccent(str(text or "")).lower()
    raw = re.findall(r"[a-z]+[0-9]*|[0-9]+", s)
    out = set()
    for w in raw:
        if w in STOPWORDS:
            continue
        if len(w) >= 4 or any(c.isdigit() for c in w):
            out.add(stem(w))
    return out


def entities(text):
    """Sottoinsieme piu' selettivo: nomi propri e sigle con numeri.

    Serve a riconoscere lo stesso fatto raccontato in due lingue diverse,
    dove le parole comuni non coincidono ma "iphone", "airpods", "m6" si'."""
    s = deaccent(str(text or ""))
    out = set()
    for w in re.findall(r"[A-Za-z]+[0-9]+|[A-Z][A-Za-z0-9]{2,}|[0-9]{2,}", s):
        low = w.lower()
        if low in STOPWORDS:
            continue
        out.add(low)
    return out


def similarity(a, b):
    """Quanto due titoli raccontano lo stesso fatto, fra 0 e 1.

    Due titoli sullo stesso fatto condividono le parole che contano ma
    quasi mai la stessa lunghezza: la sola intersezione su unione (Jaccard)
    penalizza il titolo lungo, il solo contenimento premia quello corto.
    La media dei due separa bene i casi veri dai vicini di argomento.

    Serve almeno un paio di parole in comune, altrimenti e' coincidenza."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    shared = ta & tb
    if len(shared) < 2:
        return 0.0
    jaccard = len(shared) / len(ta | tb)
    contain = len(shared) / min(len(ta), len(tb))
    score = (jaccard + contain) / 2

    # scorciatoia fra lingue diverse: le parole comuni non coincidono, i nomi
    # propri e le sigle si' (iPhone, AirPods, M6, iOS 27)
    ea, eb = entities(a), entities(b)
    se = ea & eb
    if len(se) >= 2:
        score = max(score, len(se) / len(ea | eb))
    return score


# Parametri che non identificano niente: campagne, provenienza, sessioni.
# Tolti questi, due indirizzi uguali restano uguali.
#
# Si confronta il *nome* del parametro, non la coppia intera: un parametro
# arriva come "fbclid=IwAR123", e una regola ancorata con "$" sul solo nome non
# poteva combaciare con niente. Per questo fino a oggi l'unica riga che lavorava
# davvero era "utm_", e due link identici a meno del fbclid passavano per
# diversi — la deduplica della raccolta se li teneva tutti e due.
TRACKING = re.compile(
    r"^(utm_.*|fbclid|gclid|igshid|mc_cid|mc_eid|cmpid|ref|ref_src|"
    r"source|src|s|si|t|feature|at_medium|at_campaign|__twitter.*)$", re.I)


def norm_url(url):
    """L'indirizzo ridotto a cio' che identifica la pagina.

    La query non si butta via in blocco: su YouTube *e'* l'indirizzo
    (watch?v=...), e tagliandola tutti i video del mondo diventano lo stesso
    link — che e' esattamente come sparivano dalla raccolta prima di questa
    riga. Si tolgono solo i parametri di tracciamento."""
    u = re.sub(r"#.*$", "", str(url or "")).strip()
    base, _, query = u.partition("?")
    keep = sorted(p for p in query.split("&")
                  if p and not TRACKING.match(p.partition("=")[0]))
    base = re.sub(r"^https?://(www\.)?", "", base).rstrip("/").lower()
    return base + ("?" + "&".join(keep) if keep else "")


def domain(url):
    m = re.match(r"https?://([^/]+)", str(url or ""))
    return re.sub(r"^www\.", "", m.group(1)).lower() if m else ""


# ------------------------------------------------------------ stampa

def table(rows, headers, gap=2):
    """Tabella a larghezza fissa. rows e' una lista di liste di stringhe.

    Le righe corte si pareggiano invece di troncare: con zip() una sola riga
    con una cella in meno faceva sparire l'ultima colonna da *tutta* la
    tabella, intestazione compresa, e il rapporto usciva sbagliato in
    silenzio."""
    n = len(headers)
    padded = [[str(c) for c in r[:n]] + [""] * (n - len(r[:n])) for r in rows]
    widths = [max([len(str(headers[i]))] + [len(r[i]) for r in padded])
              for i in range(n)]
    line = (" " * gap).join(str(h).ljust(w) for h, w in zip(headers, widths))
    out = [line, (" " * gap).join("-" * w for w in widths)]
    for r in padded:
        out.append((" " * gap).join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
    return "\n".join(out)


def rule(title):
    return f"\n{title}\n{'=' * len(title)}"
