#!/usr/bin/env python3
"""
Arricchisce un'edizione con le immagini degli articoli.

Legge l'og:image di ogni notizia, la ridimensiona e la incorpora nel JSON
come data URI. Incorporare invece di linkare serve a due cose: le immagini
funzionano offline, e la copia su Artifact le mostra (la sua CSP blocca
qualunque richiesta verso l'esterno).

    python3 pipeline/images.py                    edizione di oggi
    python3 pipeline/images.py 2026-08-08         una data precisa
    python3 pipeline/images.py --prune 60         toglie le immagini dalle
                                                  edizioni più vecchie di 60 giorni
"""

import argparse
import base64
import concurrent.futures as cf
import glob
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIEFS = os.path.join(ROOT, "data", "briefs")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

# quante notizie ricevono la miniatura, e con che ingombro.
# 480px perche' sul telefono la foto occupa tutta la colonna (~341 punti):
# a 300px si vedeva la sgranatura. Sono ~25 KB l'una invece di ~10.
THUMBS = 8
THUMB_PX, THUMB_Q = 480, 60
HERO_PX, HERO_Q = 880, 70

OG_PATTERNS = (
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
)


def fetch(url, timeout=25):
    try:
        out = subprocess.run(["curl", "-sL", "--max-time", str(timeout), "-A", UA, url],
                             capture_output=True, timeout=timeout + 10)
        return out.stdout
    except Exception:
        return b""


def find_image_url(page_url):
    html = fetch(page_url).decode("utf-8", "replace")
    for pat in OG_PATTERNS:
        m = re.search(pat, html, re.I)
        if m:
            src = m.group(1).strip()
            if src.startswith("//"):
                src = "https:" + src
            return src if src.startswith("http") else None
    return None


def encode(raw, width, quality):
    """Ridimensiona, ritaglia in 16:9 e restituisce un data URI JPEG."""
    try:
        img = Image.open(io.BytesIO(raw))
    except Exception:
        return None
    img = img.convert("RGB")

    target = 16 / 9
    w, h = img.size
    if w / h > target:                       # troppo larga: taglio ai lati
        new_w = int(h * target)
        img = img.crop(((w - new_w) // 2, 0, (w + new_w) // 2, h))
    else:                                    # troppo alta: taglio sopra e sotto
        new_h = int(w / target)
        top = int((h - new_h) * 0.35)        # leggermente più alto del centro:
        img = img.crop((0, top, w, top + new_h))   # nelle foto il soggetto sta in alto

    if img.width > width:
        img = img.resize((width, int(width / target)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def harvest(job):
    idx, news = job
    src = find_image_url(news.get("link", ""))
    if not src:
        return idx, None, None
    raw = fetch(src)
    if not raw:
        return idx, None, None
    thumb = encode(raw, THUMB_PX, THUMB_Q)
    hero = encode(raw, HERO_PX, HERO_Q) if idx == 0 else None
    return idx, thumb, hero


def enrich(path, refresh=False):
    with open(path, encoding="utf-8") as fh:
        brief = json.load(fh)

    jobs = [(i, n) for i, n in enumerate(brief.get("news", [])[:THUMBS])
            if refresh or not n.get("image")]
    if not jobs:
        print("Immagini già presenti, niente da fare.")
        return 0

    got = 0
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        for idx, thumb, hero in pool.map(harvest, jobs):
            news = brief["news"][idx]
            # in --refresh una fonte muta non deve cancellare quel che c'era
            if thumb:
                news["image"] = thumb
                got += 1
            if hero:
                news["hero"] = hero
            print(f"  {news['id']:22} {'immagine acquisita' if thumb else 'nessuna immagine'}")

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(brief, fh, ensure_ascii=False, indent=1)

    size = os.path.getsize(path) // 1024
    print(f"{got} immagini su {len(jobs)} notizie · edizione ora {size} KB")
    return 0


def prune(days):
    limit = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    touched = 0
    for path in sorted(glob.glob(os.path.join(BRIEFS, "*.json"))):
        day = os.path.basename(path)[:-5]
        if day >= limit:
            continue
        with open(path, encoding="utf-8") as fh:
            brief = json.load(fh)
        before = os.path.getsize(path)
        stripped = False
        for n in brief.get("news", []):
            for k in ("image", "hero"):
                if n.pop(k, None) is not None:
                    stripped = True
        if stripped:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(brief, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
            print(f"  {day}: {before // 1024} KB -> {os.path.getsize(path) // 1024} KB")
            touched += 1
    print(f"Alleggerite {touched} edizioni oltre i {days} giorni.")
    print("Ricaricale su Supabase con: python3 pipeline/push.py --all")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", help="data dell'edizione (YYYY-MM-DD)")
    ap.add_argument("--prune", type=int, metavar="GIORNI",
                    help="toglie le immagini dalle edizioni più vecchie di N giorni")
    ap.add_argument("--refresh", action="store_true",
                    help="riscarica anche le immagini già presenti (dopo un cambio di formato)")
    ap.add_argument("--all", action="store_true",
                    help="lavora su tutte le edizioni dell'archivio, non solo su una")
    args = ap.parse_args()

    # "is not None" e non la verita' del numero: --prune 0 vuol dire "togli le
    # immagini a tutto l'archivio", ed e' un comando legittimo che il controllo
    # sulla verita' buttava via in silenzio
    if args.prune is not None:
        return prune(args.prune)

    if args.all:
        for name in sorted(os.listdir(BRIEFS)):
            if name.endswith(".json"):
                print(name[:-5])
                enrich(os.path.join(BRIEFS, name), refresh=args.refresh)
        return 0

    day = args.date or datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(BRIEFS, f"{day}.json")
    if not os.path.exists(path):
        sys.exit(f"Nessuna edizione per il {day}.")
    return enrich(path, refresh=args.refresh)


if __name__ == "__main__":
    sys.exit(main())
