-- Isôko v0.3: USSD consent timestamp.
alter table profiles add column if not exists consented_at double precision;
alter table profiles add column if not exists consent_session text;
