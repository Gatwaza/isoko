# Umujyanama: AI agricultural advisory for Rwanda's smallholder farmers

*Umujyanama* ("the advisor") gives Kinyarwanda-first, grounded farm advice on **any phone**: USSD menus, two-way SMS, and an API for partner apps and for benchmarking. Every answer comes from a curated knowledge base and is returned with its sources. Questions the system cannot answer reliably go to a human extension officer instead of being guessed. A real-time dashboard shows MINAGRI and RAB what farmers are asking, where, and where the knowledge gaps are.

```
 Farmer (feature phone)            Extension officer / partner app        MINAGRI · RAB
   USSD *xxx#   SMS                      REST API  /v1/reports                 Dashboard
       │         │                             │                                  ▲
       ▼         ▼                             ▼                                  │
 ┌──────────────────────────── FastAPI service (single container) ─────────────────────────┐
 │  USSD state machine ─┐                                                                  │
 │  SMS in/out ─────────┼─► Advisory engine ─► language detect (rw/en)                     │
 │  /v1/advisory/query ─┤        │             BM25 retrieval over curated corpus (cited)  │
 │  /v1/chat/completions┘        │             domain gate + score gate ─► escalate        │
 │                               │             open-weight LLM (Ollama / vLLM), optional   │
 │                               │             guardrails: grounded-only, numbers-in-source│
 │                               └──► weather rules (7-day forecast per district)          │
 │  SQLite: profiles, interactions (hashed users), reports, SMS outbox ──► dashboard API   │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
```

## What works today

| Capability | Status |
|---|---|
| USSD menus, Kinyarwanda first with English toggle (crops, pests & diseases, weather, livestock, ask a question, field report, profile) | ✅ Working (Africa's Talking callback format) |
| Full answers delivered by SMS after a USSD session; free-text questions answered by SMS | ✅ Working (sandbox / outbox without credentials) |
| Two-way SMS: farmer texts a question and gets an answer | ✅ `POST /sms/inbound` |
| Personalisation by district and main crop (profile stored per phone number) | ✅ |
| 7-day district weather turned into planting, dry-spell, heavy-rain and heat advice for all 30 districts | ✅ Rule-based, auditable |
| Benchmark API with API keys: native JSON and OpenAI-compatible | ✅ `POST /v1/advisory/query`, `POST /v1/chat/completions` |
| Grounding: answers cite corpus entries; out-of-scope questions escalated, not guessed | ✅ |
| Guardrail: a generated answer is rejected if it contains any number (dose, spacing, interval) that is not in the sources | ✅ |
| Field reports from farmers and promoters, plus automatic forecast alerts, shown on the MINAGRI dashboard | ✅ |
| Dashboard: needs by crop/topic, district, language and channel; escalations (knowledge gaps) | ✅ `/dashboard` |
| Open-source models only, self-hosted (Ollama); runs on CPU | ✅ Llama 3.2 3B tested; Qwen 2.5 (Apache-2.0) also works |
| Single-server Docker deployment for in-country hosting | ✅ `docker compose up` |

## Honest gaps and roadmap

- **Seed knowledge base.** It has 43 bilingual entries compiled from public RAB, FAO, CABI, ILRI, CIP, IITA and NAEB extension guidance. **The Kinyarwanda text is a draft that needs review by native-speaking agronomists.** The retrieval layer is built to swap in the C4IR national corpus (RISA APIs / MCP server) without changing the interface.
- **Kinyarwanda generation is off by default** (`GENERATE_KINYARWANDA=false`). Small open models write unreliable Kinyarwanda, so Kinyarwanda answers use curated text verbatim. Generation will be switched on per model only once it passes the C4IR Kinyarwanda benchmark; the refinement window is when we'd do that, using the 2,000 parallel sentences and 5,000 Q&A pairs.
- **Voice and IVR.** Not built yet. Next step: a Kinyarwanda ASR/TTS integration (open models fine-tuned on the 20h audio-script set) behind an IVR gateway.
- **Image-based pest and disease ID.** Not built yet. Next step: an open vision model behind the same advisory engine, for WhatsApp and extension-agent apps.
- **Weather source.** The prototype uses Open-Meteo; only district coordinates are sent. Production would use Meteo Rwanda feeds through the national corpus.
- **No production usage yet.** This is a new solution. The dashboard demo uses clearly labelled simulated traffic.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
ollama pull llama3.2                                   # optional: enables English generation
API_KEYS=demo-benchmark-key .venv/bin/uvicorn app.main:app --port 8000
```

- USSD simulator: http://localhost:8000/simulator
- Dashboard: http://localhost:8000/dashboard
- API docs: http://localhost:8000/docs

Demo with simulated traffic on the dashboard (clearly bannered):

```bash
DB_PATH=data/demo.db .venv/bin/python scripts/seed_demo.py
DB_PATH=data/demo.db DEMO_MODE=true API_KEYS=demo-benchmark-key .venv/bin/uvicorn app.main:app --port 8000
```

With Docker, on any Linux server in Rwanda:

```bash
cp .env.example .env   # set API_KEYS, DASHBOARD_TOKEN, PHONE_HASH_SALT, Africa's Talking credentials
docker compose up -d && docker compose exec ollama ollama pull llama3.2
```

Africa's Talking: set the USSD callback to `https://<host>/ussd` and the incoming SMS callback to `https://<host>/sms/inbound`.

## Benchmark API

```bash
curl -X POST https://<host>/v1/advisory/query \
  -H "X-API-Key: <key>" -H "Content-Type: application/json" \
  -d '{"question": "Ibigori byanjye bifite nkongwa, nkore iki?", "language": "auto", "district": "Nyagatare"}'
```

The response includes `answer`, `language`, `sources[]` (corpus id, title, provenance, score), `confidence`, `escalated`, `model` and `latency_ms`. The OpenAI-compatible `POST /v1/chat/completions` (Bearer key) lets standard evaluation harnesses call the **whole solution**, not just the model.

Run a Q&A set (JSONL with `question`, optional `reference`, `language`, `expected_source`):

```bash
.venv/bin/python scripts/benchmark.py scripts/sample_eval.jsonl --url http://localhost:8000 --key demo-benchmark-key
```

On our own 28-item sample set (Kinyarwanda and English, including off-topic questions): top-1 source accuracy 100%, off-topic questions correctly escalated, median latency about 1s with Llama 3.2 on a laptop CPU. The sample set was written by the team, so it is a smoke test, not an independent benchmark.

## Data protection (Law N° 058/2021)

- Phone numbers are stored only in `profiles`, which is needed to send SMS. All analytics use a salted SHA-256 hash.
- No personal data leaves the host. The weather lookup sends district coordinates only. The LLM runs locally.
- The dashboard is protected by `DASHBOARD_TOKEN`, and the API by per-partner keys.

## Layout

```
app/main.py        HTTP routes: USSD, SMS, API, dashboard
app/ussd.py        USSD state machine (stateless; rebuilt from the gateway's input path)
app/advisor.py     language detection → retrieval → generation → guardrails → logging
app/retrieval.py   BM25 + domain gate over the corpus
app/llm.py         Ollama / OpenAI-compatible clients (open, self-hosted runtimes only)
app/weather.py     district forecasts → rule-based advice and alerts
app/kb/corpus.json bilingual seed knowledge base (with sources)
scripts/           benchmark runner, sample eval set, demo seeder
tests/             pytest suite
```
