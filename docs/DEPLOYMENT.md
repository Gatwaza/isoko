# Deploying Isôko on Rwandan infrastructure

One server, one command, no dependency on Vercel, Supabase or any external model API.

```bash
git clone https://github.com/Gatwaza/isoko && cd isoko
cp .env.example .env        # set API_KEYS, ADMIN_KEYS, ML_TOKEN, PHONE_HASH_SALT, POSTGRES_PASSWORD
docker compose up -d        # db (Postgres 16) + api + ml (speech/vision) + ollama (LLM)
docker compose exec ollama ollama pull gemma3:4b
curl localhost:8000/health && curl localhost:8000/v1/channels/status
```

The database schema is applied automatically from `supabase/migrations/` (plain SQL). The first start of `ml` downloads the model weights (about 4 GB) into the `isoko-models` volume. For air-gapped hosts, mirror the weights first and point `HF_HOME` at the mirror.

## Hardware

| Profile | Spec | What runs where | Expected latency |
|---|---|---|---|
| **CPU-only** (minimum) | 8 vCPU, 32 GB RAM, 60 GB SSD | Gemma 3 4B on CPU; ASR w2v-BERT 2.0; TTS, NLLB and vision on CPU | text answer 1–4 s (curated answers <0.1 s); ASR ~1.7 s per clip; photo ~0.1 s |
| **Single GPU** (recommended) | 8 vCPU, 32 GB RAM, 1× 16–24 GB GPU (T4/L4/A10), 80 GB SSD | Gemma on GPU (Ollama or vLLM); Whisper-small rw ASR on GPU (`ASR_MODEL=DigitalUmuganda/whisper_small_kinyarwanda`, `ML_DEVICE=cuda`) | text answer ~1 s; ASR <1 s per clip |
| **Demo laptop** | Apple M1/M2, 16–32 GB | `scripts/demo.sh` (Metal GPU) | as GPU profile |

Throughput: `LLM_MAX_CONCURRENCY` caps simultaneous generations (default 2). Extra live requests get the curated answer immediately; tagged benchmark runs wait for a slot to stay deterministic. Large evaluations should use the async jobs API (`POST /v1/jobs`).

## Network and data

- **Inbound:** HTTPS to `api` (port 8000) behind your reverse proxy or load balancer. The telco aggregator calls `POST /ussd` and `POST /sms/inbound`.
- **Outbound at runtime:** only the weather API, which receives district coordinates, never farmer data. The telco or WhatsApp gateway is contacted only when configured. `tests/test_egress.py` enforces this allowlist and fails if a phone number appears in any outbound request.
- Phone numbers are stored only in `profiles` (needed to reply by SMS). Analytics use salted hashes. Interactions are deleted after `RETENTION_DAYS`.
- Backups: the `isoko-db` volume (`pg_dump`). Models and knowledge are reproducible from Git and model ids.

## Updating

```bash
git pull && docker compose build && docker compose up -d
docker compose exec db psql -U isoko -d isoko -f /docker-entrypoint-initdb.d/<new migration>.sql   # if any
```

Check `GET /v1/system` after each update: it reports the commit, corpus fingerprint and model ids, so benchmark rounds can be tied to an exact build.
