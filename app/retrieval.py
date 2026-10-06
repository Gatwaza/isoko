"""BM25 retrieval over the bilingual advisory corpus.

Dependency-free on purpose: it runs on a single small server inside Rwanda and is
fully inspectable. It can be swapped for a vector index over the national corpus
(served via RISA's APIs / MCP server) without changing the advisor interface.
"""
import json
import math
import re
from collections import Counter
from dataclasses import dataclass

from . import config

# Very light normalisation: lowercase, strip punctuation and apostrophes so that
# Kinyarwanda contractions like "y'ibirayi" also index "ibirayi".
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "my", "i", "it",
    "what", "how", "do", "can", "should", "with", "at", "be", "this", "that", "when", "which",
    "ni", "na", "ku", "mu", "kuri", "ya", "yo", "wa", "za", "cy", "by", "bw", "rw", "kw",
    "iki", "ese", "nte", "gute", "nki", "kandi", "cyangwa", "ndashaka", "nshaka",
}

TOPIC_BONUS = 1.0
# Very frequent Kinyarwanda verb stems ("can", "want") whose endings collide with farm verbs
# (nshobora "I can" ends like kubora "to rot"); never root-match them.
_FREQUENT_VERBS = ("shobor", "shak")
_GENERIC = {"getting", "help", "making", "good", "safe", "use", "from", "services", "management", "control",
            "quality", "when", "ready", "rwanda"}


def _stem(t: str) -> str:
    # English plurals only ("potatoes" -> "potato", "cows" -> "cow"); Kinyarwanda words don't end in -s.
    if t.endswith("oes") and len(t) > 4:
        return t[:-2]
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith("s") and not t.endswith(("ss", "us", "is")) and len(t) > 3:
        return t[:-1]
    return t


def tokenize(text: str) -> list[str]:
    text = text.lower().replace("'", " ").replace("\u2019", " ")
    return [_stem(t) for t in _TOKEN.findall(text) if t not in _STOP and len(t) > 1]


def _lev(a: str, b: str, cap: int) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        if min(cur) >= cap:
            return cap
        prev = cur
    return prev[-1]


@dataclass
class Hit:
    entry: dict
    score: float


class Corpus:
    def __init__(self, path: str = config.CORPUS_PATH, extra: list[dict] | None = None):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.meta = data["meta"]
        self.entries: list[dict] = data["entries"] + list(extra or [])
        self.meta = {**self.meta, "extra_entries": len(extra or [])}
        self.by_id = {e["id"]: e for e in self.entries}
        self._docs = [self._doc_tokens(e) for e in self.entries]
        self._df = Counter(t for d in self._docs for t in set(d))
        self._avgdl = sum(len(d) for d in self._docs) / len(self._docs)
        self._tf = [Counter(d) for d in self._docs]
        # What each entry is *about* (title + keywords), for a topic bonus outside BM25 saturation.
        self._topic = [set(tokenize(" ".join((e["title_en"], e["title_rw"], e["keywords"])))) for e in self.entries]
        # Domain vocabulary from curated titles/keywords only (not free text), used to
        # reject off-topic questions that match incidental words in passage bodies.
        self.anchors = {t for e in self.entries
                        for t in tokenize(" ".join((e["title_en"], e["title_rw"], e["keywords"])))} - _GENERIC
        # Kinyarwanda verbs = subject/tense/object prefixes + root + final vowel; the infinitive is
        # ku-/gu-/kw- + root. Index roots of infinitives so conjugated forms in questions
        # ("nzasarura", "nayitera") match corpus words ("gusarura", "gutera").
        self.verb_roots: dict[str, set[str]] = {}
        for t in self._df:
            for pre in ("gu", "ku", "kw"):
                if t.startswith(pre) and len(t) - len(pre) >= 4:
                    self.verb_roots.setdefault(t[len(pre):], set()).add(t)

    def expand(self, terms: list[str]) -> list[tuple[str, float]]:
        """Query terms with weights; unknown Kinyarwanda verb forms are mapped to known infinitives."""
        out = [(t, 1.0) for t in terms]
        for t in terms:
            # Initial-vowel (augment) elision: "ku ntera" -> "intera", "mu murima" -> "umurima".
            if t not in self._df or t not in self.anchors:
                for aug in ("i", "u", "a"):
                    if aug + t in self.anchors:
                        out.append((aug + t, 0.9))
            # Domain-lexicon correction for ASR errors and SMS typos ("midiu" -> "mildiyu").
            if t not in self._df and len(t) >= 5:
                best = self._closest(t)
                if best:
                    out.append((best, 0.7))
            if t in self._df or len(t) < 6 or any(v in t for v in _FREQUENT_VERBS):
                continue
            for root, forms in self.verb_roots.items():
                if t.endswith(root) and len(t) > len(root):
                    out.extend((f, 0.8) for f in forms)
        return out

    def _closest(self, t: str) -> str | None:
        """Nearest curated domain term within a small edit distance (<= ~30% of the word)."""
        best, best_ratio = None, 0.3  # edits relative to the longer word must stay under 30%
        for a in self.anchors:
            if len(a) < 5 or abs(len(a) - len(t)) > 3:
                continue
            d = _lev(t, a, 4)
            ratio = d / max(len(a), len(t))
            if ratio < best_ratio:
                best, best_ratio = a, ratio
        return best

    def is_in_domain(self, q: str) -> bool:
        # Fuzzy (typo/ASR) matches alone never make a question in-domain: a real domain term is required.
        return any(t in self.anchors for t, w in self.expand(tokenize(q)) if w >= 0.8)

    @staticmethod
    def _doc_tokens(e: dict) -> list[str]:
        # Titles and keywords are weighted by repetition; bodies add recall.
        fields = [e["title_en"], e["title_rw"], e["keywords"]] * 3 + [
            e["summary_en"], e["summary_rw"], e["detail_en"], e["detail_rw"],
        ]
        return tokenize(" ".join(fields))

    def search(self, q: str, k: int = 3, k1: float = 1.4, b: float = 0.75) -> list[Hit]:
        terms = self.expand(tokenize(q))
        if not terms:
            return []
        n = len(self.entries)
        scores = []
        for i, tf in enumerate(self._tf):
            dl = len(self._docs[i])
            s = 0.0
            for t, w in terms:
                f = tf.get(t)
                if not f:
                    continue
                idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                s += w * idf * f * (k1 + 1) / (f + k1 * (1 - b + b * dl / self._avgdl))
                if t in self._topic[i]:
                    s += w * idf * TOPIC_BONUS
            if s > 0:
                scores.append(Hit(self.entries[i], s))
        scores.sort(key=lambda h: h.score, reverse=True)
        return scores[:k]

    def find(self, *, crop: str | None = None, topic: str | None = None,
             category: str | None = None) -> list[dict]:
        return [
            e for e in self.entries
            if (crop is None or e["crop"] == crop)
            and (topic is None or e["topic"] == topic)
            and (category is None or e["category"] == category)
        ]


_corpus: Corpus | None = None
_loaded_at = 0.0
RELOAD_S = 60  # refinement-window entries imported via the admin API appear within a minute


def corpus() -> Corpus:
    """Curated JSON corpus + entries imported during the refinement window (kb_extra table)."""
    global _corpus, _loaded_at
    import time
    if _corpus is None or time.time() - _loaded_at > RELOAD_S:
        from . import db
        try:
            extra = db.kb_extra()
        except Exception:
            extra = []
        if _corpus is None or len(extra) != _corpus.meta.get("extra_entries"):
            _corpus = Corpus(extra=extra)
        _loaded_at = time.time()
    return _corpus


def reload() -> Corpus:
    global _loaded_at
    _loaded_at = 0.0
    return corpus()
