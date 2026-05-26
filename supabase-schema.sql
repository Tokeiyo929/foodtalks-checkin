create table if not exists public.checkins (
  user_id uuid not null references auth.users(id) on delete cascade,
  brand_id integer not null,
  checked_at timestamptz not null default now(),
  primary key (user_id, brand_id)
);

alter table public.checkins enable row level security;

drop policy if exists "checkins_select_own" on public.checkins;
create policy "checkins_select_own"
on public.checkins
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "checkins_insert_own" on public.checkins;
create policy "checkins_insert_own"
on public.checkins
for insert
to authenticated
with check (auth.uid() = user_id);

drop policy if exists "checkins_update_own" on public.checkins;
create policy "checkins_update_own"
on public.checkins
for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "checkins_delete_own" on public.checkins;
create policy "checkins_delete_own"
on public.checkins
for delete
to authenticated
using (auth.uid() = user_id);
