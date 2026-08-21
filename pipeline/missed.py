#!/usr/bin/env python3
"""
Se te lo fossi perso: quello che ha girato, e che noi non abbiamo dato.

La rassegna guarda le ultime 26 ore e il perimetro Apple. E' la sua forza e
il suo buco: una cosa che esplode di martedi' fuori perimetro non entra mai,
e resta fuori per sempre — nessun giorno successivo la ripescherebbe, perche'
ogni giorno guarda solo il proprio.

Questo script guarda indietro, da 3 a 14 giorni, e cerca **due segnali di
massa** insieme:

  copertura    quante testate diverse fra le nostre hanno raccontato lo stesso
               fatto. Sei redazioni sullo stesso pezzo non e' un caso.
  trazione     quanto ne hanno parlato le persone: punti e commenti su Hacker
               News, posizione nel "top della settimana" di Reddit.

Poi toglie tutto quello che e' gia' passato in edizione — e' il senso del
nome: se te l'ho gia' dato non te lo sei perso — e stampa quel che resta,
ordinato. La scelta finale resta editoriale: qui escono candidati, non voci.

    python3 pipeline/missed.py                 i candidati di oggi
    python3 pipeline/missed.py --from 2 --to 21
    python3 pipeline/missed.py --offline       solo archivio, senza rete

Nota sull'archivio giovane: la copertura si misura su data/raw/, quindi nelle
prime due settimane di vita del progetto quel segnale e' quasi muto e i
candidati arrivano quasi tutti dalla trazione online. E' normale, si riempie
da solo.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common as C
from fetch import download, strip_html, parse_date
from social import REDDIT_UA, REDDIT_RETRY_S, RITUAL_RE

MISSED_DIR = os.path.join(C.ROOT, "data", "missed")
ATOM = {"atom": "http://www.w3.org/2005/Atom"}

# la finestra: si parte da 3 giorni indietro perche' sotto quella soglia non
# e' "se te lo fossi perso", e' la rassegna di ieri
FROM_DAYS, TO_DAYS = 3, 14

# due articoli oltre questa soglia raccontano lo stesso fatto
CLUSTER = 0.45
# quanto basta per dire "questo gliel'abbiamo gia' dato": piu' largo del
# raggruppamento, perche' in caso di dubbio si preferisce non ripetersi
ALREADY = 0.38

# le soglie della trazione: sotto, e' una discussione qualsiasi
HN_FLOOR = 120
HN_BIG = 400
# le bacheche dove si misura la settimana. Non solo Apple: il punto e'
# accorgersi di cosa e' passato *fuori* dal nostro perimetro.
WEEK_SUBS = ["technology", "gadgets", "apple", "android", "artificial"]
KEEP_REDDIT_WEEK = 25

# Il perimetro delle voci "solo online". Hacker News premia anche il saggio
# personale, il progetto della domenica e il necrologio: cose belle e del
# tutto inutili qui. Una voce senza un'azienda, un prodotto o un tema
# riconoscibile non e' una notizia che ci siamo persi, e' la prima pagina di
# HN. La copertura non ha bisogno di questo filtro: se sei testate hanno
# scritto la stessa cosa, e' gia' una notizia per definizione.
PERIMETRO = re.compile(
    r"\b(apple|iphone|ipad|mac(book|os)?|ios|ipados|airpods|airtag|vision ?pro|"
    r"watchos|siri|app ?store|icloud|"
    r"samsung|galaxy|pixel|android|google|deepmind|gemini|chrome|"
    r"microsoft|windows|copilot|meta|whatsapp|instagram|"
    r"openai|chatgpt|gpt-?\d|anthropic|claude|mistral|llama|qwen|deepseek|kimi|"
    r"hugging ?face|open.?weights?|modell[oi]|inferenza|token|benchmark|"
    r"nvidia|amd|intel|qualcomm|tsmc|arm|chip|silicio|gpu|processor[ei]?|"
    r"amazon|tesla|spacex|starlink|netflix|spotify|tiktok|twitter|reddit|"
    r"privacy|gdpr|antitrust|regolament\w+|garante|commissione|sorveglianza|"
    r"browser|firefox|safari|linux|kernel|open.?source|"
    r"smartphone|pieghevol\w+|laptop|display|batteri\w+|ricarica|usb|"
    r"bluetooth|wi.?fi|cuffie|visore|smartwatch)\b", re.I)
# le sigle vanno guardate rispettando le maiuscole: "ai" in italiano e' una
# preposizione, "AI" no
PERIMETRO_SIGLE = re.compile(r"\b(AI|LLMs?|API|VPN|CPU|GPU|OS|EU|UE)\b")
# i domini che sono di per se' dentro al perimetro: se lo pubblica un
# laboratorio o una testata tech, di cosa parli lo sappiamo gia'
DOMINI = re.compile(
    r"(anthropic\.com|openai\.com|deepmind\.google|ai\.googleblog|huggingface\.co|"
    r"blog\.google|apple\.com|developer\.apple\.com|techcrunch|theverge|"
    r"arstechnica|9to5mac|macrumors|wired\.|engadget|tomshw|dday\.it|hdblog|"
    r"gsmarena|androidauthority|technologyreview|the-decoder)", re.I)
# le vetrine di HN: annunci di progetti, non notizie
HN_RITUALI = re.compile(r"^\s*(show|ask|tell) hn\b", re.I)

# quanto vale ogni segnale. La copertura pesa piu' della trazione: mille voti
# li fa anche una polemica, sei redazioni no.
W_SOURCE = 2.0
W_HN_BIG, W_HN_MID = 3.0, 1.5
W_REDDIT_TOP = 1.5
W_TESTATA = 1.0
# sotto questo punteggio non e' roba da ripescare
FLOOR = 4.0
# quanti candidati stampare: il file li tiene tutti
SHOW = 12


# ------------------------------------------------------------------ archivio

def raw_window(first, last):
    """Gli articoli grezzi con data fra due giorni compresi."""
    items = []
    for path in C.raw_paths():
        day = os.path.basename(path)[:-5]
        # il file di un giorno contiene una finestra di 26 ore: puo' portarsi
        # dietro articoli del giorno prima, quindi si legge un po' piu' largo
        # e si filtra sulla data vera dell'articolo
        if not (first <= day <= (date.fromisoformat(last) + timedelta(days=1)).isoformat()):
            continue
        for it in C.load_json(path).get("items", []):
            when = (it.get("date") or "")[:10]
            if first <= when <= last:
                items.append(it)
    return items


def already_published():
    """Quello che e' gia' uscito: indirizzi e titoli, da tutte le edizioni."""
    urls, titles = set(), []
    for _, b in C.briefs():
        for n in b.get("news", []):
            if n.get("link"):
                urls.add(C.norm_url(n["link"]))
            for extra in n.get("extra_links") or []:
                if extra.get("url"):
                    urls.add(C.norm_url(extra["url"]))
            titles.append(n.get("title", ""))
        for section in ("radar", "banco", "recap"):
            for v in b.get(section) or []:
                if v.get("link"):
                    urls.add(C.norm_url(v["link"]))
                titles.append(v.get("title", ""))
    return urls, [t for t in titles if t]


# ---------------------------------------------------------------- copertura

def cluster(items):
    """Raggruppa gli articoli che raccontano lo stesso fatto.

    Greedy e volutamente ottuso: si confronta ogni pezzo con il capofila di
    ogni gruppo, non con tutti i membri. Su qualche centinaio di titoli
    costa niente e sbaglia poco, perche' il capofila e' il primo arrivato e
    quindi di solito il piu' asciutto."""
    groups = []
    for it in sorted(items, key=lambda x: x.get("date") or ""):
        for g in groups:
            if C.similarity(it.get("title", ""), g["capo"]) >= CLUSTER:
                g["items"].append(it)
                break
        else:
            groups.append({"capo": it.get("title", ""), "items": [it]})
    return groups


def pick_link(items):
    """L'articolo da linkare: la fonte piu' autorevole, e a parita' la prima
    arrivata. Fra due che dicono la stessa cosa vince chi l'ha detta prima."""
    order = {"primaria": 0, "redazionale": 1, "ai": 1, "banco": 2, "larga": 2}
    best = sorted(items, key=lambda i: (order.get(i.get("tier"), 3),
                                        i.get("date") or ""))[0]
    return best


# ----------------------------------------------------------------- trazione

def hacker_news(first, last):
    """Le storie che hanno tirato su Hacker News nella finestra.

    Nessuna parola chiave: qui non si cerca Apple, si cerca cosa ha guardato
    tutto il mestiere. Il filtro Apple lo fa l'edizione, non la raccolta."""
    since = int(datetime.fromisoformat(first).replace(tzinfo=timezone.utc).timestamp())
    until = int((datetime.fromisoformat(last).replace(tzinfo=timezone.utc)
                 + timedelta(days=1)).timestamp())
    url = ("https://hn.algolia.com/api/v1/search?tags=story"
           f"&numericFilters=created_at_i%3E{since},created_at_i%3C{until},"
           f"points%3E{HN_FLOOR}&hitsPerPage=100")
    _, _, blob = download("hn", url)
    if not blob:
        return []
    try:
        hits = json.loads(blob.decode("utf-8", "replace")).get("hits", [])
    except ValueError:
        return []
    out = []
    for h in hits:
        if not h.get("title"):
            continue
        out.append({
            "platform": "Hacker News",
            "title": strip_html(h["title"]),
            "link": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            "discussion": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            "when": (h.get("created_at") or "")[:10],
            "points": h.get("points") or 0,
            "comments": h.get("num_comments") or 0,
        })
    out.sort(key=lambda x: -x["points"])
    return out


def reddit_week():
    """Il top della settimana, non del giorno: e' l'unita' che serve qui."""
    url = "https://www.reddit.com/r/" + "+".join(WEEK_SUBS) + "/top/.rss?t=week"
    root = None
    for attempt in (0, 1):
        blob = subprocess.run(["curl", "-sL", "--max-time", "25", "-A", REDDIT_UA, url],
                              capture_output=True).stdout
        if blob:
            try:
                root = ET.fromstring(blob.lstrip(b"\xef\xbb\xbf \t\r\n"))
                break
            except ET.ParseError:
                pass
        if attempt == 0:
            time.sleep(REDDIT_RETRY_S)
    if root is None:
        print("  Reddit non ha risposto (limite di frequenza): si va avanti "
              "con la sola copertura e Hacker News.", file=sys.stderr)
        return []

    out = []
    for i, entry in enumerate(root.findall("atom:entry", ATOM)):
        el = entry.find("atom:title", ATOM)
        title = strip_html(el.text if el is not None and el.text else "")
        if not title or RITUAL_RE.search(title):
            continue
        link_el = entry.find("atom:link", ATOM)
        upd = entry.find("atom:updated", ATOM)
        when = parse_date(upd.text if upd is not None else "")
        cat = entry.find("atom:category", ATOM)
        out.append({
            "platform": f"Reddit {cat.get('label') if cat is not None else ''}".strip(),
            "rank": i + 1,
            "title": title,
            "link": link_el.get("href", "") if link_el is not None else "",
            "when": when.date().isoformat() if when else "",
        })
        if len(out) >= KEEP_REDDIT_WEEK:
            break
    return out


# ----------------------------------------------------------------- giudizio

def match(title, url, pool):
    """La voce social che parla dello stesso fatto, se c'e'."""
    nu = C.norm_url(url)
    for p in pool:
        if nu and nu == C.norm_url(p.get("link")):
            return p
    for p in pool:
        if C.similarity(title, p.get("title", "")) >= 0.40:
            return p
    return None


def score_group(g, hn, reddit):
    """Da gruppo di articoli a candidato, con il perche' gia' scritto."""
    lead = pick_link(g["items"])
    srcs = sorted({i["source"] for i in g["items"]})
    days = sorted({(i.get("date") or "")[:10] for i in g["items"] if i.get("date")})

    punti, motivi = W_SOURCE * len(srcs), []
    if len(srcs) >= 2:
        arco = C.days_between(days[-1], days[0]) if len(days) > 1 else 0
        motivi.append(f"{len(srcs)} testate" + (f" in {arco + 1} giorni" if arco else ""))

    h = match(lead.get("title", ""), lead.get("link", ""), hn)
    if h:
        punti += W_HN_BIG if h["points"] >= HN_BIG else W_HN_MID
        motivi.append(f"{h['points']} punti e {h['comments']} commenti su Hacker News")
    r = match(lead.get("title", ""), lead.get("link", ""), reddit)
    if r and r["rank"] <= 10:
        punti += W_REDDIT_TOP
        motivi.append(f"{r['rank']}º della settimana su {r['platform']}")

    return {
        "id": C.slugify(lead.get("title", ""), 40),
        "genere": "notizia",
        "title": lead.get("title", ""),
        "link": lead.get("link", ""),
        "source": lead.get("source", ""),
        "sources": srcs,
        "when": days[0] if days else (lead.get("date") or "")[:10],
        "signal": ", ".join(motivi),
        "discussione": (h or {}).get("discussion"),
        "punti": round(punti, 1),
        "origine": "copertura",
    }


def orphan_candidates(hn, reddit, urls, titles, first, last):
    """Le storie che hanno tirato online e che le nostre fonti non hanno mai
    dato. Sono le piu' interessanti delle due famiglie: non e' che ce le siamo
    perse noi, e' che non le avremmo mai avute."""
    out = []
    for h in hn:
        if h["points"] < HN_BIG:
            continue
        if not (first <= h["when"] <= last):
            continue
        if HN_RITUALI.match(h["title"]):
            continue
        if not (DOMINI.search(h["link"] or "")
                or PERIMETRO.search(h["title"])
                or PERIMETRO_SIGLE.search(h["title"])):
            continue
        if C.norm_url(h["link"]) in urls:
            continue
        if any(C.similarity(h["title"], t) >= ALREADY for t in titles):
            continue
        punti = W_HN_BIG + (h["points"] / 500.0)
        motivi = [f"{h['points']} punti e {h['comments']} commenti su Hacker News"]
        # una redazione o un laboratorio raccontano un fatto; un blog personale
        # quasi sempre commenta un fatto altrui. Il commento non si butta — a
        # volte e' proprio lo spunto — ma sta sotto la notizia
        notizia = bool(DOMINI.search(h["link"] or ""))
        if notizia:
            punti += W_TESTATA
        r = match(h["title"], h["link"], reddit)
        if r and r["rank"] <= 10:
            punti += W_REDDIT_TOP
            motivi.append(f"{r['rank']}º della settimana su {r['platform']}")
        out.append({
            "genere": "notizia" if notizia else "commento",
            "id": C.slugify(h["title"], 40),
            "title": h["title"],
            "link": h["link"],
            "source": C.domain(h["link"]) or "Hacker News",
            "sources": [],
            "when": h["when"],
            "signal": ", ".join(motivi),
            "discussione": h["discussion"],
            "punti": round(punti, 1),
            "origine": "solo online",
        })
    return out


# ------------------------------------------------------------------- stampa

def report(cands, first, last, coperti):
    print(C.rule(f"Se te lo fossi perso — dal {first} al {last}"))
    if not cands:
        print("Niente da ripescare: quello che ha girato lo abbiamo gia' dato.")
        print(f"({coperti} gruppi di articoli guardati.)")
        return
    for c in cands[:SHOW]:
        eta = C.days_between(C.today(), c["when"])
        tag = "SOLO ONLINE" if c["origine"] == "solo online" else "COPERTURA  "
        if c.get("genere") == "commento":
            tag = "COMMENTO   "
        print(f"\n  [{tag}] {c['punti']:>4}  {c['title'][:88]}")
        print(f"    {c['when']} ({eta} giorni fa) · {c['signal']}")
        if c["sources"]:
            print(f"    fonti: {', '.join(c['sources'])}")
        print(f"    {c['link']}")
        if c.get("discussione"):
            print(f"    discussione: {c['discussione']}")
    resto = max(0, len(cands) - SHOW)
    print(f"\n{len(cands)} candidati su {coperti} gruppi"
          + (f" (ne vedi {SHOW}, gli altri {resto} nel file)" if resto else "")
          + ". Da 0 a 3 in edizione,\ne solo se reggono da soli: la sezione "
            "puo' benissimo non uscire.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("--from", dest="da", type=int, default=FROM_DAYS,
                    help="quanti giorni indietro comincia la finestra")
    ap.add_argument("--to", dest="a", type=int, default=TO_DAYS,
                    help="quanti giorni indietro finisce la finestra")
    ap.add_argument("--offline", action="store_true",
                    help="non interroga Hacker News ne' Reddit")
    args = ap.parse_args()

    oggi = date.today()
    last = (oggi - timedelta(days=args.da)).isoformat()
    first = (oggi - timedelta(days=args.a)).isoformat()

    items = raw_window(first, last)
    groups = cluster(items)
    urls, titles = already_published()

    hn = [] if args.offline else hacker_news(first, last)
    reddit = [] if args.offline else reddit_week()

    cands = []
    for g in groups:
        lead = pick_link(g["items"])
        if C.norm_url(lead.get("link")) in urls:
            continue
        if any(C.similarity(lead.get("title", ""), t) >= ALREADY for t in titles):
            continue
        c = score_group(g, hn, reddit)
        if c["punti"] >= FLOOR:
            cands.append(c)

    cands += orphan_candidates(hn, reddit, urls, titles, first, last)

    # due candidati possono raccontare la stessa cosa da porte diverse
    unici, visti = [], []
    for c in sorted(cands, key=lambda x: -x["punti"]):
        if any(C.similarity(c["title"], v) >= CLUSTER for v in visti):
            continue
        visti.append(c["title"])
        unici.append(c)

    os.makedirs(MISSED_DIR, exist_ok=True)
    C.save_json(os.path.join(MISSED_DIR, f"{oggi.isoformat()}.json"), {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window": {"from": first, "to": last},
        "gruppi": len(groups),
        "candidati": unici,
    })
    report(unici, first, last, len(groups))
    return 0


if __name__ == "__main__":
    sys.exit(main())
