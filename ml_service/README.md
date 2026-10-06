---
title: Isoko Models
emoji: 🌱
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
short_description: Kinyarwanda speech and crop-disease models for Isôko
---

# Isôko model service

Kinyarwanda speech recognition and synthesis, crop-disease photo diagnosis and EN↔RW translation for the
[Isôko](https://github.com/Gatwaza/isoko) agricultural advisory platform. Open models, CPU-only.

| Endpoint | Model | Licence |
|---|---|---|
| `POST /asr` | badrex/w2v-bert-2.0-kinyarwanda-asr | CC-BY-4.0 |
| `POST /tts` | facebook/mms-tts-kin | CC-BY-NC-4.0 |
| `POST /translate` | facebook/nllb-200-distilled-600M | CC-BY-NC-4.0 |
| `POST /diagnose` | crop-specific ViT / MobileNet classifiers | see each model card |

Requests need the `X-ML-Token` header. Demo hosting only: production runs on Rwandan infrastructure.
