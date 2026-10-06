# Research foundations

Isôko grew from an earlier prototype we built in July 2026 during our applied research on **crop-yield
prediction and simulation** in Nyagatare District, which used RAB field-trial data and Meteo Rwanda climate
records. That work taught us how Rwandan agronomic data behaves: it is seasonal (A/B/C), local, sparse and
often in Kinyarwanda. We then rebuilt the platform as a general advisory engine whose knowledge, models and
channels can be swapped to fit varying agricultural constraints. Every design choice below rests on published
evidence or on our own measurements in `eval/`.

## 1. Why phone-based, voice-first advice

- Digital extension reaches farmers at a fraction of the cost of in-person visits, and it shifts practices when the
  advice is specific and actionable (Fabregas, Kremer & Schilbach, 2019).
- Voice-based advisory over basic phones (Avaaj Otalo, India) increased the adoption of recommended inputs and
  spread through farmer networks (Cole & Fernando, 2021). Older farmers with feature phones, which is the C4IR
  primary user, need voice and USSD/SMS rather than app-only channels.
- Rwanda's Twigire Muhinzi model already works through farmer promoters, so Isôko is built to **multiply**
  promoters (a second-opinion photo tool, visit records, escalation) rather than bypass them.

## 2. Why retrieval-grounded generation

- Retrieval-augmented generation reduces unsupported content by conditioning a generator on retrieved passages
  (Lewis et al., 2020). We use BM25 (Robertson & Zaragoza, 2009) because it is transparent and auditable, and it
  runs on one server.
- Our evaluation shows why grounding matters: the same open model (Gemma 3 4B) answered **12.9%** of farmer questions
  fully correctly on its own, versus **90%+** inside Isôko. 56% of its standalone answers contained figures (doses,
  spacings) found in no validated source (`eval/results/v0.1`).
- Kinyarwanda morphology (subject/tense/object prefixes + root) defeats keyword matching. Isôko v0.2 matches
  conjugated verbs to their infinitive roots (gu-/ku- + root), which raised our Kinyarwanda development-set
  accuracy from 14/20 to 19/20.

## 3. Kinyarwanda speech and translation

- Massively multilingual speech models made Kinyarwanda recognition and synthesis feasible: MMS (Pratap et al., 2023),
  Whisper (Radford et al., 2023) and w2v-BERT 2.0 (Seamless Communication, 2023), fine-tuned on Kinyarwanda data such
  as Common Voice (Ardila et al., 2020), which Rwandan volunteers made one of its largest languages.
- We **measured** the candidates on 80 real Kinyarwanda recordings instead of trusting model cards:
  Digital Umuganda's Whisper-small fine-tune reached **6.7% character error** (23.5% WER); w2v-BERT 2.0 reached 10.4%
  (and is 5× faster on CPU). See `eval/results/asr_results.json`.
- Speech synthesis models drop digits and units, so "cm 75" is spoken as "cm". Isôko verbalises numbers, ranges and
  units in Kinyarwanda before synthesis (`ml_service/kin_text.py`), because a dose that cannot be heard is no advice
  at all.
- Machine translation: NLLB-200 (NLLB Team, 2022) is measured against general LLMs on agricultural sentence pairs
  with chrF (Popović, 2015).

## 4. Photo diagnosis

- Deep CNNs reach very high accuracy on lab images of diseased leaves (Mohanty, Hughes & Salathé, 2016, on PlantVillage;
  Hughes & Salathé, 2015) but **drop sharply on field photos**. We therefore test only on field photos from East Africa:
  the Makerere AI Lab bean dataset and the iCassava challenge set (Mwebaze et al., 2019).
- Low-confidence predictions are never presented as a diagnosis: they are escalated to an extension officer.

## 5. Rwandan agronomic context we build on

- Crop yield gaps in Rwanda are driven by rainfall, soil nutrients and management (Bucagu et al., 2020); machine learning
  predicts maize, potato and rice yields from local data (Kuradusenge et al., 2023; Mugemangango et al., 2024);
  data-driven crop and fertiliser recommendation is feasible in Rwanda (Musanase et al., 2023).
- Our corpus encodes national programmes and practices: seasons A/B/C, Smart Nkunganire input subsidies, Twigire
  Muhinzi, Kirabiranya (BXW) control, marshland rice, liming of acidic soils and East Coast Fever prevention.

## 6. From research to our own infrastructure

Today Isôko uses the best measured open models. Our roadmap is to train **our own** Kinyarwanda models on Rwandan
infrastructure: C4IR's 20 h audio-script set and 2,000 EN–RW sentence pairs for permissively licensed speech and
translation models, and the 5,000 Q&A pairs and national corpus for retrieval and evaluation. Every refinement is
measured on the same harness: baseline, then refinement, then final.

## References

- Ardila, R., et al. (2020). Common Voice: A massively-multilingual speech corpus. *LREC 2020*.
- Bucagu, C., et al. (2020). Determining and managing maize yield gaps in Rwanda. *Food Security, 12*(4), 879–893.
- Cole, S. A., & Fernando, A. N. (2021). Mobile-izing agricultural advice: Technology adoption, diffusion, and sustainability. *The Economic Journal, 131*(633), 192–219.
- Fabregas, R., Kremer, M., & Schilbach, F. (2019). Realizing the potential of digital development: The case of agricultural advice. *Science, 366*(6471).
- Hughes, D. P., & Salathé, M. (2015). An open access repository of images on plant health to enable the development of mobile disease diagnostics. *arXiv:1511.08060*.
- Kuradusenge, M., et al. (2023). Crop yield prediction using machine learning models: Case of Irish potato and maize. *Agriculture, 13*(1), 225.
- Lewis, P., et al. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. *NeurIPS 2020*.
- Mohanty, S. P., Hughes, D. P., & Salathé, M. (2016). Using deep learning for image-based plant disease detection. *Frontiers in Plant Science, 7*, 1419.
- Mugemangango, C., et al. (2024). Comparative analysis of machine learning models for predicting rice yield in Rwanda. *Research on World Agricultural Economy, 5*(4).
- Musanase, C., et al. (2023). Data-driven analysis and machine learning-based crop and fertilizer recommendation system. *Agriculture, 13*(11), 2141.
- Mwebaze, E., et al. (2019). iCassava 2019 fine-grained visual categorization challenge. *arXiv:1908.02900*.
- NLLB Team (2022). No Language Left Behind: Scaling human-centered machine translation. *arXiv:2207.04672*.
- Popović, M. (2015). chrF: Character n-gram F-score for automatic MT evaluation. *WMT 2015*.
- Pratap, V., et al. (2023). Scaling speech technology to 1,000+ languages. *arXiv:2305.13516*.
- Radford, A., et al. (2023). Robust speech recognition via large-scale weak supervision. *ICML 2023*.
- Robertson, S., & Zaragoza, H. (2009). The probabilistic relevance framework: BM25 and beyond. *Foundations and Trends in Information Retrieval, 3*(4).
- Seamless Communication (2023). Seamless: Multilingual expressive and streaming speech translation. *arXiv:2312.05187*.
