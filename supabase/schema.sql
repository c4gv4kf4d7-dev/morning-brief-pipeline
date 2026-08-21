-- =====================================================================
-- The Morning Brief — schema Supabase
--
-- Pensato per convivere dentro un progetto già usato da altre app:
-- tutte le tabelle stanno nello schema public con prefisso "brief_",
-- così non collidono con niente di esistente e non serve toccare le
-- impostazioni del progetto.
--
-- Da incollare nell'SQL Editor ed eseguire una volta sola.
-- =====================================================================

-- ---------------------------------------------------------------------
-- brief_editions: le rassegne. Scritte dal task delle 7:00 con la
-- service key, lette da chiunque sia autenticato.
-- ---------------------------------------------------------------------
create table if not exists public.brief_editions (
  date         date primary key,
  payload      jsonb not null,
  published_at timestamptz not null default now()
);

alter table public.brief_editions enable row level security;

drop policy if exists "brief: edizioni leggibili da autenticati" on public.brief_editions;
create policy "brief: edizioni leggibili da autenticati"
  on public.brief_editions for select
  to authenticated
  using (true);

-- Nessuna policy di insert/update: le scritture passano solo dalla
-- service key, che aggira la RLS. Il task del Mac è l'unico redattore.

-- ---------------------------------------------------------------------
-- brief_marks: stelline, appunti e link allegati, una riga per notizia.
-- La chiave "story" è "YYYY-MM-DD/id-notizia", la stessa usata dall'app.
-- ---------------------------------------------------------------------
create table if not exists public.brief_marks (
  user_id    uuid not null references auth.users(id) on delete cascade,
  story      text not null,
  starred_at timestamptz,
  read_at    timestamptz,
  note       text,
  links      jsonb not null default '[]'::jsonb,
  -- +1 "ci stava", -1 "non ci stava", 0 nessun voto (vedi pipeline/taste.py)
  vote       smallint not null default 0,
  updated_at timestamptz not null default now(),
  primary key (user_id, story)
);

alter table public.brief_marks enable row level security;

drop policy if exists "brief: ognuno vede solo i propri segni" on public.brief_marks;
create policy "brief: ognuno vede solo i propri segni"
  on public.brief_marks for all
  to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create index if not exists brief_marks_updated_idx on public.brief_marks (user_id, updated_at desc);

-- ---------------------------------------------------------------------
-- brief_diary: le voci del diario di lavoro.
-- deleted_at invece della cancellazione vera: serve a propagare
-- l'eliminazione all'altro dispositivo invece di far riapparire la voce.
-- ---------------------------------------------------------------------
create table if not exists public.brief_diary (
  id         text not null,
  user_id    uuid not null references auth.users(id) on delete cascade,
  ts         timestamptz not null,
  text       text not null default '',
  tags       jsonb not null default '[]'::jsonb,
  link       text,
  ref        jsonb,
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  primary key (user_id, id)
);

alter table public.brief_diary enable row level security;

drop policy if exists "brief: ognuno vede solo il proprio diario" on public.brief_diary;
create policy "brief: ognuno vede solo il proprio diario"
  on public.brief_diary for all
  to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create index if not exists brief_diary_updated_idx on public.brief_diary (user_id, updated_at desc);

-- ---------------------------------------------------------------------
-- updated_at automatico: l'app sincronizza chiedendo "cosa è cambiato
-- dopo l'ultima volta", quindi il timestamp non può dipendere dal client.
-- ---------------------------------------------------------------------
create or replace function public.brief_touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists brief_marks_touch on public.brief_marks;
create trigger brief_marks_touch before insert or update on public.brief_marks
  for each row execute function public.brief_touch_updated_at();

drop trigger if exists brief_diary_touch on public.brief_diary;
create trigger brief_diary_touch before insert or update on public.brief_diary
  for each row execute function public.brief_touch_updated_at();
