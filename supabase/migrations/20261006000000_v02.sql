-- Isôko v0.2: benchmark run ids, promoter farm visits, refinement-window knowledge entries.
alter table interactions add column if not exists run_id text;
create index if not exists idx_interactions_run on interactions (run_id);

create table if not exists farm_visits (
    id bigserial primary key,
    ts double precision not null,
    promoter_hash text,
    farmer_code text,
    district text,
    crop text,
    issue text,
    diagnosis text,
    notes text
);

create table if not exists kb_extra (
    id text primary key,
    ts double precision not null,
    entry text not null,
    source text,
    active integer not null default 1
);

alter table farm_visits enable row level security;
alter table kb_extra enable row level security;
