# Isôko: programmatic access for the C4IR benchmark

Programmatic API access is available now, for both rounds (baseline and final) and the refinement window between them.

## Access

| | |
|---|---|
| Base URL (text advisory, always on) | `https://isoko-agri.vercel.app` |
| Base URL (full system incl. speech and photos) | issued to C4IR on request (GPU model host) |
| Authentication | `X-API-Key: <key>` or `Authorization: Bearer <key>`; one private key per evaluator |
| Interactive reference | `GET /docs` (OpenAPI) |
| Limits | 120 requests/minute per key (HTTP 429 + `Retry-After` when exceeded); raised on request for bulk runs |

## Each C4IR dataset maps to an endpoint

| C4IR benchmark data | Endpoint | Input → output |
|---|---|---|
| 5,000 agriculture Q&A pairs | `POST /v1/jobs` (async, ≤5,000 items; poll `GET /v1/jobs/{id}`), `POST /v1/advisory/query`, `POST /v1/advisory/batch` (≤50 items, synchronous), `POST /v1/chat/completions` (OpenAI-compatible) | question (rw/en) → answer, cited sources, confidence, escalation flag, latency |
| 2,000 EN–RW sentence pairs | `POST /v1/translate` | `{"text", "source": "en"|"rw", "target"}` → translation |
| 20 h audio–script pairs | `POST /v1/asr` | audio (wav/ogg/webm/mp3) → Kinyarwanda transcript |
| End-to-end voice (optional) | `POST /v1/voice/ask` | spoken question → transcript, answer, spoken answer (base64 WAV) |
| Photos (optional) | `POST /v1/diagnose` | crop photo + crop → disease, confidence, advice, source |

## Reproducible, comparable runs

- **Tag a run:** send `X-Benchmark-Run: <your-run-id>` with each request. Tagged requests use deterministic generation
  (temperature 0, fixed seed), are stored with the run id, and send no SMS.
- **Retrieve a run:** `GET /v1/benchmark/runs/<run-id>` returns every question, answer, source, latency and model for
  your audit.
- **Large runs:** submit all items to `POST /v1/jobs` (returns `job_id` immediately), then poll `GET /v1/jobs/{job_id}?offset=&limit=` for progress and paged results. No request has to stay open for the whole run.
- **Determinism, verified:** `scripts/determinism_check.py` submits the same 500 questions as two tagged runs and compares every answer and source (result in `eval/results/determinism.json`).
- **Channel status:** `GET /v1/channels/status` states which channels are live and which are simulated (USSD, SMS, voice, photo, WhatsApp, weather).
- **Pin versions:** every advisory response includes a `system` block (application version, git commit, corpus version, size
  and SHA-256 fingerprint, LLM and speech/vision model ids); `GET /v1/system` returns the same. The baseline and final rounds can be compared component by component.
- **Refinement window:** `scripts/import_c4ir.py` validates the schema, removes duplicates, freezes a 20% holdout
  (never imported or tuned on, so improvement claims are honest), and imports the rest through
  `POST /v1/admin/knowledge`. Entries are live within a minute and change the corpus fingerprint.
  `eval/finetune_asr.py` fine-tunes Kinyarwanda ASR on the audio set with a before/after CER/WER report.
- **Regression gates:** CI (`.github/workflows/ci.yml`) blocks changes that lower accuracy, safety or Kinyarwanda
  retrieval below the baseline, or that add outbound calls outside the allowlist.

## Example

```bash
curl -s https://isoko-agri.vercel.app/v1/advisory/query \
  -H "X-API-Key: $KEY" -H "X-Benchmark-Run: c4ir-baseline-01" -H "Content-Type: application/json" \
  -d '{"question": "Ibigori byanjye bifite nkongwa, nkore iki?", "language": "auto"}'
```

## Our own baseline measurements (to be superseded by C4IR's)

| Capability | Result | Data |
|---|---|---|
| Q&A, fully correct (Isôko + Gemma 3 4B) | see `eval/results` (v0.1 → v0.2) | 70 held-out questions, team-written |
| Kinyarwanda ASR, character error | 6.7% (Whisper-small rw), 10.4% (w2v-BERT 2.0) | 80 real recordings |
| EN→RW translation, chrF | see `eval/results/speech_mt_results.json` | 60 agriculture sentence pairs, Digital Umuganda corpus |
| Photo diagnosis accuracy | see `eval/results/vision_results.json` | East African field photos (beans, cassava) |
| Robustness | see `eval/results/threat_report.json` | adversarial suite: auth, injection, prompt injection, fuzzing, load |

All harnesses are in `eval/` and run against any Isôko deployment.

## Availability and data

- The text advisory API runs on serverless hosting (always on). Speech, photo and translation models run on a GPU host;
  for the benchmark period we will agree availability windows with C4IR, and production moves to Rwandan infrastructure.
- Benchmark data is used only for evaluation and the refinement window, is never used to train third-party models, and
  is deleted on request.

Contact: Jean Robert Gatwaza · gatwazarobert177@gmail.com · +250 788 494 219
