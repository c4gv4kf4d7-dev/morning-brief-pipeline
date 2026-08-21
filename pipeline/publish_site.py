#!/usr/bin/env python3
"""
Pubblica l'app su GitHub Pages.

Copia app/index.html in site/index.html e lo carica nel repository
c4gv4kf4d7-dev/morning-brief usando l'API Contents di GitHub. Serve solo
quando cambia pipeline/template.html: le edizioni quotidiane viaggiano su
Supabase e non toccano la pagina.

Autenticazione: GITHUB_TOKEN in .env.local (token fine-grained con permesso
Contents: Read and write sul solo repository morning-brief). Non serve la CLI
gh, che su questo Mac non e' autenticabile senza GitHub Mobile.

    python3 pipeline/publish_site.py            carica
    python3 pipeline/publish_site.py --local    solo copia in site/, niente rete
"""
import argparse
import base64
import json
import os
import shutil
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "c4gv4kf4d7-dev/morning-brief"
PATH = "index.html"
API = "https://api.github.com/repos/%s/contents/%s" % (REPO, PATH)
PAGE = "https://c4gv4kf4d7-dev.github.io/morning-brief/"


def read_token():
    env = os.path.join(ROOT, ".env.local")
    if os.path.exists(env):
        with open(env, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("GITHUB_TOKEN=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip()
    return os.environ.get("GITHUB_TOKEN", "").strip()


def call(token, method="GET", payload=None):
    req = urllib.request.Request(API, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data) as res:
        return json.load(res)


def fail(msg, dst):
    print(msg)
    print("Ripiego: carica a mano %s da https://github.com/%s -> Add file -> Upload files"
          % (dst, REPO))
    sys.exit(1)


def main():
    # Senza argparse un flag sconosciuto — "--help" per primo — cadeva nel vuoto
    # e lo script pubblicava lo stesso: qui una pubblicazione e' un commit su un
    # repository pubblico, quindi l'argomento sbagliato deve fermare tutto.
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("--local", action="store_true",
                    help="solo copia in site/, senza toccare la rete")
    args = ap.parse_args()

    src = os.path.join(ROOT, "app", "index.html")
    if not os.path.exists(src):
        sys.exit("app/index.html non trovato — lancia prima pipeline/build.py")
    dst = os.path.join(ROOT, "site", "index.html")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    print("Pronto: %s  (%d KB)" % (dst, os.path.getsize(dst) // 1024))

    if args.local:
        return

    token = read_token()
    if not token:
        fail("\nManca GITHUB_TOKEN in .env.local: non posso caricare.", dst)

    with open(dst, "rb") as fh:
        raw = fh.read()
    body = base64.b64encode(raw).decode()

    sha = None
    try:
        cur = call(token)
        sha = cur["sha"]
        if cur.get("content") and base64.b64decode(cur["content"]) == raw:
            print("Nessuna modifica: online c'e' gia' questa versione.")
            return
    except urllib.error.HTTPError as err:
        if err.code == 401:
            fail("\nToken rifiutato (401): scaduto o sbagliato. Rigeneralo.", dst)
        if err.code == 403:
            fail("\nToken senza permessi (403): serve Contents: Read and write "
                 "sul repository %s." % REPO, dst)
        if err.code != 404:      # 404 = prima pubblicazione, il file non c'e' ancora
            fail("\nErrore leggendo %s: %s" % (PATH, err.code), dst)

    payload = {"message": "Aggiorna l'app", "content": body}
    if sha:
        payload["sha"] = sha
    try:
        out = call(token, "PUT", payload)
    except urllib.error.HTTPError as err:
        fail("\nErrore caricando %s: %s %s"
             % (PATH, err.code, err.read().decode()[:300]), dst)

    print("Caricato: commit %s" % out["commit"]["sha"][:7])
    print("Online fra un minuto su " + PAGE)


if __name__ == "__main__":
    main()
