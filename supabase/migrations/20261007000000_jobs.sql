-- Isôko v0.3: asynchronous benchmark jobs.
create table if not exists jobs (
    id text primary key,
    ts double precision not null,
    key_hash text not null,
    run_id text,
    status text not null,
    total integer not null,
    done integer not null default 0,
    finished_ts double precision
);
create table if not exists job_items (
    job_id text not null references jobs (id) on delete cascade,
    idx integer not null,
    item text not null,
    result text,
    primary key (job_id, idx)
);
alter table jobs enable row level security;
alter table job_items enable row level security;
