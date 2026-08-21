#!/usr/bin/env python3
"""
Salute delle fonti: stringere e allargare.

Due domande, una per verso.

Stringere — quali fonti stiamo tenendo per abitudine? Un feed puo' morire in
silenzio, ma puo' anche restare vivissimo e inutile: ripubblicare due ore dopo,
peggio scritto, quello che hanno gia' dato gli altri. Il primo caso si vede
subito, il secondo no, e intanto gonfia il file grezzo e il lavoro di lettura.
Il rapporto misura per ogni feed quanto arriva primo, quanto insegue e di
quanto, quanto porta di esclusivo e quanto finisce davvero in edizione.

Allargare — cosa non stiamo leggendo? Con --discover lo script prova una lista
di fonti candidate, misura quanto sono fresche, quanto parlano di Apple e
quanta roba portano che le nostre non hanno gia' dato.

    python3 pipeline/feedcheck.py                 rapporto sulle fonti attuali
    python3 pipeline/feedcheck.py --days 30       finestra di analisi
    python3 pipeline/feedcheck.py --discover      prova le candidate
    python3 pipeline/feedcheck.py --discover --hours 336   finestra piu' larga

Il verdetto e' una proposta, non un'esecuzione: FEEDS in fetch.py si tocca a
mano, dopo aver guardato i numeri.
"""

import argparse
import concurrent.futures as cf
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common as C
import sources as SRC
from fetch import FEEDS, TIERS, QUIET, QUIET_TOLERANCE_H, download, parse_feed

# due articoli sopra questa somiglianza raccontano lo stesso fatto
SAME_STORY = 0.38
# oltre questo silenzio un feed e' morto, non lento
DEAD_HOURS = 24 * 14
# quanto silenzio si concede ai gironi che pubblicano a strappi (ai, banco)
SLOW_HOURS = 24 * 35

APPLE_WORDS = re.compile(
    r"\b(apple|iphone|ipad|mac|macbook|imac|ios|ipados|macos|watchos|visionos|"
    r"tvos|airpods|airtag|homepod|vision\s?pro|apple\s?watch|siri|app\s?store|"
    r"icloud|tim\s?cook|cupertino|carplay|facetime|imessage|m[1-9]\s|a1[6-9]|a2[0-9])\b",
    re.I,
)

# ---------------------------------------------------------------------------
# Le candidate. Non e' una lista da adottare in blocco: e' il banco di prova.
# La colonna "perche'" dice cosa aggiungerebbe che oggi non abbiamo.
# ---------------------------------------------------------------------------
CANDIDATES = [
    ("Apple Newsroom", "https://www.apple.com/newsroom/rss-feed.rss",
     "la fonte primaria: comunicati ufficiali, affidabilita' massima per definizione"),
    ("Apple Developer News", "https://developer.apple.com/news/rss/news.rss",
     "beta, scadenze, cambi di regole App Store: fatti verificabili, zero rumor"),
    ("Apple Security Releases", "https://developer.apple.com/news/releases/rss/releases.rss",
     "rilasci e patch datati, utile per la cronologia software"),
    ("Apple Machine Learning", "https://machinelearning.apple.com/rss.xml",
     "i paper di ricerca AI: raro ma e' materiale di prima mano"),
    ("Six Colors", "https://sixcolors.com/feed/",
     "Jason Snell: analisi lente, poco rumore, ottime per il contesto"),
    ("Daring Fireball", "https://daringfireball.net/feeds/main",
     "Gruber: opinione con peso, spesso anticipa la lettura dominante"),
    ("MacStories", "https://www.macstories.net/feed/",
     "software e workflow, taglio diverso dai siti di rumor"),
    ("512 Pixels", "https://512pixels.net/feed/",
     "Stephen Hackett: storia e hardware, materiale da CONTESTO"),
    ("Michael Tsai", "https://mjtsai.com/blog/feed/",
     "rassegna tecnica con i link alle fonti primarie, ottimo controllo incrociato"),
    ("AppleInsider", "https://appleinsider.com/rss/news/",
     "volume alto, a volte primo: da valutare proprio sul rischio eco"),
    ("Cult of Mac", "https://www.cultofmac.com/feed",
     "volume alto, qualita' variabile: candidato tipico da bocciare sui numeri"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index",
     "approfondimento tecnico e cause legali, buon contorno"),
    ("Bloomberg Technology", "https://feeds.bloomberg.com/technology/news.rss",
     "la casa di Gurman: se il feed passa, e' la fonte piu' pesante del giro"),
    ("Techmeme", "https://www.techmeme.com/feed.xml",
     "aggregatore: non da citare, ma dice in fretta cosa sta diventando grosso"),
    ("The Register", "https://www.theregister.com/headlines.atom",
     "scettico e tecnico, buon antidoto all'entusiasmo"),
    ("Engadget", "https://www.engadget.com/rss.xml",
     "generalista, probabile eco: serve per misurare quanto e' eco"),
    ("iPhone Italia", "https://www.iphoneitalia.com/feed",
     "italiano: da pesare contro Macitynet e iSpazio, non aggiungerlo a scatola chiusa"),
    ("HDblog", "https://www.hdblog.it/feed/",
     "italiano generalista, volume alto: candidato tipico da bocciare"),
    ("DDay.it", "https://www.dday.it/rss",
     "italiano, buona parte tecnica e mercato"),
    ("Il Post — Tecnologia", "https://www.ilpost.it/tecnologia/feed/",
     "italiano, poche cose ma verificate: possibile sostituto di Wired Italia"),
]


# ------------------------------------------------------------------ raccolta

def load_window(days):
    """Gli scarichi grezzi degli ultimi N giorni."""
    limit = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    out = []
    for path in C.raw_paths():
        day = os.path.basename(path)[:10]
        if day >= limit:
            out.append((day, C.load_json(path)))
    return out


def cluster(items):
    """Raggruppa gli articoli di una giornata per fatto raccontato.

    Confronto a coppie sul titolo: sono un centinaio di elementi, il costo
    quadratico non si sente, e un algoritmo piu' furbo qui non aggiungerebbe
    precisione."""
    ordered = sorted(items, key=lambda x: x.get("date") or "")
    groups = []
    for it in ordered:
        title = it.get("title", "")
        for g in groups:
            if C.similarity(title, g[0].get("title", "")) >= SAME_STORY:
                g.append(it)
                break
        else:
            groups.append([it])
    return groups


def used_urls():
    """Gli indirizzi finiti in edizione, per capire cosa serve davvero."""
    urls, titles = set(), []
    for _, brief in C.briefs():
        for news in brief.get("news", []):
            if news.get("link"):
                urls.add(C.norm_url(news["link"]))
            for extra in news.get("extra_links") or []:
                if extra.get("url"):
                    urls.add(C.norm_url(extra["url"]))
            titles.append(news.get("title", ""))
        # radar, banco e ripescaggi contano quanto le notizie: una fonte che
        # finisce sempre "Sul banco" e mai fra le news sta servendo eccome,
        # e senza questa riga sembrerebbe inutile e finirebbe in panchina
        for sezione in ("radar", "banco", "recap"):
            for r in brief.get(sezione) or []:
                if r.get("link"):
                    urls.add(C.norm_url(r["link"]))
                titles.append(r.get("title", ""))
    return urls, titles


def hours_between(a, b):
    try:
        da = datetime.fromisoformat(a)
        db = datetime.fromisoformat(b)
    except (TypeError, ValueError):
        return None
    return round((da - db).total_seconds() / 3600, 1)


# -------------------------------------------------------------------- report

def cmd_report(args):
    window = load_window(args.days)
    if not window:
        print("Nessuno scarico in data/raw/. Lancia prima fetch.py.", file=sys.stderr)
        return 1

    stat = {name: {"items": 0, "solo": 0, "first": 0, "follow": 0, "lag": [],
                   "used": 0, "leaders": {}, "days": 0}
            for name in FEEDS}
    last_status = {}

    urls, titles = used_urls()

    for day, raw in window:
        for name, st in (raw.get("feed_status") or {}).items():
            last_status[name] = st
            if name in stat and st.get("items"):
                stat[name]["days"] += 1

        for group in cluster(raw.get("items", [])):
            by_feed = {}
            for it in group:
                by_feed.setdefault(it.get("source"), it)
            leader = min(group, key=lambda x: x.get("date") or "")
            for source, it in by_feed.items():
                s = stat.get(source)
                if s is None:
                    continue
                s["items"] += 1
                if len(by_feed) == 1:
                    s["solo"] += 1
                elif it is leader or it.get("date") == leader.get("date"):
                    s["first"] += 1
                else:
                    s["follow"] += 1
                    gap = hours_between(it.get("date"), leader.get("date"))
                    if gap is not None:
                        s["lag"].append(gap)
                    ldr = leader.get("source")
                    s["leaders"][ldr] = s["leaders"].get(ldr, 0) + 1
                if C.norm_url(it.get("link")) in urls:
                    s["used"] += 1
                elif any(C.similarity(it.get("title", ""), t) >= 0.5 for t in titles):
                    s["used"] += 1

    rows, reasons = [], []
    for name in FEEDS:
        s = stat[name]
        st = last_status.get(name, {})
        stale = st.get("stale_hours")
        total = s["items"] or 1
        solo_share = s["solo"] / total
        follow_share = s["follow"] / total
        lag = sorted(s["lag"])
        median_lag = lag[len(lag) // 2] if lag else None
        verdict, why = judge(s, st, solo_share, follow_share, len(window), name)
        if why:
            reasons.append((ORDER[verdict], f"{name}: {why}"))
        chases = max(s["leaders"].items(), key=lambda x: x[1])[0] if s["leaders"] else ""
        rows.append((ORDER[verdict], -s["used"], [
            name[:18],
            st.get("state", "?")[:11],
            f"{stale:.0f}h" if isinstance(stale, (int, float)) else "—",
            str(s["items"]),
            f"{s['items']/max(len(window),1):.1f}",
            str(s["solo"]),
            str(s["first"]),
            str(s["follow"]),
            f"+{median_lag:.0f}h" if median_lag is not None else "—",
            chases[:12],
            str(s["used"]),
            verdict,
        ]))
    rows.sort(key=lambda x: (x[0], x[1]))

    print(C.rule(f"Fonti monitorate — {len(window)} giornate di scarichi"))
    print(C.table([r[2] for r in rows],
                  ["fonte", "stato", "fermo", "art.", "al g.", "escl.",
                   "primo", "insegue", "ritardo", "insegue chi", "usati", "verdetto"]))
    print("""
  escl.    articoli che nessun'altra fonte ha dato in quella giornata
  primo    stessa notizia data anche da altri, ma per primo
  insegue  stessa notizia arrivata dopo qualcun altro
  ritardo  di quanto arriva dopo, mediana
  usati    articoli finiti in edizione (link citato o titolo ripreso)""")

    reasons.sort()
    for _, line in reasons:
        print(f"\n  {line}")

    if len(window) < 7:
        print(f"\nAttenzione: {len(window)} giornate sono poche per decidere. "
              "Il quadro diventa affidabile dopo un paio di settimane.")
    print("\nIl clustering confronta i titoli: fra lingue diverse riconosce i "
          "nomi propri\n(iPhone, AirPods, M6) ma non le riformulazioni libere, "
          "quindi le sovrapposizioni\nfra fonti italiane e inglesi sono "
          "sottostimate.")

    print("\nPANCHINA non vuol dire cancellata: la fonte esce dalla raccolta "
          "quotidiana ma\nresta scritta con il suo motivo e viene riprovata "
          "ogni settimana.\n  python3 pipeline/feedcheck.py --bench \"Nome\" "
          "--reason \"...\"")
    bench_status()
    return 0


# ------------------------------------------------------------------ panchina

def bench_status():
    """Due righe su chi e' in panchina e chi tocca riprovare."""
    seats = SRC.benched()
    if not seats:
        return
    due = SRC.due_for_retest()
    print(C.rule(f"In panchina — {len(seats)}"))
    rows = []
    for name, e in sorted(seats.items()):
        rows.append([name[:20], e.get("since", "—"),
                     (e.get("checked") or "mai"),
                     "oggi" if name in due else "",
                     (e.get("reason") or "")[:44]])
    print(C.table(rows, ["fonte", "da", "riprovata", "tocca", "perche'"]))
    if due:
        print(f"\n  {len(due)} da riprovare: python3 pipeline/feedcheck.py --retest")


def cmd_bench(args):
    name = SRC.resolve(args.bench)
    if not name:
        print(f"Fonte {args.bench!r} non trovata (o ambigua) in "
              "data/sources.json.", file=sys.stderr)
        return 1
    entry = SRC.move(name, "panchina", args.reason or "")
    print(f"{name} in panchina dal {entry['since']}"
          + (f" — {entry['reason']}" if entry.get("reason") else ""))
    print("Esce dalla raccolta di domani. Torna da sola in lista d'attesa "
          f"fra {SRC.RETEST_DAYS} giorni, con --retest.")
    return 0


def cmd_restore(args):
    name = SRC.resolve(args.restore)
    if not name:
        print(f"Fonte {args.restore!r} non trovata.", file=sys.stderr)
        return 1
    SRC.move(name, "attiva", args.reason or "rimessa in campo")
    print(f"{name} di nuovo attiva: rientra nella raccolta di domani.")
    return 0


def cmd_retest(args):
    """Riprova le fonti in panchina e dice se vale la pena riprenderle."""
    seats = SRC.benched()
    if not seats:
        print("Panchina vuota.")
        return 0
    due = set(SRC.due_for_retest()) if not args.all else set(seats)
    todo = [(n, e) for n, e in sorted(seats.items()) if n in due]
    if not todo:
        print(f"Nessuna fonte da riprovare oggi (si riprova ogni "
              f"{SRC.RETEST_DAYS} giorni). Con --all le riprovi tutte.")
        return 0

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=args.hours)

    ours = []
    for _, raw in load_window(max(2, int(args.hours / 24) + 1)):
        ours.extend(raw.get("items", []))
    our_titles = [i.get("title", "") for i in ours]

    print(f"Riprovo {len(todo)} fonti in panchina sulle ultime "
          f"{args.hours:.0f} ore...\n")
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(
            lambda ne: probe((ne[0], ne[1]["url"], ne[1].get("reason", "")), cutoff, now),
            todo))

    rows, verdicts = [], []
    for r in results:
        name = r["name"]
        if not r["ok"]:
            note = f"ancora {r['reason']}"
            rows.append([name[:20], "—", "—", "—", "—", "resta in panchina"])
            verdicts.append((name, note, False))
            SRC.mark_checked(name, note)
            continue
        apple = r["apple"]
        novel = [it for it in apple
                 if not any(C.similarity(it.get("title", ""), t) >= SAME_STORY
                            for t in our_titles)]
        alive = len(r["items"]) > 0
        worth = alive and len(novel) >= 2
        note = (f"{len(r['items'])} articoli, {len(apple)} su Apple, "
                f"{len(novel)} che non avevamo")
        rows.append([
            name[:20], str(len(r["items"])), str(len(apple)), str(len(novel)),
            f"{r['stale_h']:.0f}h" if r["stale_h"] is not None else "—",
            "RIPRENDILA" if worth else ("viva ma povera" if alive else "ancora muta"),
        ])
        verdicts.append((name, note, worth))
        SRC.mark_checked(name, note)

    print(C.table(rows, ["fonte", "art.", "Apple", "nuovi", "ultimo", "verdetto"]))
    good = [n for n, _, w in verdicts if w]
    if good:
        print("\nQueste hanno ricominciato a portare roba nostra non gia' vista:")
        for n in good:
            print(f"  python3 pipeline/feedcheck.py --restore \"{n}\"")
    else:
        print(f"\nNessuna da riprendere. Si riprova fra {SRC.RETEST_DAYS} giorni.")
    return 0


ORDER = {"PANCHINA": 0, "SORVEGLIA": 1, "TIENI": 2}


def judge(s, st, solo_share, follow_share, days, name=""):
    """Il verdetto e la ragione che lo motiva."""
    state = st.get("state")
    stale = st.get("stale_hours")
    quiet = name in QUIET
    # I gironi a bassa frequenza: un laboratorio annuncia quando ha finito, un
    # canale pubblica quando il video e' montato. Il metro delle quotidiane
    # qui non vale — misurato con quello, MKBHD sarebbe da panchina ogni
    # settimana in cui non esce niente.
    tier = TIERS.get(name)
    rado = tier in ("ai", "banco")

    if state in ("unreachable", "parse-error"):
        return "PANCHINA", "il feed non risponde o non si legge"
    limite = QUIET_TOLERANCE_H if quiet else (SLOW_HOURS if rado else DEAD_HOURS)
    if isinstance(stale, (int, float)) and stale > limite:
        return "PANCHINA", f"fermo da {stale/24:.0f} giorni"
    if quiet:
        return "TIENI", ("fonte primaria: parla di rado, e quando parla "
                         "chiude i rumor invece di aprirne")
    if s["items"] == 0 and rado:
        return "SORVEGLIA", ("muta in questa finestra, ma e' un girone che "
                             "pubblica a strappi: si guarda il mese, non la settimana")
    if s["items"] == 0:
        return "PANCHINA", "nessun articolo nella finestra"
    if s["used"] == 0 and follow_share > 0.55 and solo_share < 0.2:
        return "PANCHINA", ("insegue gli altri e non entra mai in edizione: "
                            "e' eco, non fonte")
    if s["used"] == 0 and days >= 7:
        return "SORVEGLIA", "pubblica ma non ha mai portato niente in edizione"
    if solo_share > 0.5 or s["used"] > 0:
        return "TIENI", None
    return "SORVEGLIA", "poco esclusivo, poco usato: da riguardare fra una settimana"


# ------------------------------------------------------------------ discover

def probe(entry, cutoff, now):
    name, url, why = entry
    _, _, blob = download(name, url)
    if not blob:
        return {"name": name, "url": url, "why": why, "ok": False,
                "reason": "non risponde"}
    items, newest, state = parse_feed(name, blob, cutoff, now)
    if state != "ok":
        return {"name": name, "url": url, "why": why, "ok": False,
                "reason": state}
    apple = [i for i in items
             if APPLE_WORDS.search((i.get("title", "") + " " + i.get("summary", "")))]
    return {
        "name": name, "url": url, "why": why, "ok": True,
        "items": items, "apple": apple, "newest": newest,
        "stale_h": round((now - newest).total_seconds() / 3600, 1) if newest else None,
    }


def cmd_discover(args):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=args.hours)

    # cosa hanno gia' dato le nostre fonti nella stessa finestra
    ours = []
    for _, raw in load_window(max(2, int(args.hours / 24) + 1)):
        ours.extend(raw.get("items", []))
    our_urls = {C.norm_url(i.get("link")) for i in ours}
    our_titles = [i.get("title", "") for i in ours]

    print(f"Provo {len(CANDIDATES)} fonti candidate sulle ultime "
          f"{args.hours:.0f} ore...\n")
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda e: probe(e, cutoff, now), CANDIDATES))

    rows, dead = [], []
    for r in results:
        if not r["ok"]:
            dead.append((r["name"], r["reason"]))
            continue
        apple = r["apple"]
        novel = []
        for it in apple:
            if C.norm_url(it.get("link")) in our_urls:
                continue
            if any(C.similarity(it.get("title", ""), t) >= SAME_STORY for t in our_titles):
                continue
            novel.append(it)
        share = len(apple) / len(r["items"]) if r["items"] else 0
        novelty = len(novel) / len(apple) if apple else 0
        # un buon candidato porta cose di Apple, nuove, e ne porta abbastanza
        score = len(novel) * share * (0.5 + 0.5 * novelty)
        rows.append((score, r, [
            r["name"][:22],
            str(len(r["items"])),
            str(len(apple)),
            f"{share:.0%}",
            str(len(novel)),
            f"{novelty:.0%}",
            f"{r['stale_h']:.0f}h" if r["stale_h"] is not None else "—",
            f"{score:.1f}",
        ]))
    rows.sort(key=lambda x: -x[0])

    print(C.rule("Candidate raggiungibili"))
    print(C.table([r[2] for r in rows],
                  ["candidata", "art.", "Apple", "quota", "nuovi", "novita'",
                   "ultimo", "punti"]))
    print("""
  Apple    articoli nel perimetro Apple
  quota    quanta parte del feed e' nel perimetro: sotto il 20% e' un feed
           generalista, va letto solo per il contorno
  nuovi    articoli Apple che le nostre fonti non hanno dato
  novita'  quanta parte dei suoi articoli Apple e' roba nostra gia' vista

  Il punteggio premia il volume, quindi va letto con la testa: una fonte
  primaria che pubblica due comunicati a settimana finisce in fondo pur
  valendo piu' di un sito che ne sforna venti al giorno. Guarda la colonna
  "quota" insieme al punteggio: quota alta e volume basso vuol dire fonte
  autorevole e silenziosa, ed e' esattamente quello che serve in coda.""")

    print(C.rule("Cosa aggiungerebbero"))
    for _, r, cells in rows[:10]:
        print(f"\n  {r['name']}\n    {r['why']}\n    {r['url']}")

    if dead:
        print(C.rule("Non raggiungibili"))
        for name, reason in dead:
            print(f"  {name}: {reason}")
        print("\n  Un feed che non risponde puo' essere protetto da Cloudflare "
              "o richiedere\n  un percorso diverso: vale la pena riprovare a "
              "mano prima di scartarlo.")

    print("\nDa qui si decide a mano: aggiungi le prescelte a SEED in "
          "pipeline/sources.py,\npoi lascia passare una settimana e rilancia "
          "feedcheck.py per vedere se\nreggono alla prova dei numeri.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("--days", type=int, default=30,
                    help="giornate di scarichi da analizzare (default 30)")
    ap.add_argument("--discover", action="store_true",
                    help="prova le fonti candidate invece di analizzare le attuali")
    ap.add_argument("--hours", type=float, default=168,
                    help="finestra per --discover e --retest (default una settimana)")
    ap.add_argument("--bench", metavar="FONTE",
                    help="manda una fonte in panchina (non la cancella)")
    ap.add_argument("--restore", metavar="FONTE",
                    help="rimette in campo una fonte in panchina")
    ap.add_argument("--retest", action="store_true",
                    help="riprova le fonti in panchina scadute")
    ap.add_argument("--all", action="store_true",
                    help="con --retest: riprovale tutte, non solo quelle scadute")
    ap.add_argument("--reason", help="il perche', da scrivere nel registro")
    args = ap.parse_args()

    if args.bench:
        return cmd_bench(args)
    if args.restore:
        return cmd_restore(args)
    if args.retest:
        return cmd_retest(args)
    return cmd_discover(args) if args.discover else cmd_report(args)


if __name__ == "__main__":
    sys.exit(main())
