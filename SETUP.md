# Configurazione Supabase — cosa devi fare tu

**Non serve un progetto nuovo.** Il piano gratuito ne consente due attivi, e tu ne hai già tre.
Il brief va dentro uno di quelli: tutte le sue tabelle hanno il prefisso `brief_` e vivono
nello schema `public` come le altre, quindi non collidono con niente e non richiedono di
toccare nessuna impostazione del progetto ospite.

Scegli tu quale — *gym*, *casa* o *movie*. Tanto vale il più tranquillo dei tre.
Un vantaggio collaterale: appoggiandosi a un progetto già vivo, non rischia la pausa per
inattività che colpisce i progetti free fermi da una settimana.

Sei passi, una decina di minuti. Le cose che richiedono un account o una password le devi fare
tu: io non creo account e non digito credenziali.

Quando hai finito, dimmi "fatto" e faccio partire il primo caricamento.

---

## 1. Crea le tabelle

Apri il progetto che hai scelto → menu laterale **SQL Editor** → **New query**.

Apri `supabase/schema.sql` di questa cartella, copia tutto, incolla, **Run**.

Deve rispondere *Success. No rows returned*. Crea tre tabelle — `brief_editions`,
`brief_marks`, `brief_diary` — con le rispettive regole di sicurezza. Non tocca nient'altro
di quello che c'è già dentro.

---

## 2. Crea il tuo utente

Menu laterale → **Authentication** → **Users**.

Se in quel progetto hai già un utente tuo e ti va bene riusarlo, salta pure: la password è
la stessa. Altrimenti **Add user** → **Create new user**:

- Email: la tua
- Password: scegline una e **salvala nel portachiavi** — è quella che digiterai sull'app,
  su Mac e su iPhone
- Spunta **Auto Confirm User** (altrimenti resta in attesa di una mail di conferma)

Questa è la coppia che userai sui due dispositivi: il "codice condiviso" di cui parlavi, con
le regole di sicurezza vere dietro.

---

## 3. Crea lo spazio per la pagina

Menu laterale → **Storage** → **New bucket**.

- Name: `brief-app` ← nome dedicato, per non accavallarsi a bucket già presenti
- **Public bucket: attivo** ← senza questo la pagina non si apre dal telefono

---

## 4. Passami le due chiavi pubbliche

Menu laterale → **Project Settings** (l'ingranaggio) → **API**.

Copia **Project URL** e la chiave **anon / public**, e scrivile in `supabase/config.json`
(parti da `config.example.json`):

```json
{
  "url": "https://xxxxxxxxxxxx.supabase.co",
  "anon_key": "eyJhbGciOi...",
  "bucket": "brief-app"
}
```

La chiave `anon` è pubblica per definizione: finisce dentro la pagina ed è progettata per
stare lì. Da sola non apre niente — sono le regole di sicurezza sulle tabelle a decidere
chi legge cosa.

---

## 5. Metti al sicuro la chiave privata

Stessa schermata, più in basso: la chiave **service_role**. Questa è segreta e non va mai
dentro la pagina. Serve solo al task delle 7:00 sul tuo Mac per scrivere le edizioni.

Crea il file `.env.local` nella cartella del progetto:

```
SUPABASE_SERVICE_KEY=eyJhbGciOi...
```

Resta sul tuo disco. Non finisce nell'app, non finisce nell'Artifact, non la mando a nessuno.

> Attenzione: la service key di quel progetto vale per **tutto** il progetto, quindi anche per
> le tabelle dell'app che ci abita già. Tienila come tieni una password vera.

---

## 6. Dimmi che è pronto

A quel punto lancio io:

```bash
python3 pipeline/build.py && python3 pipeline/push.py --all && python3 pipeline/upload_app.py
```

Il primo comando ricompila l'app in versione cloud, il secondo carica le edizioni già scritte,
il terzo pubblica la pagina e stampa l'indirizzo definitivo.

---

## Poi, sull'iPhone

Apri l'indirizzo in Safari → tasto Condividi → **Aggiungi a Home**. Diventa un'icona come
un'app, senza barra del browser. Fai il login una volta e resti dentro per mesi.

Gli appunti scritti sull'Artifact: esportali con ↧ prima di passare alla nuova app, poi
reimportali con ↥ da lì. Da quel momento si sincronizzano da soli.

---

## Se un domani vuoi separarlo

Niente di quello che facciamo qui è un vincolo. Il giorno che liberi uno slot, basta rilanciare
`schema.sql` sul progetto nuovo, spostare le tre tabelle con un dump, e cambiare due righe in
`supabase/config.json`. L'app non sa e non gli importa dove sta il database.
