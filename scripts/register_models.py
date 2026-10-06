"""Register our own trained models: fingerprint, describe, and optionally back up to a private HF repo.

    .venv-ml/bin/python scripts/register_models.py                       # write models/MANIFEST.json
    .venv-ml/bin/python scripts/register_models.py --upload Jeanrobert/isoko-yield-models   # + private backup

Pickle runs code on load, so only register files you trained yourself. Loading is done in a separate
`inspect` step that you trigger explicitly with --inspect.
"""
import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
EXTS = {".pkl", ".joblib", ".json", ".onnx", ".csv", ".txt", ".h5", ".keras", ".pt", ".safetensors"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def describe(p: Path) -> dict:
    """Load a trusted pickle/joblib and report what it is (type, features, sklearn version)."""
    import joblib
    obj = joblib.load(p)
    info = {"type": f"{type(obj).__module__}.{type(obj).__name__}"}
    for attr in ("feature_names_in_", "n_features_in_", "classes_", "n_estimators", "_sklearn_version"):
        if hasattr(obj, attr):
            v = getattr(obj, attr)
            info[attr.strip("_")] = v.tolist() if hasattr(v, "tolist") else v
    if hasattr(obj, "steps"):
        info["pipeline_steps"] = [name for name, _ in obj.steps]
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true", help="load each pickle (trusted files only) to record its schema")
    ap.add_argument("--upload", metavar="REPO_ID", help="back up to a private Hugging Face model repo")
    a = ap.parse_args()
    files = sorted(p for p in MODELS.rglob("*") if p.is_file() and p.suffix.lower() in EXTS and p.name != "MANIFEST.json")
    if not files:
        sys.exit(f"No model files found under {MODELS}. Copy them into models/yield/ first.")
    entries = []
    for p in files:
        e = {"path": str(p.relative_to(ROOT)), "bytes": p.stat().st_size, "sha256": sha256(p)}
        if a.inspect and p.suffix.lower() in (".pkl", ".joblib"):
            try:
                e["describe"] = describe(p)
            except Exception as exc:
                e["describe_error"] = f"{type(exc).__name__}: {exc}"
        entries.append(e)
        print(f"{e['path']}  {e['bytes']:>10} bytes  {e['sha256'][:16]}")
    versions = {}
    for mod in ("sklearn", "xgboost", "lightgbm", "numpy", "pandas", "joblib"):
        try:
            versions[mod] = __import__(mod).__version__
        except Exception:
            pass
    manifest = {"registered": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "python": platform.python_version(),
                "library_versions": versions, "files": entries}
    (MODELS / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, default=str))
    print(f"wrote {MODELS / 'MANIFEST.json'}")
    if a.upload:
        from huggingface_hub import HfApi
        api = HfApi()
        api.create_repo(a.upload, repo_type="model", private=True, exist_ok=True)
        api.upload_folder(folder_path=str(MODELS), repo_id=a.upload, repo_type="model",
                          commit_message="Register Isôko trained models")
        print(f"backed up to https://huggingface.co/{a.upload} (private)")


if __name__ == "__main__":
    main()
