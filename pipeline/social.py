#!/usr/bin/env python3
"""
Cosa si dice, oltre a cosa si scrive.

Le testate raccontano i fatti; le discussioni raccontano come vengono presi, e
ogni tanto ci nasce dentro qualcosa che i giornali non hanno ancora. Questo
script raccoglie il secondo pezzo e lo mette in data/social/YYYY-MM-DD.json,
separando le due cose che contano davvero:

  eco     si discute di una notizia che abbiamo gia' nel file grezzo
  nuovo   se ne parla e da noi non c'e' — e' li' che vale la pena guardare

Da dove:

  Reddit           i feed RSS "top del giorno" dei subreddit Apple. Ordinati
                   da Reddit stessa per voti, quindi la posizione e' il segnale.
                   L'API JSON risponde 403 senza autenticazione: si usa l'RSS.
  Hacker News      l'API pubblica di Algolia, che da' punti e commenti veri.
  Appunti a mano   data/social/manual.md, dove incolli quello che hai visto
                   altrove — X in primis.

Su X non c'e' una strada onesta: niente RSS, niente API gratuita, e raschiare
le pagine viola le condizioni oltre a rompersi ogni due settimane. Il modo che
funziona e' l'altro: quando vedi un thread che conta, incolli il link in
manual.md con una riga di contesto, e da li' entra nella rassegna come tutto
il resto — con la sua fonte e la sua data.

    python3 pipeline/social.py                  raccolta di oggi
    python3 pipeline/social.py --hours 36
    python3 pipeline/social.py --show           rilegge l'ultimo file raccolto
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common as C
from fetch import UA, download, parse_date, strip_html

SOCIAL_DIR = os.path.join(C.ROOT, "data", "social")
MANUAL_FILE = os.path.join(SOCIAL_DIR, "manual.md")

ATOM = {"atom": "http://www.w3.org/2005/Atom"}

# I subreddit dove si parla di Apple con un minimo di sostanza. r/apple e'
# quello che conta; gli altri servono a intercettare i temi di nicchia che
# arrivano in superficie solo dopo giorni.
SUBS = ["apple", "iphone", "mac", "ios", "AppleWatch", "VisionPro"]

# Quante voci tenere da Reddit e da Hacker News: oltre e' rumore.
KEEP_REDDIT = 14
KEEP_HN = 8

# Reddit limita le richieste ravvicinate dallo stesso indirizzo: in parallelo
# risponde 429 a tutte tranne la prima. Si va in fila, con una pausa, e ci si
# presenta con un nome vero: le loro regole chiedono un User-Agent che dica chi
# sei, e con quello generico del browser la stretta e' molto piu' dura.
REDDIT_UA = "morning-brief/1.0 (rassegna stampa personale; contatto via GitHub)"
REDDIT_RETRY_S = 15

# Nei subreddit di prodotto meta' dei post e' assistenza: telefoni che non si
# accendono, batterie, schermi. Non si buttano, si mettono da parte — a volte
# un problema ricorrente e' una notizia (vedi antennagate).
SUPPORT_RE = re.compile(
    r"\b(help|fix(ed)?|broken|won'?t|doesn'?t|stopped|not working|issue|"
    r"problem|repair|replace(d|ment)?|warranty|boot ?loop|burn.?in|"
    r"battery health|scratch|crack|dead|stuck|why (is|does|won)|"
    r"how (do|can) i|should i (buy|get|upgrade)|is it normal|worth it)\b", re.I)

# I post fissi della settimana: tornano sempre uguali, non sono mai notizia.
RITUAL_RE = re.compile(
    r"\b(weekly|daily|monthly)\b.*\b(thread|discussion|advice)\b|"
    r"\bmegathread\b|\bwallpaper wednesday\b", re.I)

# La vetrina: acquisti, foto, quadranti, "guardate cosa ho fatto". Tiene su
# i voti nei subreddit di prodotto e non dice niente su Apple.
SHOWCASE_RE = re.compile(
    r"\b(my (new|first)|got my|just got|finally got|unboxing|arrived today|"
    r"what do you (think|guys)|thoughts\?|rate my|setup|collection|"
    r"hand.?(made|engraved)|saved my life|first apple)\b|"
    r"^\s*(new|my)\s+\w+\s*[:!]?\s*$", re.I)

# Sotto questi numeri una discussione su HN non ha ancora massa critica.
HN_MIN_POINTS = 25

APPLE_WORDS = re.compile(
    r"\b(apple|iphone|ipad|mac|macbook|imac|ios|ipados|macos|watchos|visionos|"
    r"tvos|airpods|airtag|homepod|vision\s?pro|apple\s?watch|siri|app\s?store|"
    r"icloud|tim\s?cook|cupertino|carplay|facetime|imessage)\b", re.I)


# ---------------------------------------------------------------- raccolta

def reddit(cutoff):
    """Il "top del giorno" di tutti i subreddit Apple, in una richiesta sola.

    Reddit permette di sommare piu' bacheche in un unico feed con il "+", e
    conviene: sei richieste ravvicinate si prendono un 429, una no. In piu' il
    ranking cosi' e' globale, quindi la posizione dice quanto un tema ha tirato
    rispetto a tutti gli altri, non solo dentro la sua nicchia."""
    url = ("https://www.reddit.com/r/" + "+".join(SUBS) + "/top/.rss?t=day")
    root = None
    for attempt in (0, 1):
        blob = subprocess.run(
            ["curl", "-sL", "--max-time", "25", "-A", REDDIT_UA, url],
            capture_output=True).stdout
        if blob:
            try:
                root = ET.fromstring(blob.lstrip(b"\xef\xbb\xbf \t\r\n"))
                break
            except ET.ParseError:
                pass
        if attempt == 0:
            time.sleep(REDDIT_RETRY_S)   # quasi sempre e' un 429: si aspetta
    if root is None:
        print("  Reddit non ha risposto: e' un limite di frequenza, riprova "
              "fra qualche minuto.", file=sys.stderr)
        return []

    out = []
    for i, entry in enumerate(root.findall("atom:entry", ATOM)):
        def txt(tag):
            el = entry.find(tag, ATOM)
            return (el.text or "").strip() if el is not None else ""

        link_el = entry.find("atom:link", ATOM)
        link = link_el.get("href", "") if link_el is not None else ""
        cat = entry.find("atom:category", ATOM)
        sub = cat.get("label") if cat is not None else "Reddit"
        when = parse_date(txt("atom:updated") or txt("atom:published"))
        if when and when < cutoff:
            continue
        title = strip_html(txt("atom:title"))
        if RITUAL_RE.search(title):
            continue
        out.append({
            "platform": f"Reddit {sub}",
            "rank": i + 1,
            "title": title,
            "link": link,
            "author": txt("atom:author/atom:name"),
            "when": when.isoformat() if when else None,
            "tipo": ("assistenza" if SUPPORT_RE.search(title)
                     else "vetrina" if SHOWCASE_RE.search(title)
                     else "discussione"),
            "signal": f"{i + 1}º fra i più votati del giorno su {sub}",
        })
        if len(out) >= KEEP_REDDIT:
            break
    return out


def hackernews(cutoff):
    """Le discussioni su Apple con punti e commenti veri."""
    since = int(cutoff.timestamp())
    url = ("https://hn.algolia.com/api/v1/search_by_date?query=apple&tags=story"
           f"&numericFilters=created_at_i%3E{since},points%3E{HN_MIN_POINTS}"
           "&hitsPerPage=40")
    _, _, blob = download("hn", url)
    if not blob:
        return []
    try:
        hits = json.loads(blob.decode("utf-8", "replace")).get("hits", [])
    except ValueError:
        return []

    out = []
    for h in hits:
        title = h.get("title") or ""
        if not APPLE_WORDS.search(title + " " + (h.get("story_text") or "")):
            continue
        points, comments = h.get("points") or 0, h.get("num_comments") or 0
        out.append({
            "platform": "Hacker News",
            "rank": None,
            "title": strip_html(title),
            "link": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            "discussion": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            "author": h.get("author"),
            "when": h.get("created_at"),
            "points": points,
            "comments": comments,
            "tipo": "discussione",
            "signal": f"{points} punti, {comments} commenti su Hacker News",
        })
    out.sort(key=lambda x: -(x["points"] + x["comments"]))
    return out[:KEEP_HN]


def manual():
    """Quello che hai incollato a mano in data/social/manual.md.

    Formato libero, una voce per riga che inizia con un trattino:

        - https://x.com/... — Gurman risponde nei commenti sul taglio dell'M6
        - https://x.com/... (2026-08-09) — thread sul prezzo del pieghevole

    Le righe che iniziano con # sono commenti tuoi e vengono ignorate.
    """
    if not os.path.exists(MANUAL_FILE):
        return []
    out = []
    with open(MANUAL_FILE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("-") or line.startswith("#"):
                continue
            line = line.lstrip("- ").strip()
            m = re.search(r"https?://\S+", line)
            if not m:
                continue
            link = m.group(0).rstrip(".,;)")
            rest = (line[:m.start()] + line[m.end():]).strip(" —-–:")
            date_m = re.search(r"\((\d{4}-\d{2}-\d{2})\)", rest)
            when = date_m.group(1) if date_m else None
            if date_m:
                rest = (rest[:date_m.start()] + rest[date_m.end():]).strip(" —-–:")
            host = C.domain(link)
            name = {"x.com": "X", "twitter.com": "X", "threads.net": "Threads",
                    "bsky.app": "Bluesky", "mastodon.social": "Mastodon"}.get(host, host)
            out.append({
                "platform": name or "appunto",
                "rank": None,
                "title": rest or link,
                "link": link,
                "author": None,
                "when": when,
                "signal": "segnalato a mano",
                "tipo": "discussione",
                "manual": True,
            })
    return out


# ------------------------------------------------------------------- eco

def today_titles():
    """I titoli che le nostre fonti hanno gia' dato oggi e ieri."""
    titles = []
    for path in C.raw_paths()[-2:]:
        titles += [i.get("title", "") for i in C.load_json(path).get("items", [])]
    return titles


def classify(items, titles):
    """Segna ogni voce come eco di una notizia nostra o come materiale nuovo."""
    for it in items:
        hit = None
        for t in titles:
            if C.similarity(it.get("title", ""), t) >= 0.38:
                hit = t
                break
        it["origine"] = "eco" if hit else "nuovo"
        if hit:
            it["eco_di"] = hit[:110]
    return items


# ------------------------------------------------------------------ stampa

def report(payload):
    items = payload["items"]
    talk = [i for i in items if i.get("tipo") == "discussione"]
    support = [i for i in items if i.get("tipo") in ("assistenza", "vetrina")]
    nuovo = [i for i in talk if i.get("origine") == "nuovo"]
    eco = [i for i in talk if i.get("origine") == "eco"]

    print(C.rule(f"Nasce nelle discussioni — {len(nuovo)}"))
    if not nuovo:
        print("Niente che non abbiamo gia' dalle testate.")
    for i in nuovo:
        print(f"\n  [{i['platform']}] {i['title'][:96]}")
        print(f"    {i['signal']}")
        print(f"    {i['link']}")

    print(C.rule(f"Commenta quello che abbiamo gia' — {len(eco)}"))
    for i in eco:
        print(f"  [{i['platform']}] {i['title'][:80]}")
        print(f"      su: {i.get('eco_di','')}")

    if support:
        print(C.rule(f"Messi da parte: assistenza e vetrina — {len(support)}"))
        for i in support[:8]:
            print(f"  [{i['tipo']}] {i['title'][:76]}")
        print("\n  Uno alla volta non contano. Se lo stesso guasto torna per "
              "giorni, allora\n  si', e diventa una notizia.")

    print("\nRegola: qui dentro non ci sono fatti, ci sono opinioni e voci. "
          "Quello che\nfinisce in edizione va marcato come tale — vedi CLAUDE.md, "
          "sezione social.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("--hours", type=float, default=26.0)
    ap.add_argument("--show", action="store_true",
                    help="rilegge l'ultimo file raccolto invece di raccogliere")
    args = ap.parse_args()

    os.makedirs(SOCIAL_DIR, exist_ok=True)

    if args.show:
        files = sorted(f for f in os.listdir(SOCIAL_DIR) if f.endswith(".json"))
        if not files:
            print("Ancora niente in data/social/.", file=sys.stderr)
            return 1
        report(C.load_json(os.path.join(SOCIAL_DIR, files[-1])))
        return 0

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=args.hours)

    items = reddit(cutoff) + hackernews(cutoff) + manual()

    # dedup per indirizzo: la stessa cosa gira su piu' bacheche
    seen, deduped = set(), []
    for it in items:
        k = C.norm_url(it.get("link"))
        if k and k in seen:
            continue
        seen.add(k)
        deduped.append(it)

    deduped = classify(deduped, today_titles())
    payload = {
        "fetched_at": now.isoformat(),
        "window_hours": args.hours,
        "count": len(deduped),
        "items": deduped,
    }
    out = os.path.join(SOCIAL_DIR, f"{now.astimezone().strftime('%Y-%m-%d')}.json")
    C.save_json(out, payload)

    print(f"Raccolte {len(deduped)} discussioni in {out}")
    report(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
