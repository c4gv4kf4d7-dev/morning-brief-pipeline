#!/usr/bin/env python3
"""
Carica le edizioni su Supabase.

    python3 pipeline/push.py              solo l'edizione di oggi
    python3 pipeline/push.py --all        tutto l'archivio
    python3 pipeline/push.py 2026-08-08   una data precisa

Serve la service key, letta da .env.local o dalla variabile d'ambiente
SUPABASE_SERVICE_KEY. La chiave non viene mai stampata.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIEFS_DIR = os.path.join(ROOT, "data", "briefs")


def load_config():
    path = os.path.join(ROOT, "supabase", "config.json")
    if not os.path.exists(path):
        sys.exit("supabase/config.json non trovato — vedi SETUP.md, passo 5.")
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    if "xxxx" in cfg.get("url", ""):
        sys.exit("supabase/config.json contiene ancora i valori di esempio.")
    # il pannello Supabase a volte mostra l'endpoint REST completo:
    # teniamo solo schema e host, il resto lo compongono gli script
    m = re.match(r"(https://[^/]+)", cfg["url"].strip())
    if not m:
        sys.exit(f"URL non valido in supabase/config.json: {cfg['url']!r}")
    cfg["url"] = m.group(1)
    return cfg


def service_key():
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    if key:
        return key
    env = os.path.join(ROOT, ".env.local")
    if os.path.exists(env):
        with open(env, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("SUPABASE_SERVICE_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("Service key mancante — vedi SETUP.md, passo 6.")


def post(cfg, key, rows):
    body = json.dumps(rows, ensure_ascii=False)
    out = subprocess.run(
        ["curl", "-sS", "-w", "\n%{http_code}", "-X", "POST",
         f"{cfg['url']}/rest/v1/brief_editions?on_conflict=date",
         "-H", f"apikey: {key}",
         "-H", f"Authorization: Bearer {key}",
         "-H", "Content-Type: application/json",
         "-H", "Prefer: resolution=merge-duplicates",
         "--data-binary", "@-"],
        input=body.encode("utf-8"), capture_output=True,
    )
    if out.returncode != 0:
        # senza rete curl esce male e non scrive niente: prima si leggeva uno
        # stato vuoto e il messaggio diceva "HTTP " senza numero
        return "000", (out.stderr.decode("utf-8", "replace").strip()
                       or f"curl uscito con codice {out.returncode}")
    text = out.stdout.decode("utf-8", "replace").strip()
    status = text.rsplit("\n", 1)[-1]
    payload = text.rsplit("\n", 1)[0] if "\n" in text else ""
    return status, payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", help="data da caricare (YYYY-MM-DD)")
    ap.add_argument("--all", action="store_true", help="carica tutto l'archivio")
    args = ap.parse_args()

    if args.all:
        paths = sorted(glob.glob(os.path.join(BRIEFS_DIR, "*.json")))
        if not paths:
            sys.exit("Nessuna edizione in data/briefs/: non c'e' niente da caricare.")
    else:
        day = args.date or datetime.now().strftime("%Y-%m-%d")
        paths = [os.path.join(BRIEFS_DIR, f"{day}.json")]
        if not os.path.exists(paths[0]):
            sys.exit(f"Nessun brief per il {day}. Scrivilo prima in data/briefs/.")

    cfg, key = load_config(), service_key()

    rows = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        rows.append({"date": payload["date"], "payload": payload})

    status, err = post(cfg, key, rows)
    if status.startswith("2"):
        print(f"Caricate {len(rows)} edizioni su Supabase ({rows[-1]['date']} la più recente)")
        return 0
    dove = "rete non raggiungibile" if status == "000" else f"HTTP {status}"
    print(f"Caricamento fallito ({dove}): {err[:300]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
