# The Morning Brief — istruzioni operative

Questo progetto produce **una rassegna stampa Apple al giorno** e la pubblica sull'**app
sincronizzata** su GitHub Pages: appunti, salvati e diario seguono l'utente fra Mac e
iPhone. L'indirizzo è in `.app-url`.

La copia Artifact su claude.ai (`.artifact-url`) **non si aggiorna più**: da agosto 2026
Mike legge solo l'app online. `build.py` continua a generare `app/artifact.html`, ma
resta un file locale — non va ripubblicato, e l'indirizzo si tiene solo per storia.

I dati (edizioni, appunti, diario) vivono su Supabase. L'app è un file statico che li legge.

---

## Procedura della corsa giornaliera (ore 07:00)

Esegui **tutti** questi passi, in ordine, da `/Users/mike/Desktop/Tech_news`.

### 1. Raccolta

```bash
python3 pipeline/fetch.py --hours 26
```

Scrive `data/raw/YYYY-MM-DD.json` con gli articoli delle ultime 26 ore (finestra un po' più
larga di 24h per non perdere i pezzi a cavallo). Segnala i feed irraggiungibili o fermi.

Le fonti attive stanno in `data/sources.json`, non più in `fetch.py`: quelle in panchina
non vengono raccolte (vedi *Manutenzione delle fonti*).

Ogni articolo si porta dietro il **girone** della sua fonte (`tier`), e il girone dice in
che parte dell'edizione finirà:

| Girone | Chi c'è | Dove finisce |
|---|---|---|
| `primaria` | Apple Newsroom, Apple Developer | fra le notizie, e chiude i rumor |
| `redazionale` | 9to5Mac, MacRumors, Macitynet, iSpazio, BGR, Tom's, The Verge | fra le notizie |
| `larga` | Ars Technica, TechCrunch | sonde del radar |
| `ai` | OpenAI, Google DeepMind, The Decoder, TechCrunch AI, Ars Technica AI, MIT Technology Review AI | presidio AI del radar |
| `banco` | DDay.it, HDblog, GSMArena, Android Authority, Andrea Galeazzi, MKBHD | sezione *Sul banco* |

`ai` e `banco` pubblicano a strappi: un laboratorio annuncia quando ha finito, un canale
quando il video è montato. Il campanello dei feed muti per loro suona dopo una settimana
(dodici giorni per i video), non dopo un giorno, e `feedcheck.py` non li manda in panchina
per una settimana di silenzio.

```bash
python3 pipeline/social.py --hours 30
```

Raccoglie le discussioni — Reddit, Hacker News e quello che hai incollato a mano in
`data/social/manual.md` — e le divide in due mucchi: **eco** (si parla di una notizia che
abbiamo già) e **nuovo** (se ne parla e da noi non c'è). Il secondo mucchio è il motivo
per cui esiste il passo: a volte lì dentro c'è una cosa che le testate non hanno ancora.

### 2. Selezione e scrittura

Prima di scrivere, guarda cosa è rimasto aperto dalle edizioni precedenti:

```bash
python3 pipeline/threads.py list && python3 pipeline/claims.py open --due 30 && python3 pipeline/facts.py moving
python3 pipeline/missed.py
```

Le storie in corso, le previsioni che stanno per scadere, i numeri che si sono mossi.
Se una notizia di oggi continua un filo, chiude una previsione o rivede una stima, va
detto: è il motivo per cui esistono. L'ultimo comando propone i candidati per «Se te lo
fossi perso» (vedi *Il ripescaggio*): quasi sempre non se ne prende nessuno, e va bene.

Poi guarda cosa hanno detto i pollici, che è il modo in cui la selezione si tara:

```bash
python3 pipeline/taste.py
```

Stampa i declassamenti attivi e le cinque caselle del radar di oggi (vedi *Il gusto*).

Leggi il file grezzo. Per le 8–12 notizie più importanti scarica l'articolo completo
(`curl -sL` + strip dei tag) per avere dettagli e citazioni verificabili: **non scrivere
descrizioni basandoti solo sull'abstract RSS**.

Poi scrivi `data/briefs/YYYY-MM-DD.json` seguendo esattamente lo schema di
`data/briefs/2026-08-08.json`. Regole editoriali:

- **Perimetro**: Apple al centro. Ammesso il contorno che la tocca da vicino (rivali diretti,
  AI, chip, regolamentazione UE/USA), da tenere però in coda o nel blocco `radar`. Il
  materiale dei gironi `ai` e `banco` **non entra fra le notizie**: ha le sue sezioni, e ci
  finisce solo se tocca Apple direttamente (un accordo Apple-Gemini è una notizia, il
  lancio di un modello no).
- **15–20 notizie** in `news`, ordinate per importanza reale (rank 1 = la più rilevante).
- **Niente duplicati**: se più testate coprono lo stesso fatto, un solo blocco con `sources`
  multiple e gli altri URL in `extra_links`.
- **Top 3**: una riga secca ciascuna, stile headline.
- **Intro**: 3–4 righe sul quadro della giornata, non un riassunto delle notizie.
- **Sintesi**: una riga. **Descrizione**: 3–4 righe con dati concreti, virgolette dove ci sono
  dichiarazioni, contesto utile.
- **Tono**: giornalistico, asciutto, tipo Bloomberg. Niente hype, niente entusiasmo da creator.
- **Non inventare nulla.** Se un dato non è nell'articolo, non va nel brief.

Campo `tag` (determina il colore della pastiglia):
`CONFERMATO` (blu) · `RUMOR` (giallo) · `DATI` (arancio) · `ANALISI` / `OPINIONE` (rosso) ·
`CONTORNO` / `CONTESTO` / `SERVIZIO` (nero).

Campo `reliability`: `alta` | `media` | `bassa`, con `reliability_note` che spiega **perché**.

| Fonte | Affidabilità |
|---|---|
| Documenti ufficiali, atti giudiziari, newsroom Apple | alta |
| Gurman (Bloomberg), Kuo, Ross Young, Counterpoint, IDC | alta |
| Digitimes, ETNews, catena di fornitura anonima | media |
| Leaker Weibo/X senza track record, Reddit, forum | bassa |

Rumor e gossip **si includono**, ma sempre marcati con `tag: "RUMOR"` e una nota sulla fonte.

`radar`: **6 voci** brevi di contorno tech non-Apple, ognuna con `id` (slug stabile, serve
al voto) e `topic` (l'unità su cui il radar impara). Una casella è il **presidio AI** e non
si muove, tre vengono da temi già graditi, due sono **sonde** su temi da provare: la
composizione la propone `taste.py` (vedi *Il gusto*).

**Il presidio AI.** I laboratori — OpenAI, Anthropic, Google DeepMind — non sono un tema
come gli altri: sono il fronte su cui si decide anche quello che Apple farà fra due anni.
Una casella del radar è loro per statuto, come il nucleo Apple fra le notizie. I pollici
scelgono *quale* topic AI mostrare, non se mostrarne uno. I topic del presidio sono quelli
che in `data/radar_topics.json` hanno `"axis": "ai"` — oggi `openai`, `anthropic`,
`google-ai` (è Gemini), `modelli-ai`, `ai-agenti`, `ai-regole`. Se ne aggiunge uno
scrivendolo nel file con quel campo.

```json
{"id": "pebble-ritorno", "topic": "hardware-indipendente",
 "title": "…", "note": "…", "link": "…", "source": "Tom's Hardware IT"}
```

`feed_notes`: segnala i feed muti o fermi rilevati al passo 1. **Non compare più
nell'app** — è diagnostica della pipeline, non roba da leggere a colazione: resta
nell'edizione e si guarda dal Mac con `lint.py` e `feedcheck.py`.

#### Il filo — `thread`

Se la notizia è una puntata di una storia che va avanti nel tempo, aggiungi lo slug del filo:

```json
"thread": "silicio-mac"
```

I fili esistenti sono in `data/threads.json` (slug, etichetta, nota). Per capire a quale
agganciare le notizie di oggi:

```bash
python3 pipeline/threads.py suggest
```

È solo una proposta per somiglianza: la decisione è editoriale. Un filo nuovo si apre
scrivendo uno slug che non esiste ancora — `threads.py sync` lo registra con
un'etichetta provvisoria, che poi va corretta a mano in `data/threads.json`. Meglio
pochi fili larghi e duraturi che tanti fili da una puntata sola.

#### La previsione — `claim` e `resolves`

Ogni rumor sostiene che succederà qualcosa. Scritta per esteso, prima o poi si può
verificare. **Ogni notizia con `tag: "RUMOR"` deve avere un `claim`**, e possono averlo
anche le altre quando contengono una previsione datata:

```json
"claim": {
  "id": "m6-pro-autunno",
  "text": "In autunno arriva un MacBook Pro con chip M6 Pro",
  "source": "9to5Mac",
  "horizon": "2026-11-30"
}
```

`text` deve essere **falsificabile**: una cosa che a una certa data o è successa o no.
Niente "Apple lavora a…". `horizon` è la data entro cui si saprà. `source` è chi l'ha
detta, non chi l'ha ripresa: se Macitynet riporta Gurman, la fonte è Gurman.

Quando una notizia chiude una previsione aperta, glielo si dice addosso:

```json
"resolves": [
  {"claim": "m6-pro-autunno", "verdict": "smentito",
   "note": "Gurman: M6 Pro e Max cancellati, si passa direttamente all'M7."}
]
```

Verdetti: `confermato` · `parziale` · `smentito`. Una previsione il cui `horizon` passa
senza che nessuno l'abbia chiusa diventa da sola `scaduta`, e nelle pagelle pesa come
un errore. In alternativa al campo scritto a mano:

```bash
python3 pipeline/claims.py resolve m6-pro-autunno smentito --story m7-accelerazione --note "..."
```

Fili e previsioni **vivono dentro le edizioni**, non in una tabella a parte: viaggiano
da soli con `push.py`, senza bisogno di query aggiuntive dall'app.

#### I numeri — `facts`

Quasi tutto in questo mestiere è un numero che qualcuno rivede: un prezzo stimato, una
data d'uscita, una quota di mercato. Preso una volta è un dettaglio, seguito nel tempo
è una deriva — e la deriva è spesso la notizia vera. Quando una notizia porta un numero
che vale la pena seguire, si scrive:

```json
"facts": [
  {"key": "iphone18-pro-prezzo", "value": 1299, "unit": "USD",
   "kind": "stima", "source": "9to5Mac (stime di analisti)"}
]
```

`value` è un numero o una data ISO. `kind` è `dato` (è successo, è misurato, è a
listino) oppure `stima` (qualcuno prevede che sarà così) — **non confonderli mai**:
tutto il senso della serie sta nel distinguere il previsto dall'accaduto.

Etichetta e unità stanno una volta sola in `data/facts.json`; `facts.py sync` le
ricopia dentro le letture. Se una metrica non esiste ancora, la chiave nuova la crea —
poi l'etichetta va corretta a mano nel registro.

Regole: la stessa metrica sempre con la **stessa chiave e la stessa unità**, altrimenti
non è una serie. Un valore va scritto solo se è nell'articolo. Se la fonte dà una
forchetta ("fra 1.299 e 1.399"), si registra l'estremo basso e la forchetta si racconta
nella descrizione.

Nell'app le serie compaiono dentro la notizia e, raggruppate, dentro il filo.

#### Le pagelle — strumento tuo, non dell'app

Il conto di chi ci prende **non compare nella rassegna**: nessuno vuole leggere una
classifica delle fonti a colazione. Serve a te, prima di scrivere, per decidere che
`reliability` mettere:

```bash
python3 pipeline/claims.py score
```

Se una fonte ha un tasso basso su un campione decente, il suo prossimo rumor non è
`alta` per definizione, per quanto blasonata sia — la tabella in cima a questo file è il
punto di partenza, le pagelle la correggono con i fatti. Nell'app resta solo la parte
che è notizia: sulla vecchia notizia compare "Come è andata a finire", su quella nuova
"Chiude una previsione".

#### La sezione social — `social`

Un blocco a parte, dopo il radar, per quello che si dice. Regole strette:

- **Non sono fatti.** Se una cosa vista lì diventa una notizia, va nel blocco `news` con
  la sua fonte vera, `tag: "RUMOR"` e `reliability: "bassa"`, non qui.
- **Si cita la discussione, non si spaccia per verificata.** "Un utente sostiene",
  "il thread più votato", "36 punti e 69 commenti": il segnale è la misura, non il merito.
- **Niente assistenza e niente vetrina.** `social.py` mette già da parte i post di
  supporto e le foto degli acquisti. Un guasto singolo non è mai una notizia; lo stesso
  guasto per giorni sì, e allora si verifica e diventa una notizia vera.
- 3–5 voci, mai di più. `origine: "nuovo"` segna quelle che le testate non hanno dato:
  nell'app prendono la pastiglia rossa.

Su **X** non c'è modo legittimo di raccogliere in automatico: niente RSS, niente API
gratuita, e raschiare le pagine viola le condizioni. Il percorso è manuale e funziona
bene: quando vedi un thread che conta, incolla il link in `data/social/manual.md` con
una riga di contesto, e al giro dopo entra nella raccolta come tutto il resto.

#### La sezione da lavoro — `banco`

Mike sta dietro il banco di un Apple Store. Metà delle domande che riceve non riguardano
Apple: riguardano quello che il cliente ha visto ieri sera in un video. Il pieghevole
Samsung, il Pixel, la cover che costa quanto il telefono. Questa sezione è materiale da
lavoro, non rassegna: **3–5 voci** fra recensioni, video e confronti della concorrenza.

```json
{"id": "fold8-mkbhd", "kind": "video", "topic": "pieghevoli",
 "title": "Galaxy Z Fold 8 Review: Honeymoon's Over",
 "note": "Cosa dice il pezzo, due righe.",
 "perche": "È il video che ha visto il cliente che entra a chiedere del pieghevole.",
 "link": "…", "source": "MKBHD"}
```

`kind` è `recensione` · `video` · `confronto` · `curiosità` · `guida`, e determina il
colore della pastiglia. **`perche` è la sezione**: senza quella riga è una recensione
qualsiasi, e il lint la respinge come errore. Deve dire perché quella cosa serve *al
banco* — la domanda che arriverà, il confronto che ti chiederanno, il dettaglio che non
sai. Non "è interessante".

Il materiale arriva dal girone `banco` del file grezzo (`"tier": "banco"`): DDay.it,
HDblog, GSMArena, Android Authority e i due canali YouTube, Andrea Galeazzi e MKBHD.
I video si riconoscono dal link `youtube.com/watch`.

#### Il ripescaggio — `recap`

«Se te lo fossi perso»: **0–3 voci**, e lo zero è un risultato onesto. La rassegna guarda
26 ore e il perimetro Apple, ed è il suo buco: una cosa che esplode di martedì fuori
perimetro non entra mai più, perché ogni giorno guarda solo il proprio. Questa sezione
guarda indietro da 3 a 14 giorni e ripesca quello che ha girato e che noi non abbiamo dato.

```bash
python3 pipeline/missed.py
```

Incrocia due segnali: la **copertura** (quante testate diverse fra le nostre hanno
raccontato lo stesso fatto) e la **trazione** (punti e commenti su Hacker News, posizione
nel top della settimana di Reddit). Toglie tutto quello che è già passato in edizione — è
il senso del nome — e stampa i candidati ordinati, marcati `COPERTURA`, `SOLO ONLINE` o
`COMMENTO`. La scelta resta editoriale: escono candidati, non voci.

```json
{"id": "anthropic-open-weights", "when": "2026-07-27",
 "title": "…", "note": "3-4 righe: cos'era e perché ne hanno parlato tutti",
 "signal": "1.180 punti e 1.747 commenti su Hacker News",
 "link": "…", "source": "Anthropic"}
```

`when` è la data d'origine, non quella di oggi: l'app la mostra come «2 settimane fa».
Sotto i due giorni non è un ripescaggio, è la rassegna di ieri, e il lint dà errore. Stessa
cosa se la voce è già uscita in una vecchia edizione: quello svuota la sezione del suo
senso, e il collaudo la blocca.

`signal` è obbligatorio ed è la misura, non il giudizio: quanti punti, quante testate,
quale posizione. È il motivo per cui la voce sta lì.

#### Controllo prima di pubblicare

```bash
python3 pipeline/threads.py sync && python3 pipeline/facts.py sync
python3 pipeline/lint.py
```

I due `sync` registrano fili e metriche nuove e ne ricopiano le etichette dentro le
edizioni — **vanno lanciati sempre**, altrimenti l'app mostra lo slug al posto del nome.

`lint.py` collauda l'edizione contro le regole di questo file: campi obbligatori, rank
senza buchi, descrizioni senza un solo dato concreto, citazioni senza attribuzione,
doppioni, tono da creator, rumor senza previsione. Distingue **errori** (l'edizione è
rotta, si sistema prima di pubblicare) da **avvisi** (fuori misura, spesso voluto, ma
da guardare), ed esce con 1 se trova errori. Con `--links` controlla anche che ogni
indirizzo apra davvero.

Per i controlli più fini, che il lint non ripete:

```bash
python3 pipeline/threads.py check && python3 pipeline/claims.py check && python3 pipeline/facts.py check
```

#### Il gusto — i pollici, `taste.py`

Ogni notizia e ogni voce di radar, banco e ripescaggio hanno due pollici nell'app. Il voto
**non dice "mi piace l'argomento"**, dice *questa voce meritava di stare in rassegna*: è il
segnale con cui si tara la selezione, non il perimetro.

```bash
python3 pipeline/taste.py            # il digest, prima di scrivere
python3 pipeline/taste.py report     # il briefing, ogni 14 giorni
```

I voti stanno nella colonna `vote` di `brief_marks` (migrazione in
`supabase/migrazioni.sql`, da lanciare una volta sola). `taste.py` li rilegge, li incrocia
con l'archivio locale e ne ricava i pattern lungo cinque assi: **categoria**, **tag**,
**fonte**, **banco** (il genere: recensione, video, confronto…) e **sezione**.

L'asse `sezione` è quello che tiene onesto l'impianto: se «Se te lo fossi perso» prende tre
pollici giù di fila, la sezione non serve e va tolta, non difesa. Vale per tutte e tre le
sezioni non-notizia — radar, banco, ripescaggio.

Tre regole non negoziabili:

- **Si declassa, non si cancella.** Un pattern confermato manda la notizia in coda o nel
  radar. Non la fa sparire.
- **Il nucleo Apple non si tocca.** I voti agiscono su contorno, ordine e radar. Se Apple
  prende una multa UE quella notizia entra, quanti pollici giù ci siano stati. Lo stesso
  vale per il presidio AI: i pollici scelgono quale laboratorio mostrare, non se mostrarne
  uno.
- **Il silenzio non è un no.** Contano solo i voti espressi, e servono 3 voti concordi
  sullo stesso asse (75% di concordia) prima di dare retta a un pattern.

**Il radar impara per topic.** Ogni topic ha uno stato in `data/radar_topics.json`:

| Stato | Come ci si arriva | Cosa comporta |
|---|---|---|
| `nuovo` | mai mostrato | candidato per una sonda |
| `in prova` | mostrato, nessun verdetto | può tornare |
| `confermato` | +2 di scarto fra su e giù | casella fissa nella rotazione |
| `in pausa` | 1 pollice giù, o 3 uscite mute | torna fra 6 settimane |
| `archiviato` | 2 pollici giù | non torna |

**La pausa si sconta una volta sola.** Un pollice giù resta scritto per sempre, quindi
finita la pausa quel voto non rimanda più il topic in panchina: rientra `in prova` e ha
una seconda occasione vera. A bocciarlo è il *secondo* pollice giù. Lo stesso per le
uscite mute, che si ricontano da zero al rientro (`pausa_finita` e `seen_a_fine_pausa` nel
file tengono il segno). Senza questa regola il topic non tornava mai: ogni corsa rivedeva
lo stesso pollice giù e rimandava la scadenza di altre sei settimane.

Un pollice su vale un **seguito il giorno dopo**: il digest lo segna come "da riprendere
per forza". I topic candidati si aggiungono a mano nel file, con stato `nuovo`.

**Il briefing ogni 14 giorni** non è un rapporto da archiviare, è una conversazione: si
mostra cosa sta sparendo e perché, con due o tre titoli d'esempio di quello che è stato
declassato, lo stato dei topic e i voti che si contraddicono. Poi si chiede a Mike se
quello che è uscito gli manca. Il digest avvisa da solo quando è il momento.

### 3. Immagini

```bash
python3 pipeline/images.py
```

Legge l'og:image di ogni articolo fra i primi otto, lo ritaglia in 16:9 e lo incorpora
nell'edizione come data URI: miniatura da 480px per tutti, più una da 880px per la notizia
di apertura. Incorporare invece di linkare serve perché le immagini funzionino offline e
perché la copia su Artifact le mostri — la sua CSP blocca ogni richiesta esterna.

480px perché sul telefono la foto occupa tutta la colonna (~341 punti): a 300px si vedeva
la sgranatura. Se un giorno cambi di nuovo il formato, `--refresh` riscarica anche le
immagini già presenti e `--all` lavora su tutto l'archivio; una fonte che non risponde
lascia al suo posto l'immagine vecchia invece di cancellarla.

```bash
python3 pipeline/images.py --all --refresh && python3 pipeline/push.py --all
```

Costo: circa 150 KB per edizione, una cinquantina di MB l'anno. Ogni tanto alleggerisci
l'archivio, poi ricaricalo:

```bash
python3 pipeline/images.py --prune 60 && python3 pipeline/push.py --all
```

### 4. Pubblicazione sull'app sincronizzata

```bash
python3 pipeline/push.py
```

Carica l'edizione di oggi nella tabella `brief_editions` di Supabase. L'app la vede al successivo
avvio o cambio di scheda: **il file dell'app non va ritoccato**.

### 5. Chiusura

Un messaggio breve: data dell'edizione, le tre notizie di apertura, quante notizie selezionate
su quanti articoli letti, eventuali feed muti. Se una previsione è stata chiusa, una riga anche
su quella. Nient'altro.

---

## Manutenzione delle fonti (una volta a settimana, il lunedì)

```bash
python3 pipeline/feedcheck.py
```

Misura ogni feed su due assi che a occhio non si vedono: quanto arriva **primo** e quanto
**insegue** (stessa notizia, ore dopo qualcun altro), e quanti dei suoi articoli finiscono
davvero in edizione. Un feed può essere vivissimo e inutile — se ripubblica in ritardo
quello che hanno già dato gli altri è eco, non una fonte, e va tolto: costa lettura e non
aggiunge niente.

Il verdetto in fondo (`TIENI` · `SORVEGLIA` · `PANCHINA`) è una proposta, mai
un'esecuzione, e non si decide mai sotto le due settimane di dati.

### La panchina

**Una fonte non si cancella.** Se smette di servire va in panchina: esce dalla raccolta
quotidiana ma resta scritta in `data/sources.json` con la sua data e il suo motivo, e
ogni sette giorni si riprova.

```bash
python3 pipeline/feedcheck.py --bench "Wired Italia" --reason "fermo da 39 giorni"
python3 pipeline/feedcheck.py --retest      # riprova quelle scadute
python3 pipeline/feedcheck.py --restore "Wired Italia"
```

`--retest` scarica il feed e guarda tre cose: se risponde, se ha ripreso a pubblicare, e
se porta roba che le nostre fonti attive non hanno già dato. Se ne trova almeno un paio,
propone di rimetterla in campo. Altrimenti aspetta un'altra settimana. Un giornale che
cambia direzione, un feed spostato, un sito rinato: succede, e la panchina è quello che
permette di accorgersene senza tenerselo in casa nel frattempo.

Il rapporto normale mostra in fondo chi è in panchina e a chi tocca la riprova.

Per il verso opposto — cosa non stiamo leggendo:

```bash
python3 pipeline/feedcheck.py --discover
```

Prova una ventina di fonti candidate e per ognuna misura quanto è nel perimetro Apple e
quanta roba porta che le nostre non hanno già dato. **Attenzione al punteggio**: premia il
volume, quindi una fonte primaria che pubblica due volte a settimana finisce in fondo pur
valendo più di un sito che ne sforna venti al giorno. Guarda `quota` insieme a `punti`.

Le fonti con `QUIET` in `fetch.py` (le due ufficiali Apple) tacciono per settimane senza
che sia un problema: il campanello suona solo dopo tre.

---

## Quando cambia l'app (non ogni giorno)

Solo se hai modificato `pipeline/template.html`:

```bash
python3 pipeline/build.py && python3 pipeline/publish_site.py
```

`publish_site.py` copia il file in `site/index.html` e lo carica da solo su GitHub
(repository `c4gv4kf4d7-dev/morning-brief`, API Contents) con `GITHUB_TOKEN` letto da
`.env.local`. Niente caricamento a mano, niente `gh`: la CLI su questo Mac non è
autenticabile perché l'accesso interattivo vuole una conferma via GitHub Mobile, app che
l'utente non ha. Il token è fine-grained, limitato a quel repository, permesso
Contents: Read and write.

Lo script salta il caricamento se online c'è già lo stesso file, e distingue gli errori:
401 token scaduto, 403 permessi mancanti. In ogni caso il ripiego è il caricamento dal
browser (Add file → Upload files). `--local` copia in `site/` senza toccare la rete.

Le edizioni quotidiane **non** richiedono niente di tutto questo: viaggiano sul database.

### Perché non Supabase

Supabase serve HTML come `text/plain` alle navigazioni da browser, su `*.supabase.co` —
misura anti-phishing, valida sia per Storage sia per il gateway delle Edge Functions, e non
aggirabile. Attenzione al modo in cui si verifica: **curl riceve `text/html`, un browser no**.
Un controllo fatto solo con curl dà un falso positivo. La Edge Function `app` e il bucket
`brief-app` sono resti di quel tentativo: inutilizzati, si possono eliminare.

---

## Struttura

```
pipeline/fetch.py        raccolta RSS, filtro temporale, dedup per URL
pipeline/sources.py      il registro delle fonti: attive, in panchina, riprove
pipeline/social.py       Reddit + Hacker News + appunti a mano  ->  data/social/
pipeline/common.py       lettura/scrittura archivio, somiglianza fra titoli, tabelle
pipeline/threads.py      i fili delle storie: registro, sync, proposte, cronologia
pipeline/claims.py       le previsioni: aperte, verdetti, pagelle per fonte
pipeline/facts.py        i numeri seguiti nel tempo: serie, derive, registro
pipeline/taste.py        i pollici  ->  declassamenti + caselle del radar + briefing
pipeline/missed.py       copertura + trazione online  ->  candidati per il ripescaggio
pipeline/lint.py         il collaudo dell'edizione contro le regole di questo file
pipeline/feedcheck.py    salute delle fonti + ricerca di candidate nuove
pipeline/images.py       og:image  ->  data URI incorporati nell'edizione
pipeline/icon.py         disegna app/icon.png (monogramma + pallini). --check la prova piccola
pipeline/publish_site.py app  ->  site/index.html  ->  GitHub Pages (API Contents, GITHUB_TOKEN)
pipeline/build.py        archivio  →  app/index.html (cloud). Genera anche app/artifact.html,
                         che però non si pubblica più: resta un file locale.
pipeline/push.py         edizioni  →  tabella brief_editions su Supabase
pipeline/upload_app.py   app/index.html  →  Supabase Storage
pipeline/template.html   la web app: stile, markup, accesso, sincronizzazione.
                         I segnaposto /*__MODE__*/ /*__CONFIG__*/ /*__BRIEFS__*/ /*__APP_URL__*/
                         vengono sostituiti da build.py.
supabase/functions/app/  la Edge Function che serve la pagina come HTML
supabase/config.toml     configurazione CLI per la distribuzione della funzione
supabase/migrazioni.sql  i ritocchi allo schema, da lanciare a mano nell'editor SQL.
                         Idempotenti: rilanciarle non fa danno.
supabase/schema.sql      tabelle e regole di sicurezza (già eseguito una volta).
                         Tre tabelle prefissate: brief_editions, brief_marks, brief_diary.
                         Convivono in un progetto Supabase usato anche da altre app.
supabase/config.json     url + anon key. Pubblici, ma non versionarli per abitudine.
.env.local               SUPABASE_SERVICE_KEY + GITHUB_TOKEN. Segreti, restano solo sul Mac.
data/raw/                scarichi grezzi per data
data/briefs/             le edizioni scritte — l'archivio locale, fonte di verità per push.py
data/threads.json        il registro dei fili: slug, etichetta, nota, apertura, chiusura
data/facts.json          il registro delle metriche: chiave, etichetta, unità, nota
data/sources.json        le fonti: stato, da quando, perché, ultima riprova
data/taste.json          l'ultimo scarico dei voti + le regole ricavate + data del briefing
data/radar_topics.json   i temi del radar e il loro stato (nuovo, in prova, confermato…)
data/social/             le discussioni raccolte per data
data/missed/             i candidati al ripescaggio, per data
data/social/manual.md    dove incolli a mano i link da X e affini
app/                     output generato, non modificare a mano
```

## Come funziona la sincronizzazione

Local-first. Ogni modifica va prima in `localStorage`, marcata `dirty`, e viene spinta su
Supabase entro un paio di secondi. In lettura l'app chiede solo le righe con
`updated_at > lastPull`. In conflitto vince la scrittura più recente, con una sola eccezione:
una modifica locale non ancora spinta non viene mai sovrascritta da una lettura.

Offline l'app funziona lo stesso — legge dalla cache e accumula le modifiche, che partono
appena torna la rete. Il pallino nella testata dice lo stato: verde sincronizzato, blu in corso,
grigio offline, rosso errore.

## Note di stile

Riferimento dichiarato alla sigla di *The Morning Show* (Elastic, art direction Hazel Baird):
fondo osso, campiture piatte, campo di pallini, condensato pesante, quattro colori saturi con
ruolo semantico. Il marchio in testata è tutto giallo. Se tocchi lo stile, resta dentro
questo sistema.

## Fonti monitorate

**Primarie** (parlano di rado, ma è la parola di Apple e chiude i rumor invece di aprirne):
Apple Newsroom · Apple Developer

**Redazionali**: 9to5Mac · MacRumors · BGR · Macitynet · iSpazio · Tom's Hardware IT ·
The Verge

**Larghe** (non parlano di Apple: sono la materia prima delle sonde del radar):
Ars Technica · TechCrunch

**AI** (i laboratori quando parlano in prima persona, più chi li segue di mestiere):
OpenAI · Google DeepMind · The Decoder · TechCrunch AI · Ars Technica AI ·
MIT Technology Review AI

> **Anthropic non ha un feed.** Il sito non espone RSS a nessun indirizzo noto: provati
> `news/rss.xml`, `rss.xml`, `feed.xml`, `index.xml`, tutti 404 al 9 agosto 2026. Passa
> dalle sei fonti qui sopra, che la coprono tutte, e dai suoi annunci quando finiscono su
> Hacker News — che è come li ha trovati `missed.py` la prima volta. Se un giorno aprono
> un feed, va aggiunto al `SEED` con `tier: "ai"`.

**Banco** (la concorrenza e chi la prova, per la sezione *Sul banco*): DDay.it · HDblog ·
GSMArena · Android Authority · Andrea Galeazzi (YouTube) · MKBHD (YouTube)

I due canali YouTube passano dal feed Atom pubblico, che non richiede chiave:
`youtube.com/feeds/videos.xml?channel_id=UC…`. L'id del canale si ricava dalla pagina del
canale cercando `channelId` nell'HTML — l'handle `@nome` da solo non basta.

**In panchina**: Wired Italia, dal 9 agosto 2026 — feed fermo al 1° luglio. Si riprova
da sola ogni sette giorni con `--retest`.

L'elenco che comanda è `data/sources.json`; `SEED` in `pipeline/sources.py` serve solo a
ricordare gli indirizzi e a far entrare le fonti nuove. Il candidato italiano più pulito
emerso da `--discover` è Il Post — Tecnologia: poco volume, ma verificato.
