#!/usr/bin/env python3
"""
Disegna l'icona dell'app.

    python3 pipeline/icon.py            riscrive app/icon.png (1024px)
    python3 pipeline/icon.py --check    salva una prova a 60, 120 e 180 punti

L'icona è la testata compressa: i tre pallini del marchio e il monogramma in
condensato pesante, giallo su inchiostro. Fondo scuro e non osso perché
un'icona chiara sparisce sugli sfondi chiari di iOS, mentre il giallo tiene
su entrambi. Niente sfumature e niente angoli arrotondati: la maschera la
mette iOS, e se la disegnassimo noi verrebbe tagliata due volte.

build.py incorpora il file come apple-touch-icon dentro l'app.
"""

import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "app", "icon.png")

SIZE = 1024
INK = (23, 24, 27)
YELLOW = (247, 206, 60)
RED = (240, 67, 92)
BLUE = (53, 182, 236)

FONT = "/System/Library/Fonts/Avenir Next Condensed.ttc"
FONT_HEAVY = 8                      # indice della sezione Heavy dentro il .ttc
WORD = "TMB"


def load_font(px):
    try:
        return ImageFont.truetype(FONT, px, index=FONT_HEAVY)
    except OSError:
        sys.exit(f"Carattere non trovato: {FONT}")


def fit_font(draw, text, target_w):
    """Il corpo che porta la parola alla larghezza voluta."""
    px = 100
    f = load_font(px)
    w = draw.textbbox((0, 0), text, font=f)[2]
    px = int(px * target_w / max(w, 1))
    return load_font(px)


def draw_icon(size=SIZE):
    img = Image.new("RGB", (size, size), INK)
    d = ImageDraw.Draw(img)
    u = size / 1024.0                       # tutto in proporzione al lato

    # Il monogramma comanda l'impaginato: si fissa la sua larghezza, e i
    # pallini si allineano al suo bordo sinistro come fanno in testata.
    f = fit_font(d, WORD, 648 * u)
    box = d.textbbox((0, 0), WORD, font=f)
    w, h = box[2] - box[0], box[3] - box[1]

    r = 47 * u                              # pallini generosi: a 60 punti
    gap = 126 * u                           # quelli piccoli sparivano
    salto = 132 * u                         # aria fra i pallini e le lettere

    # Il gruppo sta un filo sopra la meta' geometrica: dentro la maschera
    # tonda di iOS un blocco centrato matematicamente sembra caduto in basso.
    blocco = h + salto + 2 * r
    top = (size - blocco) / 2 - 26 * u

    left = (size - w) / 2
    cy = top + r
    for i, col in enumerate((RED, YELLOW, BLUE)):
        cx = left + r + i * gap
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)

    d.text((left - box[0], top + 2 * r + salto - box[1]), WORD, font=f, fill=YELLOW)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="salva anche una prova alle misure vere, per guardarla piccola")
    args = ap.parse_args()

    img = draw_icon()
    img.save(OUT, "PNG", optimize=True)
    print(f"Scritta {OUT}  ({os.path.getsize(OUT) // 1024} KB, {SIZE}px)")

    if args.check:
        sheet = Image.new("RGB", (760, 300), (237, 234, 227))
        x = 40
        for px in (60, 120, 180):
            small = img.resize((px, px), Image.LANCZOS)
            sheet.paste(small, (x, 150 - px // 2))
            x += px + 60
        path = os.path.join(ROOT, "app", "icon-prova.png")
        sheet.save(path, "PNG")
        print(f"Prova alle misure vere: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
