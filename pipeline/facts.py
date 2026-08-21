#!/usr/bin/env python3
"""
I numeri che si muovono.

Un filo dice che una storia continua. Non dice cosa e' cambiato. Ma nelle
notizie Apple quasi tutto e' un numero che qualcuno rivede: un prezzo stimato,
una data d'uscita, una quota di mercato, la capacita' di una batteria. Presi
uno alla volta sono dettagli; messi in fila raccontano una deriva, e la deriva
e' spesso la notizia vera.

Sulla notizia si scrive cosi':

    "facts": [
      {"key": "iphone18-pro-prezzo", "value": 1299, "kind": "stima",
       "source": "9to5Mac"}
    ]

`value` e' un numero oppure una data ISO. `kind` dice che peso ha:

    dato        e' successo, e' misurato, e' a listino
    stima       qualcuno prevede che sara' cosi'

Etichetta e unita' stanno una volta sola in data/facts.json, il registro delle
metriche, e `facts.py sync` le ricopia dentro ogni lettura. Cosi' l'app non ha
bisogno di scaricare altro, e la copia Artifact — che non puo' fare rete —
mostra le stesse serie.

Comandi:
    python3 pipeline/facts.py sync              allinea registro ed edizioni
    python3 pipeline/facts.py list              tutte le metriche seguite
    python3 pipeline/facts.py show <chiave>     la serie di una metrica
    python3 pipeline/facts.py moving [--days N] quelle che si sono mosse
    python3 pipeline/facts.py check             controlli di integrita'
"""

import argparse
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common as C

FACTS_FILE = os.path.join(C.ROOT, "data", "facts.json")

KINDS = ("dato", "stima")

# Come si scrive un valore, per unita'. Il simbolo sta dove va nella lingua.
UNITS = {
    "USD": ("$", ""), "EUR": ("", " €"), "%": ("", "%"),
    "mAh": ("", " mAh"), "mm": ("", " mm"), "g": ("", " g"),
    "pollici": ("", "\""), "milioni": ("", " mln"), "miliardi": ("", " mld"),
    "": ("", ""),
}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_registry():
    return C.load_json(FACTS_FILE) if os.path.exists(FACTS_FILE) else {}


def save_registry(reg):
    C.save_json(FACTS_FILE, dict(sorted(reg.items())))


def is_date(value):
    return isinstance(value, str) and bool(DATE_RE.match(value))


def fmt(value, unit):
    if is_date(value):
        return value
    pre, post = UNITS.get(unit or "", ("", " " + (unit or "")))
    if isinstance(value, float) and value == int(value):
        value = int(value)
    if isinstance(value, int):
        body = f"{value:,}"
    elif isinstance(value, float):
        body = f"{value:,.2f}".rstrip("0").rstrip(".")
    else:
        return f"{pre}{value}{post}".strip()
    # dai separatori inglesi a quelli italiani: 1,299.5 -> 1.299,5
    body = body.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{pre}{body}{post}".strip()


def readings():
    """Tutte le letture, per metrica, in ordine di data."""
    out = {}
    for day, brief, news in C.stories():
        for f in news.get("facts") or []:
            if not f.get("key"):
                continue
            out.setdefault(f["key"], []).append({
                "date": day,
                "value": f.get("value"),
                "unit": f.get("unit", ""),
                "kind": f.get("kind", "stima"),
                "source": f.get("source") or (news.get("sources") or [""])[0],
                "story": news.get("id"),
                "title": news.get("title", ""),
                "thread": news.get("thread"),
            })
    for key in out:
        out[key].sort(key=lambda r: r["date"])
    return out


def delta(series):
    """Di quanto si e' mosso, dalla prima all'ultima lettura.

    Ritorna (testo, direzione) dove direzione e' 1, -1 o 0."""
    if len(series) < 2:
        return "", 0
    a, b = series[0]["value"], series[-1]["value"]
    if is_date(a) and is_date(b):
        days = C.days_between(b, a)
        if not days:
            return "ferma", 0
        verso = "slittata" if days > 0 else "anticipata"
        return f"{verso} di {abs(days)} giorni", (1 if days > 0 else -1)
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return "", 0
    if a == b:
        return "stabile", 0
    diff = b - a
    if a:
        return f"{'+' if diff > 0 else ''}{diff:g} ({diff / abs(a):+.0%})", (1 if diff > 0 else -1)
    return f"{'+' if diff > 0 else ''}{diff:g}", (1 if diff > 0 else -1)


# ---------------------------------------------------------------- sync

def cmd_sync(args):
    reg = load_registry()
    data = readings()
    added = []

    for key, series in sorted(data.items()):
        if key not in reg:
            first = series[0]
            reg[key] = {
                "label": key.replace("-", " ").capitalize(),
                "unit": first.get("unit", ""),
                "note": "",
                "opened": first["date"],
            }
            added.append(key)
        else:
            reg[key].setdefault("note", "")
            reg[key].setdefault("unit", "")

    touched = []
    for path, brief in C.briefs():
        changed = False
        for news in brief.get("news", []):
            for f in news.get("facts") or []:
                entry = reg.get(f.get("key"))
                if not entry:
                    continue
                # etichetta e unita' vivono nel registro e scendono nelle
                # letture: se rinomini una metrica, l'archivio si adegua
                if f.get("label") != entry["label"]:
                    f["label"] = entry["label"]
                    changed = True
                if entry.get("unit") and f.get("unit") != entry["unit"]:
                    f["unit"] = entry["unit"]
                    changed = True
        if changed:
            C.save_json(path, brief)
            touched.append(brief.get("date"))

    save_registry(reg)
    print(f"Registro: {len(reg)} metriche, {sum(len(s) for s in data.values())} letture.")
    if added:
        print("Nuove metriche (l'etichetta e' provvisoria, correggila in "
              "data/facts.json):")
        for k in added:
            print(f"  {k}  ->  {reg[k]['label']}")
    print(f"Edizioni riscritte: {len(touched)}"
          + (f" ({', '.join(touched)})" if touched else ""))
    return 0


# ---------------------------------------------------------------- list

def cmd_list(args):
    reg, data = load_registry(), readings()
    rows = []
    for key, series in data.items():
        entry = reg.get(key, {})
        d, _ = delta(series)
        rows.append((series[-1]["date"], [
            key[:26],
            entry.get("label", "")[:34],
            str(len(series)),
            fmt(series[-1]["value"], series[-1].get("unit", "")),
            series[-1]["kind"],
            d or "—",
            series[-1]["date"],
        ]))
    rows.sort(key=lambda x: x[0], reverse=True)
    if not rows:
        print("Nessuna metrica ancora. Aggiungi \"facts\" alle notizie e lancia sync.")
        return 0
    print(C.table([r[1] for r in rows],
                  ["chiave", "metrica", "lett.", "ultimo", "tipo", "movimento", "il"]))
    return 0


# ---------------------------------------------------------------- show

def cmd_show(args):
    reg, data = load_registry(), readings()
    series = data.get(args.key)
    if not series:
        print(f"Nessuna lettura per {args.key!r}.", file=sys.stderr)
        return 1
    entry = reg.get(args.key, {})
    print(C.rule(entry.get("label", args.key)))
    if entry.get("note"):
        print(entry["note"] + "\n")

    prev = None
    for r in series:
        line = f"{r['date']}  {fmt(r['value'], r.get('unit','')):>12}  [{r['kind']}]"
        if prev is not None:
            step, _ = delta([prev, r])
            if step and step != "stabile":
                line += f"   {step}"
        print(line)
        print(f"{'':12}  {r['source']} — {r['title'][:60]}")
        prev = r

    d, _ = delta(series)
    if d:
        print(f"\nDalla prima lettura: {d}")
    return 0


# ---------------------------------------------------------------- moving

def cmd_moving(args):
    reg, data = load_registry(), readings()
    today = C.today()
    rows = []
    for key, series in data.items():
        recent = [r for r in series
                  if (C.days_between(today, r["date"]) or 0) <= args.days]
        if len(recent) < 2:
            continue
        d, direction = delta(recent)
        if direction == 0:
            continue
        rows.append((abs(len(recent)), [
            reg.get(key, {}).get("label", key)[:36],
            str(len(recent)),
            fmt(recent[0]["value"], recent[0].get("unit", "")),
            "→",
            fmt(recent[-1]["value"], recent[-1].get("unit", "")),
            d,
        ]))
    if not rows:
        print(f"Niente si e' mosso negli ultimi {args.days} giorni "
              "(serve almeno una metrica con due letture diverse).")
        return 0
    rows.sort(key=lambda x: -x[0])
    print(C.rule(f"Si sono mosse negli ultimi {args.days} giorni"))
    print(C.table([r[1] for r in rows],
                  ["metrica", "lett.", "prima", "", "adesso", "movimento"]))
    print("\nUna stima che cambia tre volte in un mese e' una notizia, non un "
          "dettaglio:\nvale la pena dirlo nell'edizione.")
    return 0


# ---------------------------------------------------------------- check

def cmd_check(args):
    reg, problems = load_registry(), 0
    for day, brief, news in C.stories():
        for f in news.get("facts") or []:
            where = f"{day}/{news.get('id')}"
            if not f.get("key"):
                print(f"  {where}: lettura senza chiave")
                problems += 1
                continue
            if f.get("value") is None:
                print(f"  {where}: {f['key']} senza valore")
                problems += 1
            elif not isinstance(f["value"], (int, float)) and not is_date(f["value"]):
                print(f"  {where}: {f['key']} ha un valore che non e' ne' un "
                      f"numero ne' una data ({f['value']!r})")
                problems += 1
            if f.get("kind") not in KINDS:
                print(f"  {where}: {f['key']} tipo non ammesso ({f.get('kind')!r}), "
                      f"usa uno fra {', '.join(KINDS)}")
                problems += 1
            if f.get("key") not in reg:
                print(f"  {where}: {f['key']} non nel registro "
                      "(risolve: facts.py sync)")
                problems += 1

    # una metrica con letture in unita' diverse non e' una serie
    for key, series in readings().items():
        units = {r.get("unit", "") for r in series}
        if len(units) > 1:
            print(f"  {key}: letture in unita' diverse ({', '.join(sorted(units))})")
            problems += 1
        kinds = {is_date(r["value"]) for r in series}
        if len(kinds) > 1:
            print(f"  {key}: mescola date e numeri")
            problems += 1

    print(f"\n{problems} segnalazioni." if problems else "\nTutto in ordine.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("sync", help="allinea registro ed edizioni")
    sub.add_parser("list", help="tutte le metriche seguite")
    p = sub.add_parser("show", help="la serie di una metrica")
    p.add_argument("key")
    p = sub.add_parser("moving", help="quelle che si sono mosse")
    p.add_argument("--days", type=int, default=60)
    sub.add_parser("check", help="controlli di integrita'")

    args = ap.parse_args()
    fn = {"sync": cmd_sync, "list": cmd_list, "show": cmd_show,
          "moving": cmd_moving, "check": cmd_check}
    if not args.cmd:
        return cmd_list(args)
    return fn[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
