"""Local zero-shot classification with GLiClass Multilang (optional extra: `uv sync --extra classify`).

Adds to each requirement its kind: requirement (binding) or information (explanation, heading, note).
Information items are excluded from grading. Runs on CPU; the model (~288M params) downloads on first use.

Zero-shot quality categories (functional, performance, ...) were evaluated and dropped: 38% accuracy on the
12 PROMISE classes and no better than the majority baseline on F vs NFR (bench/classify_promise.py).
That needs few-shot examples or a fine-tune on labelled data.
"""

import re
from functools import cache

MODEL = "knowledgator/gliclass-multilang-mini"
KINDS = ["requirement", "information"]
# An obligation verb makes an item binding whatever the model says: a weak requirement must never be hidden as information.
OBLIGATION = re.compile(
    r"\b(?:shall|must|should|is required to|are required to|muss|müssen|soll|sollen|sollte|sollten|darf|dürfen|"
    r"ist zu|sind zu|hat zu|haben zu)\b",
    re.IGNORECASE,
)


@cache
def _pipeline():
    import logging
    import warnings

    from gliclass import GLiClassModel, ZeroShotClassificationPipeline
    from transformers import AutoTokenizer
    from transformers.utils import logging as hf_logging

    warnings.filterwarnings("ignore")
    hf_logging.set_verbosity_error()
    logging.getLogger("gliclass").setLevel(logging.ERROR)
    return ZeroShotClassificationPipeline(
        GLiClassModel.from_pretrained(MODEL),
        AutoTokenizer.from_pretrained(MODEL),
        classification_type="single-label",
        device="cpu",
        progress_bar=False,
    )


def top(texts: list[str], labels: list[str]) -> list[tuple[str, float]]:
    out = _pipeline()(texts, labels, threshold=0.0, batch_size=16)
    return [
        max(((p["label"], p["score"]) for p in preds), key=lambda x: x[1])
        for preds in out
    ]


def classify(doc: dict) -> dict:
    reqs = doc["requirements"]
    for r in reqs:
        if (
            "classification" in r
        ):  # decided by the input file (or an earlier run): keep it
            continue
        if OBLIGATION.search(r["text"]):
            r["classification"] = {
                "model": "obligation verb",
                "kind": "requirement",
                "score": 1.0,
            }
    rest = [r for r in reqs if "classification" not in r]
    for r, (kind, score) in zip(
        rest, top([r["text"] for r in rest], KINDS) if rest else []
    ):
        r["classification"] = {"model": MODEL, "kind": kind, "score": round(score, 3)}
    return doc
