"""Reproducible Kinyarwanda ASR fine-tune (Whisper) with a before/after CER/WER report.

For C4IR's 20 h audio-script set during the refinement window.
    .venv-ml/bin/python eval/finetune_asr.py --train data/c4ir_audio/train.jsonl --test data/c4ir_audio/test.jsonl \
        --base DigitalUmuganda/whisper_small_kinyarwanda --out models/whisper-rw-isoko --epochs 3
Manifests are JSONL lines {"path": "clip.wav", "text": "transcript"}. Keep the test manifest frozen: it is the
before/after yardstick. Writes eval/results/asr_finetune.json and a model folder the ml_service can load
(ASR_MODEL=<out dir>).
"""
import argparse
import json
import sys
import time
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
from asr_eval import edits, load, norm  # noqa: E402


def score(pipe, items) -> dict:
    we = wt = ce = ct = 0
    for it in items:
        hyp = pipe({"raw": load(it["path"]), "sampling_rate": 16000})["text"]
        r, h = norm(it["text"]), norm(hyp)
        we += edits(r.split(), h.split()); wt += len(r.split())
        ce += edits(list(r), list(h)); ct += len(r)
    return {"wer": round(100 * we / max(wt, 1), 1), "cer": round(100 * ce / max(ct, 1), 1), "n": len(items)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--test", required=True)
    ap.add_argument("--base", default="DigitalUmuganda/whisper_small_kinyarwanda")
    ap.add_argument("--out", default="models/whisper-rw-isoko")
    ap.add_argument("--epochs", type=float, default=3)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--max-steps", type=int, default=-1, help="for smoke tests")
    a = ap.parse_args()

    from transformers import (Seq2SeqTrainer, Seq2SeqTrainingArguments, WhisperForConditionalGeneration,
                              WhisperProcessor, pipeline)
    device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    read = lambda p: [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    train, test = read(a.train), read(a.test)

    before = score(pipeline("automatic-speech-recognition", model=a.base, device=device), test)
    print("before:", before)

    proc = WhisperProcessor.from_pretrained(a.base)
    model = WhisperForConditionalGeneration.from_pretrained(a.base)
    model.config.forced_decoder_ids = None

    class DS(torch.utils.data.Dataset):
        def __init__(self, rows): self.rows = rows
        def __len__(self): return len(self.rows)
        def __getitem__(self, i):
            r = self.rows[i]
            feats = proc.feature_extractor(load(r["path"]), sampling_rate=16000).input_features[0]
            return {"input_features": feats, "labels": proc.tokenizer(r["text"]).input_ids}

    def collate(batch):
        x = proc.feature_extractor.pad([{"input_features": b["input_features"]} for b in batch], return_tensors="pt")
        y = proc.tokenizer.pad([{"input_ids": b["labels"]} for b in batch], return_tensors="pt")
        labels = y["input_ids"].masked_fill(y["attention_mask"].ne(1), -100)
        if (labels[:, 0] == model.config.decoder_start_token_id).all():
            labels = labels[:, 1:]
        x["labels"] = labels
        return x

    args = Seq2SeqTrainingArguments(output_dir=a.out, per_device_train_batch_size=a.batch, learning_rate=a.lr,
                                    num_train_epochs=a.epochs, max_steps=a.max_steps, warmup_ratio=0.1,
                                    logging_steps=25, save_strategy="no", report_to=[], seed=7,
                                    fp16=torch.cuda.is_available())
    t0 = time.time()
    Seq2SeqTrainer(model=model, args=args, train_dataset=DS(train), data_collator=collate).train()
    model.save_pretrained(a.out)
    proc.save_pretrained(a.out)

    after = score(pipeline("automatic-speech-recognition", model=a.out, device=device), test)
    report = {"base": a.base, "out": a.out, "train_clips": len(train), "test_clips": len(test), "before": before,
              "after": after, "minutes": round((time.time() - t0) / 60, 1), "epochs": a.epochs, "lr": a.lr}
    (ROOT / "eval" / "results" / "asr_finetune.json").write_text(json.dumps(report, indent=1))
    print("after:", after)


if __name__ == "__main__":
    main()
