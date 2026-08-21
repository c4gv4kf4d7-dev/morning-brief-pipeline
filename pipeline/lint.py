#!/usr/bin/env python3
"""
Il collaudo dell'edizione.

Le regole editoriali stanno scritte in CLAUDE.md, e valgono finche' qualcuno
le fa rispettare. Dopo cento edizioni lo standard scivola senza che nessuno se
ne accorga: le descrizioni si accorciano, le virgolette perdono l'attribuzione,
il rank smette di seguire l'importanza e comincia a seguire l'ordine in cui
sono state scritte. Questo script legge un'edizione e la mette alla prova
contro le sue stesse regole.

Due livelli:

  ERRORE   l'edizione e' rotta o contraddice una regola non negoziabile.
           Va sistemata prima di pubblicare.
  AVVISO   qualcosa e' fuori misura. Spesso e' voluto, ma va guardato.

    python3 pipeline/lint.py                 l'edizione di oggi
    python3 pipeline/lint.py 2026-08-08      una data precisa
    python3 pipeline/lint.py --all           tutto l'archivio
    python3 pipeline/lint.py --links         controlla anche che i link aprano

Esce con 1 se trova errori, cosi' si puo' mettere in coda a un comando.
"""

import argparse
import concurrent.futures as cf
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common as C

TAGS = {"CONFERMATO", "RUMOR", "DATI", "ANALISI", "OPINIONE",
        "CONTORNO", "CONTESTO", "SERVIZIO"}
RELIABILITY = {"alta", "media", "bassa"}

# le misure dichiarate in CLAUDE.md
NEWS_MIN, NEWS_MAX = 15, 20
RADAR_MIN, RADAR_MAX = 6, 6
SOCIAL_MAX = 5
BANCO_MIN, BANCO_MAX = 3, 5
BANCO_KINDS = {"recensione", "video", "confronto", "curiosità", "guida"}
RECAP_MAX = 3
# "Se te lo fossi perso" guarda indietro: sotto i due giorni e' la rassegna di
# ieri, oltre il mese non se l'e' perso, l'ha dimenticato
RECAP_MIN_AGE, RECAP_MAX_AGE = 2, 30
SINTESI_MAX = 200
DESCR_MIN, DESCR_MAX = 200, 950
INTRO_MIN, INTRO_MAX = 180, 700

# due titoli oltre questa somiglianza raccontano la stessa cosa
DUP = 0.45

# "Tono: giornalistico, asciutto. Niente hype, niente entusiasmo da creator."
HYPE = re.compile(
    r"\b(incredibil\w+|clamoros\w+|pazzesc\w+|rivoluzionar\w+|stupefacent\w+|"
    r"spettacolar\w+|da urlo|boom|imperdibil\w+|sensazional\w+|epic\w+|"
    r"assurd\w+|mostruos\w+|bomba)\b", re.I)

# una descrizione senza cifre e senza virgolette non porta niente di concreto
NUMBER = re.compile(r"\d")
QUOTE = re.compile(r"[\"«»“”]")
# chi l'ha detto: serve accanto a una citazione
ATTRIB = re.compile(
    r"\b(second\w+|scriv\w+|dichiar\w+|afferm\w+|spieg\w+|ricord\w+|riferisc\w+|"
    r"sostien\w+|ha detto|racconta|nota|osserva|conferma)\b", re.I)


class Report:
    def __init__(self, day):
        self.day, self.errors, self.warnings = day, [], []

    def error(self, where, msg):
        self.errors.append((where, msg))

    def warn(self, where, msg):
        self.warnings.append((where, msg))

    def show(self):
        print(C.rule(f"Edizione del {self.day}"))
        if not self.errors and not self.warnings:
            print("Nessun rilievo.")
            return
        for where, msg in self.errors:
            print(f"  ERRORE  {where}: {msg}")
        for where, msg in self.warnings:
            print(f"  avviso  {where}: {msg}")
        print(f"\n{len(self.errors)} errori, {len(self.warnings)} avvisi.")


# ---------------------------------------------------------------- struttura

def check_shape(brief, r):
    for field in ("date", "title", "top3", "intro", "news"):
        if not brief.get(field):
            r.error("edizione", f"manca il campo {field}")

    top3 = brief.get("top3") or []
    if len(top3) != 3:
        r.error("top3", f"{len(top3)} voci invece di 3")
    for i, t in enumerate(top3):
        if len(t) > 190:
            r.warn(f"top3[{i+1}]", f"{len(t)} caratteri: e' un titolo, non un riassunto")

    intro = brief.get("intro") or ""
    if intro and not (INTRO_MIN <= len(intro) <= INTRO_MAX):
        r.warn("intro", f"{len(intro)} caratteri, attese 3-4 righe "
                        f"({INTRO_MIN}-{INTRO_MAX})")

    news = brief.get("news") or []
    if not (NEWS_MIN <= len(news) <= NEWS_MAX):
        r.warn("news", f"{len(news)} notizie, la misura dichiarata e' "
                       f"{NEWS_MIN}-{NEWS_MAX}")

    radar = brief.get("radar") or []
    if radar and not (RADAR_MIN <= len(radar) <= RADAR_MAX):
        r.warn("radar", f"{len(radar)} voci, attese {RADAR_MIN}-{RADAR_MAX}")
    # senza id la voce non e' votabile, senza topic il radar non impara
    for v in radar:
        titolo = (v.get("title") or "")[:46]
        if not v.get("id"):
            r.warn("radar", f"voce senza id, non votabile: {titolo}")
        if not v.get("topic"):
            r.warn("radar", f"voce senza topic, il radar non impara: {titolo}")

    banco = brief.get("banco") or []
    if banco and not (BANCO_MIN <= len(banco) <= BANCO_MAX):
        r.warn("banco", f"{len(banco)} voci, attese {BANCO_MIN}-{BANCO_MAX}")
    for v in banco:
        titolo = (v.get("title") or "")[:46]
        if not v.get("id"):
            r.warn("banco", f"voce senza id, non votabile: {titolo}")
        if v.get("kind") not in BANCO_KINDS:
            r.warn("banco", f"genere non ammesso ({v.get('kind')!r}): {titolo}")
        # senza il "perche'" la sezione non esiste: e' una recensione qualsiasi
        if not v.get("perche"):
            r.error("banco", f"voce senza il perche' serve al banco: {titolo}")
        if not v.get("link"):
            r.error("banco", f"voce senza link: {titolo}")

    check_recap(brief, r)

    social = brief.get("social") or []
    if len(social) > SOCIAL_MAX:
        r.warn("social", f"{len(social)} voci, il massimo dichiarato e' {SOCIAL_MAX}")
    for s in social:
        if not s.get("note"):
            r.warn("social", f"voce senza contesto: {(s.get('title') or '')[:50]}")
        if s.get("origine") not in (None, "eco", "nuovo"):
            r.warn("social", f"origine non ammessa: {s.get('origine')!r}")

    if not brief.get("feed_notes"):
        r.warn("feed_notes", "assente: lo stato delle fonti va sempre dichiarato")

    ranks = [n.get("rank") for n in news]
    if sorted(r_ for r_ in ranks if isinstance(r_, int)) != list(range(1, len(news) + 1)):
        r.error("news", "i rank non sono 1..n senza buchi ne' doppioni")

    ids = [n.get("id") for n in news]
    for i in set(ids):
        if i and ids.count(i) > 1:
            r.error("news", f"id ripetuto: {i}")

    if news and not news[0].get("hero"):
        r.warn("news[1]", "la notizia di apertura non ha l'immagine grande "
                          "(lancia images.py)")


_ARCHIVIO = None


def archivio():
    """Titoli e indirizzi gia' usciti, con la loro data: (data, titolo, url).

    Si costruisce una volta per corsa. Prima lo faceva check_recap a ogni
    edizione, e con --all su un anno di rassegne erano trecentosessantacinque
    ricostruzioni dello stesso indice."""
    global _ARCHIVIO
    if _ARCHIVIO is None:
        rows = []
        for _, b in C.briefs():
            day = b.get("date", "")
            for n in b.get("news", []):
                rows.append((day, n.get("title", ""),
                             C.norm_url(n["link"]) if n.get("link") else None))
            for sec in ("radar", "banco", "recap"):
                for v in b.get(sec) or []:
                    rows.append((day, v.get("title", ""),
                                 C.norm_url(v["link"]) if v.get("link") else None))
        _ARCHIVIO = rows
    return _ARCHIVIO


def check_recap(brief, r):
    """"Se te lo fossi perso" ha una sola regola vera: che tu non l'abbia
    gia' avuto. Una voce gia' passata in edizione svuota la sezione del suo
    senso, quindi si confronta con tutto l'archivio prima di lasciarla."""
    recap = brief.get("recap") or []
    if not recap:
        return
    if len(recap) > RECAP_MAX:
        r.warn("recap", f"{len(recap)} voci, il massimo dichiarato e' {RECAP_MAX}")

    oggi = brief.get("date") or C.today()
    vecchi = [t for day, t, _ in archivio() if day != oggi and t]
    urls = {u for day, _, u in archivio() if day != oggi and u}

    for v in recap:
        titolo = (v.get("title") or "")[:46]
        if not v.get("id"):
            r.warn("recap", f"voce senza id, non votabile: {titolo}")
        if not v.get("signal"):
            r.error("recap", f"voce senza la misura di quanto ha girato: {titolo}")
        when = v.get("when")
        if not when:
            r.error("recap", f"voce senza data d'origine: {titolo}")
        else:
            eta = C.days_between(oggi, when)
            if eta is None:
                r.error("recap", f"data d'origine illeggibile ({when!r}): {titolo}")
            elif eta < RECAP_MIN_AGE:
                r.error("recap", f"{titolo}: ha {eta} giorni, non e' un ripescaggio "
                                 f"ma la rassegna di ieri")
            elif eta > RECAP_MAX_AGE:
                r.warn("recap", f"{titolo}: ha {eta} giorni, oltre il mese non se "
                                "l'e' perso, l'ha dimenticato")
        if v.get("link") and C.norm_url(v["link"]) in urls:
            r.error("recap", f"gia' pubblicata in una vecchia edizione: {titolo}")
            continue
        for t in vecchi:
            if C.similarity(v.get("title", ""), t) >= DUP:
                r.error("recap", f"{titolo}: gliel'abbiamo gia' data — «{t[:50]}»")
                break


# ---------------------------------------------------------------- notizie

def check_story(n, r):
    where = f"news/{n.get('id') or '?'}"

    for field in ("id", "title", "sintesi", "descrizione", "link"):
        if not n.get(field):
            r.error(where, f"manca {field}")

    tag = n.get("tag")
    if tag and tag not in TAGS:
        r.error(where, f"tag non ammesso: {tag!r}")
    rel = n.get("reliability")
    if rel and rel not in RELIABILITY:
        r.error(where, f"reliability non ammessa: {rel!r}")
    # la nota sulla fonte serve dove il sourcing e' in gioco: su un annuncio di
    # servizio o su un pezzo di contesto sarebbe burocrazia
    if rel and not n.get("reliability_note") and tag in ("RUMOR", "DATI", "CONFERMATO"):
        r.warn(where, "affidabilita' dichiarata senza spiegare perche'")

    link = n.get("link") or ""
    if link and not link.startswith(("http://", "https://")):
        r.error(where, f"link non valido: {link[:50]}")

    sintesi = n.get("sintesi") or ""
    if len(sintesi) > SINTESI_MAX:
        r.warn(where, f"sintesi di {len(sintesi)} caratteri: dev'essere una riga")

    d = n.get("descrizione") or ""
    if d and len(d) < DESCR_MIN:
        r.warn(where, f"descrizione di {len(d)} caratteri: troppo poco per "
                      "dare contesto")
    if len(d) > DESCR_MAX:
        r.warn(where, f"descrizione di {len(d)} caratteri: attese 3-4 righe")
    if d and not NUMBER.search(d) and not QUOTE.search(d):
        r.warn(where, "descrizione senza un solo dato concreto ne' una citazione")
    if QUOTE.search(d) and not ATTRIB.search(d):
        r.warn(where, "c'e' una citazione ma non si capisce chi l'ha detta")

    hype = HYPE.findall(" ".join([n.get("title", ""), sintesi, d]))
    if hype:
        r.warn(where, f"tono da creator: {', '.join(sorted(set(h.lower() for h in hype)))}")

    if tag == "RUMOR" and not n.get("claim"):
        r.warn(where, "rumor senza previsione verificabile (campo claim)")

    for f in n.get("facts") or []:
        if not f.get("key") or f.get("value") is None:
            r.error(where, "lettura numerica incompleta (servono key e value)")


def check_duplicates(news, r):
    for i in range(len(news)):
        for j in range(i + 1, len(news)):
            s = C.similarity(news[i].get("title", ""), news[j].get("title", ""))
            if s >= DUP:
                r.warn("news", f"{news[i].get('id')} e {news[j].get('id')} "
                               f"sembrano la stessa notizia ({s:.0%})")


def check_ranking(news, r):
    """Il rank dovrebbe seguire l'importanza, non l'ordine di scrittura.

    L'unico segnale automatico onesto e' quante testate hanno coperto il fatto,
    ed e' un segnale debole: una pagina di offerte ha due fonti e sta giusta in
    fondo. Quindi il controllo e' volutamente timido — salta le categorie che
    per regola vanno in coda (contorno, contesto, servizio) e parla solo dei
    casi grossi: tre fonti o piu' relegate nella meta' bassa."""
    tail = {"CONTORNO", "CONTESTO", "SERVIZIO"}
    core = [(i, n) for i, n in enumerate(news) if n.get("tag") not in tail]
    if len(core) < 6:
        return
    half = len(news) / 2
    top_thin = [n for i, n in core if i < half and len(n.get("sources") or []) <= 1]
    if not top_thin:
        return
    for i, n in core:
        if i >= half and len(n.get("sources") or []) >= 3:
            r.warn("news", f"{n.get('id')} ha {len(n['sources'])} fonti ed e' al "
                           f"posto {i+1}, mentre in alto ci sono notizie con una "
                           "fonte sola: l'ordine merita un'occhiata")


# ---------------------------------------------------------------- link

def head(url):
    out = subprocess.run(
        ["curl", "-sIL", "--max-time", "20", "-o", "/dev/null",
         "-w", "%{http_code}", "-A",
         "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120 Safari/537.36", url],
        capture_output=True)
    return url, out.stdout.decode().strip()


def check_links(brief, r):
    urls = []
    for n in brief.get("news", []):
        if n.get("link"):
            urls.append((f"news/{n.get('id')}", n["link"]))
        for extra in n.get("extra_links") or []:
            if extra.get("url"):
                urls.append((f"news/{n.get('id')}", extra["url"]))
    for sec in ("radar", "banco", "recap", "social"):
        for s in brief.get(sec) or []:
            if s.get("link"):
                urls.append((sec, s["link"]))

    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        results = dict(pool.map(lambda u: head(u[1]), urls))
    for where, url in urls:
        code = results.get(url, "000")
        if code in ("000", ""):
            r.warn(where, f"link che non risponde: {url[:70]}")
        elif not code.startswith(("2", "3")):
            r.warn(where, f"link con HTTP {code}: {url[:70]}")


# ---------------------------------------------------------------- corsa

def lint(brief, with_links):
    r = Report(brief.get("date", "?"))
    news = brief.get("news") or []
    check_shape(brief, r)
    for n in news:
        check_story(n, r)
    check_duplicates(news, r)
    check_ranking(news, r)
    if with_links:
        check_links(brief, r)
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("date", nargs="?", help="data da collaudare (YYYY-MM-DD)")
    ap.add_argument("--all", action="store_true", help="tutto l'archivio")
    ap.add_argument("--links", action="store_true",
                    help="controlla che i link aprano davvero (va in rete)")
    args = ap.parse_args()

    if args.all:
        briefs = [b for _, b in C.briefs(reverse=True)]
    else:
        day = args.date or C.today()
        path = os.path.join(C.BRIEFS_DIR, f"{day}.json")
        if not os.path.exists(path):
            print(f"Nessuna edizione per il {day}.", file=sys.stderr)
            return 1
        briefs = [C.load_json(path)]

    errors = 0
    for brief in briefs:
        r = lint(brief, args.links)
        r.show()
        errors += len(r.errors)

    if len(briefs) > 1:
        print(f"\n{len(briefs)} edizioni collaudate, {errors} errori in tutto.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
