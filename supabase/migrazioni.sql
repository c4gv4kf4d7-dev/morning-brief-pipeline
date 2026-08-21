-- ---------------------------------------------------------------------
-- Migrazioni da lanciare a mano nell'editor SQL di Supabase, in ordine.
-- Sono tutte idempotenti: rilanciarle non fa danno.
-- ---------------------------------------------------------------------

-- 2026-08-09 · il pollice
-- Un voto per notizia e per voce del radar: +1 "ci stava", -1 "non ci stava",
-- 0 nessun voto. Serve a tarare la selezione del mattino dopo (pipeline/taste.py).
alter table public.brief_marks
  add column if not exists vote smallint not null default 0;

-- niente politiche nuove: la riga e' gia' protetta da quelle di brief_marks,
-- che valgono per tutte le colonne.
