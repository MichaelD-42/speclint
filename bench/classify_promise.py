"""Zero-shot GLiClass accuracy on PROMISE_exp type labels (F vs NFR, and the 12 classes).

Usage: uv run --extra classify python bench/classify_promise.py
"""

import time
from collections import Counter

from promise import load

from speclint.classify import top

CODES = {
    "F": "functional",
    "A": "availability",
    "FT": "fault tolerance",
    "L": "legal",
    "LF": "look and feel",
    "MN": "maintainability",
    "O": "operational",
    "PE": "performance",
    "PO": "portability",
    "SC": "scalability",
    "SE": "security",
    "US": "usability",
}


def main() -> None:
    reqs = [r for r in load() if r.source in CODES]
    gold = [CODES[r.source] for r in reqs]
    t = time.perf_counter()
    pred = [label for label, _ in top([r.text for r in reqs], list(CODES.values()))]
    elapsed = time.perf_counter() - t

    acc = sum(g == p for g, p in zip(gold, pred)) / len(gold)
    binary = sum(
        (g == "functional") == (p == "functional") for g, p in zip(gold, pred)
    ) / len(gold)
    print(f"{len(reqs)} requirements in {elapsed:.1f}s ({len(reqs) / elapsed:.0f}/s)")
    print(f"12-class accuracy {acc:.1%}   F vs NFR accuracy {binary:.1%}")
    f1s = []
    for label in CODES.values():
        tp = sum(g == p == label for g, p in zip(gold, pred))
        prec = tp / max(1, sum(p == label for p in pred))
        rec = tp / max(1, sum(g == label for g in gold))
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0)
        print(
            f"  {label:<16} n={sum(g == label for g in gold):<4} P={prec:.2f} R={rec:.2f} F1={f1s[-1]:.2f}"
        )
    print(f"macro F1 {sum(f1s) / len(f1s):.2f}")
    print(
        "most common confusions:",
        Counter((g, p) for g, p in zip(gold, pred) if g != p).most_common(5),
    )


if __name__ == "__main__":
    main()
