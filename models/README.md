# Trained models (Isôko)

Our own trained models, e.g. the crop-yield prediction models from the July 2026 research prototype
(Nyagatare, RAB field trials + Meteo Rwanda climate data).

- Put the files in `models/yield/` (`.pkl`, `.joblib`, `.json`, plus any scaler or encoder files and the
  feature list they need).
- Run `scripts/register_models.py`: it fingerprints every file (SHA-256), records framework versions and
  input features in `models/MANIFEST.json`, and can upload everything to a **private Hugging Face model repo**
  so the models live somewhere other than one laptop or Drive.
- Weight files are git-ignored: the public GitHub repo carries only the manifest.

**Security:** a pickle file runs code when it is loaded. Only load files you produced yourself; the loader
refuses any file whose SHA-256 does not match the manifest.
