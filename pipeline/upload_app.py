#!/usr/bin/env python3
"""
Pubblica app/index.html su Supabase Storage e stampa l'indirizzo pubblico.

    python3 pipeline/upload_app.py

VIA VECCHIA, non piu' in uso. L'app sta su GitHub Pages e si pubblica con
pipeline/publish_site.py. Storage serve gli HTML come text/plain alle
navigazioni da browser (misura anti-phishing, non aggirabile), quindi il file
caricato qui non e' una pagina: lo rileggeva la Edge Function "app", anche lei
in disuso. Resta perche' costa niente tenerlo e perche' se un giorno Supabase
cambiasse politica la strada e' gia' scritta.

Serve la service key, letta da .env.local o da SUPABASE_SERVICE_KEY.
"""

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app", "index.html")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from push import load_config, service_key  # noqa: E402


def main():
    argparse.ArgumentParser(description=__doc__.strip().split("\n")[0]).parse_args()

    if not os.path.exists(APP):
        sys.exit("app/index.html non trovato — lancia prima pipeline/build.py")

    with open(APP, encoding="utf-8") as fh:
        body = fh.read()
    mode = re.search(r'const MODE\s*=\s*"([a-z]+)"', body)
    if not mode or mode.group(1) != "cloud":
        sys.exit(f"app/index.html è in modalità {mode.group(1) if mode else 'ignota'}, non cloud — "
                 "controlla supabase/config.json e rilancia pipeline/build.py")

    cfg, key = load_config(), service_key()
    bucket = cfg.get("bucket", "app")

    out = subprocess.run(
        ["curl", "-sS", "-w", "\n%{http_code}", "-X", "POST",
         f"{cfg['url']}/storage/v1/object/{bucket}/index.html",
         # Storage vuole entrambe le intestazioni: senza apikey prova a leggere
         # il Bearer come JWT classico e le chiavi sb_secret_ non lo sono
         "-H", f"apikey: {key}",
         "-H", f"Authorization: Bearer {key}",
         "-H", "Content-Type: text/html; charset=utf-8",
         "-H", "Cache-Control: max-age=300",
         "-H", "x-upsert: true",
         "--data-binary", f"@{APP}"],
        capture_output=True,
    )
    text = out.stdout.decode("utf-8", "replace").strip()
    status = text.rsplit("\n", 1)[-1]
    body = text.rsplit("\n", 1)[0] if "\n" in text else ""

    if not status.startswith("2"):
        print(f"Caricamento fallito (HTTP {status}): {body[:300]}", file=sys.stderr)
        if status == "400" and "Bucket not found" in body:
            print(f"Il bucket '{bucket}' non esiste — vedi SETUP.md, passo 4.", file=sys.stderr)
        return 1

    # Storage è solo il magazzino: la pagina la serve la Edge Function "app",
    # perché i file pubblici di Storage escono sempre come text/plain
    url = cfg.get("app_url") or f"{cfg['url']}/functions/v1/app"
    with open(os.path.join(ROOT, ".app-url"), "w", encoding="utf-8") as fh:
        fh.write(url + "\n")
    size = os.path.getsize(APP) // 1024
    print(f"App caricata su Storage ({size} KB)")
    print("La funzione la rilegge entro un minuto (cache interna).")
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
