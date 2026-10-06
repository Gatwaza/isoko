# Isôko: AI agricultural advisory for Rwanda's smallholder farmers

*Isôko* (Kinyarwanda for "source", as in a spring, and also "market") is a Kinyarwanda-first farm advisor:

- **Farmers** speak to it in Kinyarwanda and hear the answer, send a photo of a sick crop, or use USSD and SMS on any phone.
- **Farmer promoters and extension officers** get a field toolkit: a photo second opinion, farm-visit records, a quick refresher and outbreak reports.
- **MINAGRI, RAB and Meteo Rwanda** see what farmers need, where, in real time.

Every answer comes from a curated knowledge base and is returned with its sources. When the system is not sure, it escalates to a human instead of guessing.

Isôko grew from a prototype we built in July 2026 during our crop-yield prediction and simulation research (Nyagatare, RAB and Meteo Rwanda data). See [docs/RESEARCH.md](docs/RESEARCH.md) for the evidence behind each design choice.

```
 Farmer phone                 Promoter / extension         MINAGRI · RAB         C4IR benchmark
 1 voice  2 photo  3 USSD     /promoter                    /dashboard            /v1/* API
     │       │       │            │                            ▲                    │
     ▼       ▼       ▼            ▼                            │                    ▼
 ┌───────────────────────────── app/ (FastAPI) ─────────────────────────────────────────────┐
 │ channels: USSD · SMS · voice · photo · WhatsApp webhook · REST + OpenAI-compatible API   │
 │ advisory engine: language id → Kinyarwanda morphology-aware BM25 → scope gate            │
 │                  → open LLM (Ollama/vLLM) → figure-check guardrail → cited answer        │
 │ weather rules (30 districts) · Postgres/SQLite · benchmark runs · refinement import       │
 └───────────────┬──────────────────────────────────────────────────────────────────────────┘
                 │ X-ML-Token
 ┌───────────────▼─────── ml_service/ (GPU or CPU) ──────────────────────────────────────────┐
 │ /asr Kinyarwanda speech recognition (Whisper-small rw) · /tts MMS-TTS + number verbaliser │
 │ /translate NLLB-200 (en↔rw) · /diagnose crop-disease classifiers (beans, cassava, general) │
 └───────────────────────────────────────────────────────────────────────────────────────────┘
```

## Measured results (our own test sets; C4IR's benchmark is the real test)

| Capability | Result | Test data |
|---|---|---|
| Advisory answers, fully correct | **90.3%** (Gemma 3 4B alone: 12.9%) | 70 held-out questions, 49 EN / 21 RW |
| Off-topic, market and credit questions handled safely | **100%** (Gemma alone: 25%) | 8 off-topic questions |
| Answers with figures not in any source | **3.2%** (Gemma alone: 56.5%) | same |
| Fresh Kinyarwanda questions (development set) | 14/20 → **20/20** with v0.2 morphology | 20 questions, used for tuning |
| Kinyarwanda speech recognition | **6.7% character error** (23.5% WER) | 80 real recordings |
| Spoken-answer intelligibility | 43.1% → **9.6%** error with our number verbaliser | 20 advisory sentences, TTS → ASR |
| Spoken questions answered correctly, end to end | **71.4%** (typed: 85.7%) | 21 Kinyarwanda questions |
| EN→RW translation, chrF | **56.4** NLLB-200 (Gemma 3: 21.1) | 60 agriculture sentence pairs |
| Photo diagnosis accuracy | beans **100%**, cassava **82.5%** | 40 + 40 East African field photos |
| Adversarial and robustness tests | see `eval/results/threat_report.json` | auth, injection, prompt injection, fuzzing, load |

All harnesses are in `eval/`: `run_eval.py` (Q&A), `asr_eval.py`, `speech_mt_eval.py`, `vision_eval.py`, `voice_e2e_eval.py` and `threat_tests.py`. Results are in `eval/results/` (v0.1 baseline in `eval/results/v0.1/`) and rendered at `/evaluation`.

Caveats: the test sets are small and written or selected by the team. The development set was used for tuning. Translation pairs come from the [Digital Umuganda corpus](https://huggingface.co/datasets/DigitalUmuganda/kinyarwanda-english-machine-translation-dataset) (CC-BY-4.0). Bean photos come from [AI-Lab-Makerere/beans](https://huggingface.co/datasets/AI-Lab-Makerere/beans) and cassava photos from the iCassava test split.

## Benchmark access (C4IR)

Programmatic API access is ready for both rounds. Each C4IR dataset maps to an endpoint:

- Q&A pairs → `POST /v1/advisory/query` or `/v1/advisory/batch`
- EN–RW sentence pairs → `POST /v1/translate`
- Audio–script pairs → `POST /v1/asr`

Runs tagged with `X-Benchmark-Run` are deterministic and retrievable. `/v1/system` pins component versions, and refinement data can be imported through an admin API. See [docs/BENCHMARK.md](docs/BENCHMARK.md).

## Run it

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
python3 -m venv .venv-ml && .venv-ml/bin/python -m pip install -r ml_service/requirements.txt   # voice + photos
ollama pull gemma3:4b
scripts/demo.sh        # app + model service + public Cloudflare link
```

Pages: `/simulator` (farmer phone), `/promoter`, `/dashboard`, `/evaluation`, `/compare`, `/docs`. They default to Kinyarwanda, with an English toggle.

Hosted text service: **https://isoko-agri.vercel.app**. It runs on Vercel (FastAPI, region `fra1`) with Supabase Postgres (migrations in `supabase/migrations/`, RLS on, no public policies). Voice and photo features need the model service: set `ML_SERVICE_URL` and `ML_TOKEN`.

Production runs on Rwandan infrastructure: Docker for `app/` (see `Dockerfile` and `docker-compose.yml`) and `ml_service/` (its own `Dockerfile`), with Postgres in a local data centre. Nothing depends on Vercel, Supabase or any one model.

> **Data residency.** The Vercel and Supabase demo is hosted in the EU and holds simulated data only. It must not hold real farmer data without NCSA authorisation (Law N° 058/2021).

## Models and licences

| Role | Model | Licence |
|---|---|---|
| Advice generation | Gemma 3 4B (Ollama) | Gemma terms (open weights) |
| Speech recognition | DigitalUmuganda/whisper_small_kinyarwanda (fallback: badrex/w2v-bert-2.0-kinyarwanda-asr) | not stated on card (fallback CC-BY-4.0) |
| Speech synthesis | facebook/mms-tts-kin + `ml_service/kin_text.py` | CC-BY-NC-4.0 |
| Translation | facebook/nllb-200-distilled-600M | CC-BY-NC-4.0 |
| Photos | ayoubkirouane/VIT_Beans_Leaf_Disease_Classifier, siddharth963/vit-base-…-cassava (Apache-2.0), linkanjarad/mobilenet_v2 plant disease | see model cards |

The non-commercial and unstated licences are disclosed. We plan to replace them with our own permissively licensed models trained on C4IR's refinement data.

## Security

`eval/threat_tests.py` covers authentication bypass, SQL injection, prompt injection, harmful-request refusal, stored XSS, oversized payloads, USSD fuzzing, rate limiting (HTTP 429), path traversal, webhook spoofing and concurrent load. API keys are rate-limited per key, demo endpoints per IP. Responses carry `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. Phone numbers are salted-hashed for analytics.

## Name and character set

USSD and SMS screens write **Isoko**, because "ô" is outside the GSM 7-bit alphabet (it would force 70-character UCS-2 SMS).

## Layout

```
app/                 FastAPI app: main.py (pages, USSD, SMS, v1 API), api_v2.py (voice, photo, batch, runs,
                     promoter, refinement import, WhatsApp), advisor.py, retrieval.py, ml.py, db.py, ussd.py, weather.py
app/kb/corpus.json   bilingual knowledge base with sources
app/static/          farmer phone, promoter portal, dashboard, evaluation, comparison (i18n.js: Kinyarwanda default)
ml_service/          speech, translation and photo model service (Dockerfile for any GPU/CPU host)
eval/                test sets, harnesses and results
docs/                RESEARCH.md, BENCHMARK.md
scripts/             demo.sh (Demo Day launcher), seed_demo.py, benchmark.py (API client)
supabase/            Postgres migrations
```
