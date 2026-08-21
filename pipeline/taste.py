#!/usr/bin/env python3
"""
Il gusto: cosa dicono i pollici, e cosa farne.

L'app registra un voto per notizia e per voce del radar — +1 "ci stava",
-1 "non ci stava". Il voto non giudica l'argomento, giudica la **presenza in
rassegna**: e' il segnale con cui si tara la selezione del mattino dopo.

    python3 pipeline/taste.py            il digest da leggere prima di scrivere
    python3 pipeline/taste.py report     il briefing quindicinale, da discutere
    python3 pipeline/taste.py --offline  senza rete, usa l'ultimo scarico

Due regole che tengono onesto il meccanismo:

* **Il silenzio non e' un no.** Conto solo i voti espressi. Tre apparizioni
  mute di fila mettono un topic in pausa, ma non lo bocciano.
* **Si declassa, non si cancella.** Un pattern confermato sposta la notizia in
  coda o nel radar. Il nucleo Apple non si tocca mai: se Apple prende una
  multa UE quella notizia entra, quanti pollici giu' ci siano stati.
"""

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common                                    # noqa: E402
from push import load_config, service_key        # noqa: E402

ROOT = common.ROOT
TASTE_FILE = os.path.join(ROOT, "data", "taste.json")
TOPICS_FILE = os.path.join(ROOT, "data", "radar_topics.json")

# quanti voti concordi servono prima di dare retta a un pattern
MIN_VOTES = 3
# quota di concordia richiesta: sotto questa soglia il segnale e' rumore
AGREEMENT = 0.75
# ogni quanti giorni il briefing
REPORT_EVERY = 14
# quanto resta in pausa un topic bocciato una volta
PAUSE_DAYS = 42
# quante apparizioni mute prima di liberare lo slot
MUTE_LIMIT = 3
# quante voci ha il radar, quante sono sonde, e quante sono presidio
RADAR_SLOTS, RADAR_PROBES, AI_SLOTS = 6, 2, 1

# Il presidio AI. I laboratori — OpenAI, Anthropic, Google — non sono un tema
# come gli altri: sono il fronte su cui si decide anche quello che Apple fara'.
# Una casella del radar e' loro per statuto, come il nucleo Apple nelle
# notizie: i pollici scelgono *quale* topic AI mostrare, non se mostrarne uno.
# Un topic e' del presidio se in data/radar_topics.json ha "axis": "ai".
AI_AXIS = "ai"


# ------------------------------------------------------------------ lettura

def pull_votes(cfg, key):
    """I voti da Supabase. Ritorna {story: voto}.

    Solo quelli del proprietario: l'app la leggono anche altri, e la service
    key salta l'RLS, quindi senza il filtro i pollici di un lettore ospite
    entrerebbero nella taratura — e sulla stessa notizia ne sovrascriverebbero
    uno dei due. `owner_id` sta in supabase/config.json.
    """
    owner = cfg.get("owner_id")
    if not owner:
        sys.exit("Manca 'owner_id' in supabase/config.json: senza, i voti "
                 "degli altri lettori sporcherebbero la taratura.")
    url = (cfg["url"] + "/rest/v1/brief_marks"
           "?select=story,vote,updated_at&vote=neq.0"
           f"&user_id=eq.{owner}")
    out = subprocess.run(
        ["curl", "-sS", "-w", "\n%{http_code}", url,
         "-H", f"apikey: {key}", "-H", f"Authorization: Bearer {key}"],
        capture_output=True, text=True)
    body, _, code = out.stdout.rpartition("\n")
    if code.strip() != "200":
        if "vote" in body and "column" in body:
            sys.exit("La colonna 'vote' non esiste ancora su brief_marks.\n"
                     "Lancia la riga in supabase/migrazioni.sql dall'editor SQL di Supabase.")
        sys.exit(f"Supabase ha risposto {code.strip()}: {body[:200]}")
    return json.loads(body)


def load_state(path, default):
    if os.path.exists(path):
        return common.load_json(path)
    return default


# --------------------------------------------------------------- incrocio

def index_archive():
    """Ogni chiave votabile con quel che serve per capirla: da che edizione
    viene, che tag e categoria aveva, chi l'ha scritta, che topic era."""
    idx = {}
    for path, b in common.briefs():
        day = b.get("date", os.path.basename(path)[:-5])
        for n in b.get("news", []):
            idx[f"{day}/{n['id']}"] = {
                "kind": "news", "date": day, "title": n.get("title", ""),
                "tag": (n.get("tag") or "").upper(),
                "category": (n.get("category") or "").lower(),
                "sources": n.get("sources") or [],
                "thread": n.get("thread"),
            }
        for r in b.get("radar", []):
            if not r.get("id"):
                continue
            idx[f"{day}/radar:{r['id']}"] = {
                "kind": "radar", "date": day, "title": r.get("title", ""),
                "topic": r.get("topic") or "senza-topic",
                "sources": [r.get("source")] if r.get("source") else [],
            }
        # "Sul banco" impara su due cose: il genere (recensione, video,
        # confronto, curiosita') e chi l'ha fatto. Il topic serve solo a
        # raggruppare, non entra nella macchina a stati del radar.
        for v in b.get("banco", []):
            if not v.get("id"):
                continue
            idx[f"{day}/banco:{v['id']}"] = {
                "kind": "banco", "date": day, "title": v.get("title", ""),
                "genere": (v.get("kind") or "").lower(),
                "sources": [v.get("source")] if v.get("source") else [],
            }
        for m in b.get("recap", []):
            if not m.get("id"):
                continue
            idx[f"{day}/recap:{m['id']}"] = {
                "kind": "recap", "date": day, "title": m.get("title", ""),
                "sources": [m.get("source")] if m.get("source") else [],
            }
    return idx


def radar_appearances():
    """Quante volte un topic e' passato dal radar, e quando l'ultima."""
    seen = defaultdict(lambda: {"n": 0, "last": ""})
    for _, b in common.briefs():
        day = b.get("date", "")
        for r in b.get("radar", []):
            t = r.get("topic")
            if not t:
                continue
            seen[t]["n"] += 1
            seen[t]["last"] = max(seen[t]["last"], day)
    return seen


# ---------------------------------------------------------------- pattern

def tally(votes, idx):
    """Somma i voti lungo gli assi che so usare quando scelgo: categoria,
    tag, fonte, genere da banco e sezione. Un asse conta solo se ha abbastanza
    voti concordi.

    L'asse "sezione" e' quello che tiene onesto l'impianto: se "Se te lo fossi
    perso" prende tre pollici giu' di fila, la sezione non serve e va tolta,
    non difesa."""
    axes = {"categoria": defaultdict(list), "tag": defaultdict(list),
            "fonte": defaultdict(list), "banco": defaultdict(list),
            "sezione": defaultdict(list)}
    unknown = 0
    for row in votes:
        meta = idx.get(row["story"])
        if not meta:
            unknown += 1
            continue
        v = row["vote"]
        if meta["kind"] != "news":
            axes["sezione"][meta["kind"]].append(v)
        if meta["kind"] == "banco":
            if meta.get("genere"):
                axes["banco"][meta["genere"]].append(v)
            for s in meta["sources"]:
                axes["fonte"][s].append(v)
            continue
        if meta["kind"] != "news":
            continue
        if meta.get("category"):
            axes["categoria"][meta["category"]].append(v)
        if meta.get("tag"):
            axes["tag"][meta["tag"]].append(v)
        for s in meta["sources"]:
            axes["fonte"][s].append(v)
    return axes, unknown


def rules_from(axes):
    """Da conteggio a regola scritta. Solo declassamenti: niente sparizioni."""
    out = []
    for axis, buckets in axes.items():
        for value, vs in sorted(buckets.items()):
            n = len(vs)
            if n < MIN_VOTES:
                continue
            down = sum(1 for v in vs if v < 0)
            up = n - down
            if down / n >= AGREEMENT:
                out.append({"asse": axis, "valore": value, "verso": "declassa",
                            "su": up, "giu": down,
                            "nota": f"{axis} «{value}»: {down} pollici giù su {n}"})
            elif up / n >= AGREEMENT:
                out.append({"asse": axis, "valore": value, "verso": "promuovi",
                            "su": up, "giu": down,
                            "nota": f"{axis} «{value}»: {up} pollici su su {n}"})
    return out


def topic_states(votes, idx, topics):
    """La macchina a stati del radar. Il voto piu' recente comanda."""
    seen = radar_appearances()
    tv = defaultdict(list)
    last_up = {}
    for row in votes:
        meta = idx.get(row["story"])
        if not meta or meta["kind"] != "radar":
            continue
        t = meta["topic"]
        tv[t].append(row["vote"])
        if row["vote"] > 0:
            last_up[t] = max(last_up.get(t, ""), meta["date"])

    today = date.today().isoformat()
    for t in set(list(seen) + list(tv) + list(topics)):
        e = topics.setdefault(t, {"state": "nuovo", "since": today,
                                  "up": 0, "down": 0, "seen": 0, "last": ""})
        e["up"] = sum(1 for v in tv[t] if v > 0)
        e["down"] = sum(1 for v in tv[t] if v < 0)
        e["seen"] = seen[t]["n"] if t in seen else 0
        e["last"] = seen[t]["last"] if t in seen else e.get("last", "")

        # Una pausa gia' scontata non si riapre per lo stesso motivo. Il pollice
        # giu' resta scritto per sempre, quindi la regola "1 giu' = in pausa"
        # tornava vera a ogni corsa e rimandava avanti la scadenza di altre sei
        # settimane: il topic non rientrava mai. La pausa si sconta una volta,
        # poi il topic riprova — a bocciarlo davvero e' il secondo pollice giu'.
        scontata = bool(e.get("pausa_finita"))
        # le uscite mute si contano da quando e' rientrato, non dall'inizio,
        # se no rientrava e ripartiva subito in pausa
        mute = e["seen"] - e.get("seen_a_fine_pausa", 0)

        was = e["state"]
        if e["down"] >= 2:
            e["state"] = "archiviato"
        elif e["up"] - e["down"] >= 2:
            e["state"] = "confermato"
        elif e["down"] == 1 and not scontata:
            e["state"] = "in pausa"
        elif mute >= MUTE_LIMIT and not tv[t]:
            e["state"] = "in pausa"
        elif e["seen"] > 0:
            e["state"] = "in prova"

        if e["state"] != was:
            e["since"] = today
            if e["state"] == "in pausa":
                e["paused_until"] = (date.today() + timedelta(days=PAUSE_DAYS)).isoformat()
            else:
                e.pop("paused_until", None)

        # la pausa scade da sola, e lascia il segno di essere stata fatta
        if e["state"] == "in pausa" and e.get("paused_until", "") < today:
            e["state"] = "in prova"
            e["since"] = today
            e["pausa_finita"] = today
            e["seen_a_fine_pausa"] = e["seen"]
            e.pop("paused_until", None)
    return topics, last_up


def ai_pick(topics):
    """Il topic AI di oggi: quello vivo che manca da piu' tempo.

    L'ordine preferisce i confermati, poi gli incerti, poi i sospesi, e solo
    in ultima istanza gli archiviati — perche' la casella non resta mai vuota.
    A parita', vince chi non esce da piu' tempo: cosi' i laboratori ruotano
    invece di darsi il cambio sempre nello stesso ordine."""
    pool = [t for t, e in topics.items() if e.get("axis") == AI_AXIS]
    if not pool:
        return []
    rank = {"confermato": 0, "in prova": 1, "nuovo": 1, "in pausa": 2, "archiviato": 3}
    return sorted(pool, key=lambda t: (rank.get(topics[t]["state"], 1),
                                       topics[t].get("last", ""), t))


def radar_plan(topics, last_up, archive_last_day):
    """Le sei caselle di oggi: una di presidio AI, le confermate a rotazione,
    piu' le sonde. Un pollice su ieri vale un seguito oggi — e' la reazione
    che si sente."""
    follow = [t for t, day in last_up.items() if day == archive_last_day]
    confirmed = sorted([t for t, e in topics.items() if e["state"] == "confermato"],
                       key=lambda t: topics[t].get("last", ""))
    trial = sorted([t for t, e in topics.items() if e["state"] == "in prova"],
                   key=lambda t: topics[t].get("last", ""))
    fresh = sorted([t for t, e in topics.items() if e["state"] == "nuovo"])

    plan, used = [], set()

    def prendi(pool, quanti, etichetta):
        for t in pool:
            if quanti <= 0:
                return
            if t in used:
                continue
            plan.append((t, etichetta(t)))
            used.add(t)
            quanti -= 1

    # la casella di presidio: si assegna per prima, cosi' non se la mangiano
    # le altre regole nelle giornate in cui i topic confermati abbondano
    prendi(ai_pick(topics), AI_SLOTS, lambda t: "presidio AI")

    # le caselle sicure: il seguito di ieri, poi i confermati, e finche' non
    # ce ne sono abbastanza i topic gia' visti ma ancora senza verdetto
    prendi(follow + confirmed + trial, RADAR_SLOTS - RADAR_PROBES - len(plan),
           lambda t: "seguito" if t in follow else
                     ("confermato" if t in confirmed else "in prova"))
    # le sonde: prima i mai provati, poi i vecchi incerti da ritentare
    prendi(fresh + trial, RADAR_PROBES, lambda t: "sonda")
    # se qualcosa e' avanzato (archivio giovane), si riempie con quel che c'e'
    prendi(confirmed + trial + fresh, RADAR_SLOTS - len(plan),
           lambda t: "in prova" if t in trial else "sonda")
    return plan, follow


# ----------------------------------------------------------------- stampe

def digest(state, topics, plan, follow, axes, rules, votes, idx):
    print(common.rule("Il gusto — cosa dicono i pollici"))
    voted = len(votes)
    if not voted:
        print("Ancora nessun voto. Il meccanismo è pronto, serve solo che qualcuno")
        print("cominci a premere i pollici: le prime indicazioni arrivano con una")
        print(f"ventina di voti, le regole vere sopra i {MIN_VOTES} concordi per asse.\n")
    else:
        print(f"{voted} voti espressi.\n")

    if rules:
        print("Indicazioni per la selezione di oggi:")
        for r in rules:
            verso = "declassa (in coda o nel radar)" if r["verso"] == "declassa" else "tieni alto"
            print(f"  · {r['nota']} → {verso}")
        print("  Il nucleo Apple resta fuori da queste regole.\n")
    elif voted:
        print(f"Nessun pattern ancora solido (servono {MIN_VOTES} voti concordi "
              f"su uno stesso asse).\n")

    print(f"Radar di oggi — {RADAR_SLOTS} caselle:")
    for t, why in plan:
        e = topics.get(t, {})
        marker = {"seguito": "↑ seguito di ieri", "confermato": "confermato",
                  "in prova": "in prova", "sonda": "sonda",
                  "presidio AI": "presidio AI (fisso)"}.get(why, why)
        n_out = e.get('seen', 0)
        conto = f"{e.get('up',0)}↑ {e.get('down',0)}↓ · {n_out} uscit" + ("a" if n_out == 1 else "e")
        print(f"  · {t:26} {marker:18} {conto}")
    if follow:
        print(f"  Da riprendere per forza: {', '.join(follow)} (pollice su ieri).")
    print()

    parked = [t for t, e in topics.items() if e["state"] in ("in pausa", "archiviato")]
    if parked:
        print("Fuori rotazione: " + ", ".join(
            f"{t} ({topics[t]['state']})" for t in sorted(parked)))
    print()


def report(state, topics, rules, axes, idx, votes):
    last = state.get("last_report")
    print(common.rule(f"Briefing — dal {last or 'primo giorno'} a oggi"))

    if not rules:
        print("Nessun declassamento attivo: la selezione non si è ancora stretta.\n")
    else:
        print("Cosa sto declassando, e perché:\n")
        for r in rules:
            if r["verso"] != "declassa":
                continue
            print(f"  {r['asse']} «{r['valore']}» — {r['giu']} giù su {r['su'] + r['giu']}")
            def colpita(meta):
                if r["asse"] == "fonte":
                    return r["valore"] in (meta.get("sources") or [])
                campo = "category" if r["asse"] == "categoria" else "tag"
                return meta.get(campo) == r["valore"]

            esempi = [idx[row["story"]]["title"] for row in votes
                      if row["vote"] < 0 and row["story"] in idx
                      and colpita(idx[row["story"]])]
            for t in esempi[:3]:
                print(f"      ↓ {t[:72]}")
        print()

    print("Radar:")
    for stato in ("confermato", "in prova", "in pausa", "archiviato"):
        righe = [t for t, e in topics.items() if e["state"] == stato]
        if righe:
            print(f"  {stato:12} {', '.join(sorted(righe))}")
    print()

    contro = [r for r in rules if 0 < min(r["su"], r["giu"])]
    if contro:
        print("Voti che si contraddicono — da sciogliere a voce:")
        for r in contro:
            print(f"  · {r['asse']} «{r['valore']}»: {r['su']}↑ e {r['giu']}↓")
        print()

    print("Da chiedere: quello che è uscito dalla rassegna ti manca, o va bene così?")
    print()


# ------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", nargs="?", default="digest", choices=["digest", "report"])
    ap.add_argument("--offline", action="store_true",
                    help="non interroga Supabase, usa l'ultimo scarico in data/taste.json")
    args = ap.parse_args()

    state = load_state(TASTE_FILE, {"votes": [], "pulled": None, "last_report": None})
    # al primo giro il contatore del briefing parte da oggi, altrimenti
    # scatterebbe subito e ogni mattina
    primo_giro = state.get("last_report") is None
    if primo_giro:
        state["last_report"] = date.today().isoformat()
    if args.offline:
        votes = state.get("votes", [])
    else:
        cfg = load_config()
        votes = pull_votes(cfg, service_key())
        state["votes"] = votes
        state["pulled"] = datetime.now().isoformat(timespec="seconds")

    idx = index_archive()
    topics = load_state(TOPICS_FILE, {})
    axes, unknown = tally(votes, idx)
    rules = rules_from(axes)
    topics, last_up = topic_states(votes, idx, topics)
    days = [b.get("date", "") for _, b in common.briefs()]
    plan, follow = radar_plan(topics, last_up, max(days) if days else "")

    state["rules"] = rules
    common.save_json(TOPICS_FILE, dict(sorted(topics.items())))

    if args.modo == "report":
        report(state, topics, rules, axes, idx, votes)
        state["last_report"] = date.today().isoformat()
    else:
        digest(state, topics, plan, follow, axes, rules, votes, idx)
        due = state.get("last_report")
        if not primo_giro and (common.days_between(date.today().isoformat(), due) or 0) >= REPORT_EVERY:
            print(f"※ Sono passati {REPORT_EVERY} giorni o più dall'ultimo briefing: "
                  f"lancia `python3 pipeline/taste.py report` e parlane con Mike.")
        if unknown:
            print(f"({unknown} voti su notizie non più in archivio, ignorati.)")

    common.save_json(TASTE_FILE, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
