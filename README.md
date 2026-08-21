# The Morning Brief

Una rassegna stampa Apple al giorno, scritta alle 7:00, sincronizzata fra Mac e iPhone.

- **App:** https://c4gv4kf4d7-dev.github.io/morning-brief/
- **Copia di riserva (appunti locali):** https://claude.ai/code/artifact/d308625e-2cb9-48ef-8da6-fa8a2690cb1c

## Come funziona

Ogni mattina alle 7:00 un task legge otto feed RSS, scarta il rumore, accorpa le notizie
che più testate raccontano, ne sceglie 15–20 e le riscrive in italiano con dati e citazioni
verificati sugli articoli originali. Poi carica l'edizione su Supabase.

L'intelligenza sta lì, nella corsa delle 7:00. L'app è la vetrina: non elabora niente, mostra
quello che è già stato scritto. Leggerla non consuma nulla.

## Cosa c'è dentro

**Edizione** — le tre notizie che contano, l'apertura del giorno, poi 15–20 notizie ordinate
per rilevanza. Ognuna ha una riga di sintesi, un paragrafo di approfondimento, il link
all'articolo migliore e le fonti. La pastiglia colorata dice il tipo di notizia, il pallino
accanto quanto è affidabile. In fondo *Radar*: il contorno tech non-Apple.

**Archivio** — tutte le edizioni pubblicate.

**Salvati** — le notizie marcate con ☆, da qualunque giorno e da qualunque dispositivo.

**Diario** — appunti liberi con etichette (Idea, Lavoro, Da approfondire, Video, Contenuto,
Personale) e link allegati. Dagli appunti di una notizia puoi mandare tutto qui con un tocco.

**Cerca** — cerca insieme nell'archivio, nei tuoi appunti e nel diario.

## Sincronizzazione

Appunti, salvati e diario stanno su Supabase e ti seguono fra i dispositivi. Il pallino nella
testata dice lo stato: verde sincronizzato, blu in corso, grigio offline, rosso errore.

L'app funziona anche senza rete: legge dalla cache e accumula le modifiche, che partono da sole
appena torni online.

I pulsanti ↧ / ↥ esportano e reimportano tutto come JSON, se ti serve una copia fuori da Supabase.

## Comandi

```bash
python3 pipeline/fetch.py --hours 26
```

Raccoglie i feed. Poi si scrive l'edizione in `data/briefs/`, e:

```bash
python3 pipeline/push.py
```

La carica su Supabase. Solo se cambia il codice dell'app:

```bash
python3 pipeline/build.py && python3 pipeline/upload_app.py
```

Procedura completa e regole editoriali in [CLAUDE.md](CLAUDE.md).
Configurazione iniziale in [SETUP.md](SETUP.md).

## Fonti

9to5Mac · MacRumors · BGR · Macitynet · iSpazio · Tom's Hardware IT · Wired Italia · The Verge
