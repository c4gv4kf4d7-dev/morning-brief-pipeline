#!/usr/bin/env python3
"""
Genera le due versioni della web app a partire dall'archivio.

  app/index.html     versione cloud: legge le edizioni da Supabase, richiede
                     l'accesso, sincronizza appunti e diario fra i dispositivi.
                     È il file che va caricato su Supabase Storage.

  app/artifact.html  copia di sola lettura: archivio incorporato nel file,
                     nessun account, nessuna sincronizzazione. È il file che
                     va pubblicato come Artifact.

Uso:
    python3 pipeline/build.py
"""

import argparse
import base64
import glob
import json
import re
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIEFS_DIR = os.path.join(ROOT, "data", "briefs")
TEMPLATE = os.path.join(ROOT, "pipeline", "template.html")
CONFIG = os.path.join(ROOT, "supabase", "config.json")
OUT_CLOUD = os.path.join(ROOT, "app", "index.html")
OUT_STATIC = os.path.join(ROOT, "app", "artifact.html")

# quante edizioni incorporare nella copia di sola lettura
STATIC_LIMIT = 30


def js(value):
    """Serializza per l'inserimento in un letterale JavaScript."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


ICON = os.path.join(ROOT, "app", "icon.png")


def document(rendered):
    """Avvolge il contenuto del template in un documento HTML completo.

    Il template nasce per gli Artifact, che iniettano da sé doctype, head e
    body. Servito da un host qualsiasi quello scheletro manca, e senza il
    meta viewport la pagina esce a larghezza desktop sul telefono.
    """
    cut = rendered.index("</style>") + len("</style>")
    head, body = rendered[:cut], rendered[cut:]

    icon = ""
    if os.path.exists(ICON):
        with open(ICON, "rb") as fh:
            icon = base64.b64encode(fh.read()).decode()
        # la stessa immagine fa da icona sulla schermata di casa e nella
        # scheda del browser: una sola sorgente, nessun file da tenere allineato
        src = f"data:image/png;base64,{icon}"
        icon = (f'\n  <link rel="apple-touch-icon" href="{src}">'
                f'\n  <link rel="icon" type="image/png" href="{src}">')

    return (
        '<!DOCTYPE html>\n'
        '<html lang="it">\n'
        '<head>\n'
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '  <meta name="color-scheme" content="light dark">\n'
        '  <meta name="theme-color" content="#EDEAE3" media="(prefers-color-scheme: light)">\n'
        '  <meta name="theme-color" content="#131418" media="(prefers-color-scheme: dark)">\n'
        '  <meta name="description" content="Rassegna stampa Apple quotidiana.">\n'
        '  <meta name="apple-mobile-web-app-capable" content="yes">\n'
        '  <meta name="mobile-web-app-capable" content="yes">\n'
        '  <meta name="apple-mobile-web-app-title" content="Morning Brief">\n'
        '  <meta name="apple-mobile-web-app-status-bar-style" content="default">\n'
        '  <meta name="robots" content="noindex, nofollow">'
        + icon + '\n'
        + head + '\n'
        '</head>\n'
        '<body>' + body + '\n</body>\n</html>\n'
    )

def render(template, mode, config, briefs, app_url):
    out = template.replace('/*__MODE__*/"static"', js(mode))
    out = out.replace("/*__CONFIG__*/null", js(config))
    out = out.replace("/*__BRIEFS__*/[]", js(briefs))
    out = out.replace('/*__APP_URL__*/""', js(app_url))
    return out


def main():
    argparse.ArgumentParser(description=__doc__.strip().split("\n")[0]).parse_args()

    files = sorted(glob.glob(os.path.join(BRIEFS_DIR, "*.json")), reverse=True)
    if not files:
        print("Nessun brief in data/briefs/", file=sys.stderr)
        return 1

    briefs = []
    for path in files:
        with open(path, encoding="utf-8") as fh:
            briefs.append(json.load(fh))

    with open(TEMPLATE, encoding="utf-8") as fh:
        template = fh.read()

    config, app_url = None, ""
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as fh:
            cfg = json.load(fh)
        host = re.match(r"(https://[^/]+)", cfg.get("url", "").strip())
        if host and "xxxx" not in host.group(1) and "INCOLLA" not in cfg.get("anon_key", ""):
            config = {"url": host.group(1), "anon_key": cfg["anon_key"]}
            # Storage conserva il file ma lo serve come text/plain:
            # la pagina vera la restituisce la Edge Function "app"
            app_url = cfg.get("app_url") or f"{config['url']}/functions/v1/app"

    os.makedirs(os.path.dirname(OUT_CLOUD), exist_ok=True)

    if config:
        with open(OUT_CLOUD, "w", encoding="utf-8") as fh:
            fh.write(document(render(template, "cloud", config, [], "")))
        print(f"Generato {OUT_CLOUD}  (cloud, edizioni lette da Supabase)")
        print(f"  indirizzo pubblico: {app_url}")
    else:
        # senza configurazione la versione cloud non ha senso: incorporiamo
        # l'archivio così il file resta comunque apribile in locale
        with open(OUT_CLOUD, "w", encoding="utf-8") as fh:
            fh.write(document(render(template, "static", None, briefs, "")))
        print(f"Generato {OUT_CLOUD}  (locale, archivio incorporato)")
        print("  supabase/config.json assente: vedi SETUP.md per il passaggio al cloud")

    embedded = briefs[:STATIC_LIMIT]
    with open(OUT_STATIC, "w", encoding="utf-8") as fh:
        fh.write(render(template, "local", None, embedded, app_url))
    size = os.path.getsize(OUT_STATIC) // 1024
    print(f"Generato {OUT_STATIC}  (appunti locali, {len(embedded)} edizioni, {size} KB)")

    total = sum(len(b.get("news", [])) for b in briefs)
    print(f"Archivio: {len(briefs)} edizioni, {total} notizie")
    return 0


if __name__ == "__main__":
    sys.exit(main())
