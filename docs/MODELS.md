# Models, licences and replacement plan

Every model is selected by configuration (environment variables), so swapping one means changing the configuration and rerunning the evaluation (`eval/`). Licences are taken from the model cards at the time of selection. **Verify them before production use.**

| Role | Current model | Licence | Our measurement | Permissive alternative (measured) | Plan |
|---|---|---|---|---|---|
| Advice generation | Gemma 3 4B (`LLM_MODEL=gemma3:4b`) | Gemma Terms of Use (open weights, not OSI) | 90.3% fully correct inside Isôko | Qwen 2.5 (Apache-2.0); see `eval/results` | Keep the guardrails model-agnostic; evaluate Apache-2.0 models each round |
| Speech recognition (GPU) | DigitalUmuganda/whisper_small_kinyarwanda | not stated on model card | CER 6.7%, WER 23.5% (80 clips) | badrex/w2v-bert-2.0-kinyarwanda-asr (CC-BY-4.0): CER 10.4% | Confirm licence with Digital Umuganda; fine-tune our own on C4IR's 20 h audio |
| Speech recognition (CPU) | badrex/w2v-bert-2.0-kinyarwanda-asr | CC-BY-4.0 | CER 10.4%, 1.7 s per clip on CPU | n/a | Default for CPU-only hosts |
| Speech synthesis | facebook/mms-tts-kin + `kin_text` verbaliser | CC-BY-NC-4.0 | round-trip CER 9.6% (43.1% without verbaliser) | DigitalUmuganda/KinyarwandaTTS_female_voice (CC-BY-SA-4.0, YourTTS / Coqui) | Integrate the CC-BY-SA voice or train our own on C4IR audio |
| Translation | facebook/nllb-200-distilled-600M | CC-BY-NC-4.0 | chrF 56.4 EN→RW, 49.5 RW→EN | Helsinki-NLP/opus-mt-en-rw and opus-mt-rw-en (Apache-2.0): chrF 45.1 / 38.1 | Switch to OPUS-MT if non-commercial terms are an issue; fine-tune on C4IR's 2,000 pairs |
| Bean diseases | ayoubkirouane/VIT_Beans_Leaf_Disease_Classifier | see card | 100% (40 field photos) | n/a | Retrain on Rwandan field photos |
| Cassava diseases | siddharth963/vit-base-patch16-224-in21k-finetuned-cassava | Apache-2.0 | 82.5% (40 field photos); 86.1% when confident | n/a | Retrain on Rwandan field photos |
| Maize / potato / other | linkanjarad/mobilenet_v2_1.0_224-plant-disease-identification | see card | not field-tested (PlantVillage lab images) | n/a | Field evaluation before relying on it; low-confidence results escalate |

## Rejected or unusable candidates (and why)

- **mbazaNLP/Whisper-Small-Kinyarwanda:** gated; access not granted at evaluation time.
- **louislu9911 cassava ViT:** the published weights carry ImageNet labels (goldfish, shark…), not cassava classes.
- **nexusbert/resnet50-cassava-finetuned:** 47.5% on field photos.
- **Hume AI (voice):** no Kinyarwanda support; closed and hosted abroad, against C4IR's open and local principles.
- **Generic LLMs for Kinyarwanda generation:** chrF 16–21 EN→RW; Kinyarwanda answers use reviewed text until a model passes evaluation (`GENERATE_KINYARWANDA=false`).

## Swapping a model

```bash
# e.g. move translation to Apache-2.0 OPUS-MT
MT_MODEL=opus ...                                  # Apache-2.0 OPUS-MT (en<->rw); ml_service reads MT_MODEL, ASR_MODEL, TTS_MODEL, *_MODEL
.venv-ml/bin/python eval/speech_mt_eval.py opus    # measure before switching
```
