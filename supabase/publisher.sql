-- =====================================================================
-- The Morning Brief — utenza di pubblicazione e diario delle esecuzioni
--
-- La routine gira su infrastruttura Anthropic e non ha un posto sicuro
-- dove tenere un segreto: le sue credenziali stanno nel prompt. Per
-- questo non usa la service key, che aprirebbe l'intero progetto, ma
-- un'utenza che sa fare due cose sole: scrivere le edizioni e annotare
-- com'è andata la corsa.
--
-- Non può leggere brief_marks né brief_diary — appunti e diario restano
-- visibili solo a te — e non vede le tabelle dell'altra app che convive
-- in questo progetto.
--
-- Utenza: brief-publisher@morningbrief.local
-- (creata in Authentication -> Users, con Auto Confirm attivo)
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Permesso di scrivere le edizioni, solo per quell'utenza.
--    La lettura resta com'era: la policy creata con schema.sql vale
--    per chiunque sia autenticato, quindi per te.
-- ---------------------------------------------------------------------
drop policy if exists "brief: il publisher pubblica le edizioni" on public.brief_editions;
create policy "brief: il publisher pubblica le edizioni"
  on public.brief_editions for all
  to authenticated
  using      ((auth.jwt() ->> 'email') = 'brief-publisher@morningbrief.local')
  with check ((auth.jwt() ->> 'email') = 'brief-publisher@morningbrief.local');

-- ---------------------------------------------------------------------
-- 2. Diario delle esecuzioni.
--    Serve a vedere ogni mattina dove si è fermata la routine senza
--    dover aprire interfacce: scrive qui cosa ha fatto e cosa è fallito.
-- ---------------------------------------------------------------------
create table if not exists public.brief_runs (
  id         bigserial primary key,
  ran_at     timestamptz not null default now(),
  ok         boolean not null,
  step       text,
  articles   int,
  selected   int,
  note       text
);

alter table public.brief_runs enable row level security;

drop policy if exists "brief: il publisher annota le corse" on public.brief_runs;
create policy "brief: il publisher annota le corse"
  on public.brief_runs for insert
  to authenticated
  with check ((auth.jwt() ->> 'email') = 'brief-publisher@morningbrief.local');

drop policy if exists "brief: le corse sono leggibili da autenticati" on public.brief_runs;
create policy "brief: le corse sono leggibili da autenticati"
  on public.brief_runs for select
  to authenticated
  using (true);

-- ---------------------------------------------------------------------
-- 3. Verifica: elenca le regole attive sulle tabelle del brief.
-- ---------------------------------------------------------------------
select tablename, policyname, cmd
from pg_policies
where schemaname = 'public'
  and tablename like 'brief\_%'
order by tablename, policyname;
