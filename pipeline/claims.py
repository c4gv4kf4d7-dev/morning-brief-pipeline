#!/usr/bin/env python3
"""
Le pagelle: tenere il conto di chi ci prende.

Ogni rumor contiene una previsione verificabile. Se la scriviamo per esteso,
prima o poi si puo' dire se era giusta. La previsione sta dentro la notizia:

    "claim": {
      "id": "m6-pro-autunno",
      "text": "In autunno arriva un MacBook Pro con chip M6 Pro",
      "source": "9to5Mac",
      "horizon": "2026-11-30"
    }

La verifica sta dentro la notizia che la chiude, in un'edizione successiva:

    "resolves": [
      {"claim": "m6-pro-autunno", "verdict": "smentito",
       "note": "Gurman: M6 Pro e Max cancellati, si passa all'M7."}
    ]

Nessuna tabella in piu': tutto vive nelle edizioni, quindi arriva
all'app con push.py e resta dentro la copia Artifact.

Verdetti ammessi: confermato, parziale, smentito. Una previsione il cui
orizzonte passa senza che nessuno l'abbia chiusa conta come scaduta, e nelle
pagelle pesa come un errore: prevedere una cosa che non succede e' sbagliare.

Comandi:
    python3 pipeline/claims.py open                    le previsioni aperte
    python3 pipeline/claims.py open --due 21           quelle in scadenza
    python3 pipeline/claims.py score                   le pagelle per fonte
    python3 pipeline/claims.py show <id>               una previsione
    python3 pipeline/claims.py resolve <id> <verdetto> --story <id-notizia> \\
                                       [--in DATA] [--note "..."]
    python3 pipeline/claims.py check                   controlli di integrita'
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common as C

VERDICTS = ("confermato", "parziale", "smentito")
# quanto vale ogni esito nel calcolo del tasso di successo
WEIGHT = {"confermato": 1.0, "parziale": 0.5, "smentito": 0.0, "scaduto": 0.0}

# varianti dello stesso nome che devono finire nella stessa riga di pagella
ALIASES = {
    "gurman": "Mark Gurman (Bloomberg)",
    "mark gurman": "Mark Gurman (Bloomberg)",
    "bloomberg": "Mark Gurman (Bloomberg)",
    "ming-chi kuo": "Ming-Chi Kuo",
    "kuo": "Ming-Chi Kuo",
    "ross young": "Ross Young",
    "counterpoint": "Counterpoint Research",
    "idc": "IDC",
    "digitimes": "Digitimes",
    "etnews": "ETNews",
}


def canon(source):
    """Riporta le varianti di un nome alla stessa riga di pagella.

    La parentesi finale va tolta se e' una precisazione ("9to5Mac (stime di
    analisti)") e tenuta se e' l'editore ("Mark Gurman (Bloomberg)"): la
    maiuscola iniziale distingue i due casi."""
    s = " ".join(str(source or "ignota").split())
    m = re.match(r"^(.*?)\s*\(([^)]*)\)$", s)
    if m and m.group(2)[:1].islower():
        s = m.group(1).strip()
    return ALIASES.get(s.lower(), s)


def collect():
    """Legge tutto l'archivio e ritorna (previsioni, verifiche).

    previsioni: id -> dict con testo, fonte, orizzonte, edizione e notizia
    verifiche:  id -> dict con verdetto, nota, edizione e notizia che chiude
    """
    claims, resolutions = {}, {}
    for day, brief, news in C.stories():
        c = news.get("claim")
        if c and c.get("id"):
            claims[c["id"]] = {
                "id": c["id"],
                "text": c.get("text", ""),
                "source": canon(c.get("source") or (news.get("sources") or ["ignota"])[0]),
                "horizon": c.get("horizon", ""),
                "opened": day,
                "story": news.get("id"),
                "title": news.get("title", ""),
                "reliability": news.get("reliability", ""),
            }
        for r in news.get("resolves") or []:
            if not r.get("claim"):
                continue
            resolutions[r["claim"]] = {
                "verdict": r.get("verdict", ""),
                "note": r.get("note", ""),
                "day": day,
                "story": news.get("id"),
                "title": news.get("title", ""),
            }
    return claims, resolutions


def status_of(claim, resolutions, today=None):
    """Stato attuale di una previsione: un verdetto, 'scaduto' o 'aperto'."""
    today = today or C.today()
    res = resolutions.get(claim["id"])
    if res and res.get("verdict") in VERDICTS:
        return res["verdict"], res
    horizon = claim.get("horizon") or ""
    if horizon and horizon[:10] < today:
        return "scaduto", None
    return "aperto", None


# ---------------------------------------------------------------- open

def cmd_open(args):
    claims, resolutions = collect()
    today = C.today()
    rows = []
    for claim in claims.values():
        state, _ = status_of(claim, resolutions, today)
        if state not in ("aperto", "scaduto"):
            continue
        left = C.days_between(claim.get("horizon", ""), today)
        if args.due is not None and (left is None or left > args.due):
            continue
        rows.append((claim.get("horizon") or "9999", [
            claim["id"],
            claim["source"][:28],
            claim.get("horizon") or "—",
            "SCADUTA" if state == "scaduto" else (f"{left}g" if left is not None else "—"),
            claim["text"][:64],
        ]))
    rows.sort(key=lambda x: x[0])
    if not rows:
        print("Nessuna previsione aperta." if args.due is None
              else f"Nessuna previsione in scadenza entro {args.due} giorni.")
        return 0
    print(C.table([r[1] for r in rows],
                  ["previsione", "fonte", "orizzonte", "restano", "cosa dice"]))
    print(f"\n{len(rows)} previsioni da tenere d'occhio. Se una notizia di oggi "
          "ne chiude una, aggiungi il campo \"resolves\" a quella notizia\n"
          "(o usa: claims.py resolve <id> <verdetto> --story <id-notizia>).")
    return 0


# ---------------------------------------------------------------- score

def cmd_score(args):
    claims, resolutions = collect()
    today = C.today()
    by_source = {}
    for claim in claims.values():
        state, _ = status_of(claim, resolutions, today)
        agg = by_source.setdefault(claim["source"], {
            "confermato": 0, "parziale": 0, "smentito": 0, "scaduto": 0, "aperto": 0,
            "lead": [],
        })
        agg[state] += 1
        if state in VERDICTS:
            gap = C.days_between(resolutions[claim["id"]]["day"], claim["opened"])
            if gap is not None:
                agg["lead"].append(gap)

    rows = []
    for source, a in by_source.items():
        chiuse = a["confermato"] + a["parziale"] + a["smentito"] + a["scaduto"]
        punti = sum(WEIGHT[v] * a[v] for v in WEIGHT)
        tasso = (punti / chiuse) if chiuse else None
        lead = sorted(a["lead"])
        median = lead[len(lead) // 2] if lead else None
        rows.append(((tasso if tasso is not None else -1), chiuse, [
            source[:30],
            f"{tasso:.0%}" if tasso is not None else "—",
            f"{punti:g}/{chiuse}" if chiuse else "—",
            str(a["confermato"]), str(a["parziale"]), str(a["smentito"]),
            str(a["scaduto"]), str(a["aperto"]),
            f"{median}g" if median is not None else "—",
        ]))
    rows.sort(key=lambda x: (-x[0], -x[1]))

    print(C.rule("Pagelle delle fonti"))
    if not rows:
        print("Ancora nessuna previsione registrata.")
        return 0
    print(C.table([r[2] for r in rows],
                  ["fonte", "tasso", "punti", "conf", "parz", "smen",
                   "scad", "apert", "attesa"]))
    chiuse_tot = sum(r[1] for r in rows)
    print(f"\n{len(claims)} previsioni in archivio, {chiuse_tot} gia' verificate.")
    if chiuse_tot < 10:
        print("Campione ancora piccolo: le percentuali diranno qualcosa dopo "
              "qualche decina di verifiche.")
    return 0


# ---------------------------------------------------------------- show

def cmd_show(args):
    claims, resolutions = collect()
    claim = claims.get(args.id)
    if not claim:
        print(f"Previsione {args.id!r} non trovata.", file=sys.stderr)
        return 1
    state, res = status_of(claim, resolutions)
    print(C.rule(claim["id"]))
    print(f"  {claim['text']}")
    print(f"  fonte      {claim['source']}  (affidabilita' dichiarata: {claim['reliability'] or '—'})")
    print(f"  aperta     {claim['opened']}  in \"{claim['title'][:60]}\"")
    print(f"  orizzonte  {claim['horizon'] or '—'}")
    print(f"  stato      {state.upper()}")
    if res:
        print(f"  chiusa     {res['day']}  in \"{res['title'][:60]}\"")
        if res.get("note"):
            print(f"  motivo     {res['note']}")
    return 0


# ---------------------------------------------------------------- resolve

def cmd_resolve(args):
    if args.verdict not in VERDICTS:
        print(f"Verdetto non ammesso: {args.verdict!r}. Usa uno fra "
              f"{', '.join(VERDICTS)}.", file=sys.stderr)
        return 1

    claims, resolutions = collect()
    if args.id not in claims:
        print(f"Previsione {args.id!r} non trovata in archivio.", file=sys.stderr)
        return 1
    if args.id in resolutions and not args.force:
        old = resolutions[args.id]
        print(f"Gia' chiusa il {old['day']} come {old['verdict']!r}. "
              "Usa --force per riscrivere.", file=sys.stderr)
        return 1

    day = getattr(args, "in_date", None) or C.today()
    path = os.path.join(C.BRIEFS_DIR, f"{day}.json")
    if not os.path.exists(path):
        print(f"Nessuna edizione per il {day}.", file=sys.stderr)
        return 1
    brief = C.load_json(path)
    target = next((n for n in brief.get("news", []) if n.get("id") == args.story), None)
    if target is None:
        print(f"Nessuna notizia {args.story!r} nell'edizione del {day}.", file=sys.stderr)
        return 1

    entry = {"claim": args.id, "verdict": args.verdict}
    if args.note:
        entry["note"] = args.note
    target["resolves"] = [r for r in (target.get("resolves") or [])
                          if r.get("claim") != args.id] + [entry]
    C.save_json(path, brief)

    claim = claims[args.id]
    print(f"{args.id}: {args.verdict.upper()}  ({claim['source']}, aperta il {claim['opened']})")
    print(f"  registrato in {day}/{args.story}")
    print(f"  l'edizione del {day} e' cambiata: ricaricala con "
          f"python3 pipeline/push.py {day}")
    return 0


# ---------------------------------------------------------------- check

def cmd_check(args):
    claims, resolutions = collect()
    problems = 0

    # doppioni di id e riferimenti a vuoto
    seen = {}
    for day, brief, news in C.stories():
        c = news.get("claim")
        if c and c.get("id"):
            if c["id"] in seen:
                print(f"  id ripetuto: {c['id']} in {seen[c['id']]} e in "
                      f"{day}/{news.get('id')}")
                problems += 1
            seen[c["id"]] = f"{day}/{news.get('id')}"
            if not c.get("horizon"):
                print(f"  {day}/{news.get('id')}: previsione {c['id']} senza orizzonte")
                problems += 1
            if not c.get("text"):
                print(f"  {day}/{news.get('id')}: previsione {c['id']} senza testo")
                problems += 1
        for r in news.get("resolves") or []:
            if r.get("claim") not in claims:
                print(f"  {day}/{news.get('id')}: verifica di una previsione "
                      f"inesistente ({r.get('claim')})")
                problems += 1
            if r.get("verdict") not in VERDICTS:
                print(f"  {day}/{news.get('id')}: verdetto non ammesso "
                      f"({r.get('verdict')!r})")
                problems += 1
        if news.get("tag") == "RUMOR" and not news.get("claim"):
            print(f"  {day}/{news.get('id')}: rumor senza previsione verificabile")
            problems += 1

    # verifiche che precedono la previsione
    for cid, res in resolutions.items():
        if cid in claims and res["day"] < claims[cid]["opened"]:
            print(f"  {cid}: chiusa il {res['day']}, cioe' prima di essere "
                  f"aperta il {claims[cid]['opened']}")
            problems += 1

    print(f"\n{problems} segnalazioni." if problems else "\nTutto in ordine.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("open", help="le previsioni ancora aperte")
    p.add_argument("--due", type=int, default=None,
                   help="solo quelle in scadenza entro N giorni")
    sub.add_parser("score", help="le pagelle per fonte")
    p = sub.add_parser("show", help="dettaglio di una previsione")
    p.add_argument("id")
    p = sub.add_parser("resolve", help="chiude una previsione")
    p.add_argument("id")
    p.add_argument("verdict", choices=VERDICTS)
    p.add_argument("--story", required=True, help="id della notizia che la chiude")
    p.add_argument("--in", dest="in_date", help="data dell'edizione (default: oggi)")
    p.add_argument("--note", help="perche'")
    p.add_argument("--force", action="store_true")
    sub.add_parser("check", help="controlli di integrita'")

    args = ap.parse_args()
    fn = {"open": cmd_open, "score": cmd_score, "show": cmd_show,
          "resolve": cmd_resolve, "check": cmd_check}
    if not args.cmd:
        return cmd_score(args)
    return fn[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
