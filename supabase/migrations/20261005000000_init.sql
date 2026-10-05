-- Umujyanama schema. Timestamps are epoch seconds (double precision) to match the SQLite backend.
-- RLS is enabled with no policies: the anon/authenticated REST roles get no access; only the
-- server (direct Postgres connection) can read or write farmer data.

create table if not exists profiles (
    phone text primary key,
    lang text not null default 'rw',
    district text,
    main_crop text,
    created_at double precision not null,
    updated_at double precision not null
);

create table if not exists interactions (
    id bigserial primary key,
    ts double precision not null,
    channel text not null,
    user_hash text,
    lang text,
    district text,
    category text,
    crop text,
    topic text,
    query text,
    answer text,
    sources text,
    confidence double precision,
    escalated integer not null default 0,
    latency_ms integer,
    model text
);

create table if not exists reports (
    id bigserial primary key,
    ts double precision not null,
    user_hash text,
    district text,
    issue text not null,
    detail text,
    channel text not null
);

create table if not exists sms_outbox (
    id bigserial primary key,
    ts double precision not null,
    phone text not null,
    message text not null,
    status text not null
);

create index if not exists idx_interactions_ts on interactions (ts);
create index if not exists idx_reports_ts on reports (ts);
create index if not exists idx_sms_outbox_phone on sms_outbox (phone, id);

alter table profiles enable row level security;
alter table interactions enable row level security;
alter table reports enable row level security;
alter table sms_outbox enable row level security;
