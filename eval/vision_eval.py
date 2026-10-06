"""Crop-disease photo classifiers: accuracy on held-out field photos (beans, cassava).

    .venv-ml/bin/python eval/vision_eval.py beans <model_id> [...]
    .venv-ml/bin/python eval/vision_eval.py cassava <model_id> [...]

Test images: 40 bean photos from the AI-Lab-Makerere/beans test split (Uganda field photos) and
40 cassava photos from the iCassava test split (dpdl-benchmark/cassava), downloaded into data/img_test.
"""
import json
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ml_service"))
OUT = ROOT / "eval" / "results" / "vision_results.json"

CANON = {  # model label keywords -> canonical label
    "angular": "angular_leaf_spot", "rust": "bean_rust", "healthy": "healthy",
    "cbb": "cassava_bacterial_blight", "bacterial": "cassava_bacterial_blight",
    "cbsd": "cassava_brown_streak", "brown": "cassava_brown_streak",
    "cgm": "cassava_green_mottle", "mottle": "cassava_green_mottle",
    "cmd": "cassava_mosaic", "mosaic": "cassava_mosaic",
}


def canon(label: str) -> str:
    l = label.lower()
    if l == "h":
        return "healthy"
    for k, v in CANON.items():
        if k in l:
            return v
    return l


def main():
    subset, model_ids = sys.argv[1], sys.argv[2:]
    from vision_loader import image_classifier
    items = [i for i in json.loads((ROOT / "data" / "img_test" / "manifest.json").read_text()) if i["set"] == subset]
    results = json.loads(OUT.read_text()) if OUT.exists() else {}
    for mid in model_ids:
        clf = image_classifier(mid, "cpu")
        correct, lat, conf = 0, [], []
        for it in items:
            img = Image.open(it["path"]).convert("RGB")
            t0 = time.perf_counter()
            top = clf(img, top_k=1)[0]
            lat.append(time.perf_counter() - t0)
            ok = canon(top["label"]) == it["label"]
            correct += ok
            conf.append((top["score"], ok))
        hi = [ok for s, ok in conf if s >= 0.7]
        results[f"{subset}:{mid}"] = {
            "accuracy": round(100 * correct / len(items), 1), "n": len(items),
            "accuracy_when_confident": round(100 * sum(hi) / len(hi), 1) if hi else None,
            "share_confident": round(100 * len(hi) / len(items), 1),
            "median_latency_s_cpu": round(sorted(lat)[len(lat) // 2], 3),
            "labels": list(clf.model.config.id2label.values()),
        }
        r = results[f"{subset}:{mid}"]
        print(f"{subset} {mid}: acc {r['accuracy']}%  (conf>=0.7: {r['accuracy_when_confident']}% on {r['share_confident']}%)  {r['median_latency_s_cpu']}s")
        OUT.write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
