"""Timing per stage at 100 / 1k / 10k items, built from PROMISE_exp texts.

Stages: read (CSV), per-item rules, whole-spec rules, report + grading, batches + merge, and
--classify when the `classify` extra is installed. The Haiku review itself runs outside speclint
and isn't timed. 10k items repeat PROMISE's 969 texts, so the duplicate check sees about ten copies
of every text: a worst case for that stage, not a typical spec.
Usage: uv run python bench/timing.py [profile] [sizes...]
"""

import csv
import json
import sys
import tempfile
import time
from pathlib import Path

from promise import load

from speclint.checks import check, report
from speclint.profiles import Profile, load_profile
from speclint.readers import read
from speclint.review import batches, merge
from speclint.spec_checks import SPEC_RULES, check_spec


def timed(fn, *args):
    t = time.perf_counter()
    out = fn(*args)
    return out, time.perf_counter() - t


def review(doc, out_dir, reviews):
    batches(doc, out_dir)
    return merge(doc, reviews)


def main(profile: str = "system", *sizes: int) -> None:
    p = load_profile(profile)
    items_only = Profile(
        p.name, {k: v for k, v in p.severities.items() if k not in SPEC_RULES}
    )
    texts = [r.text for r in load()]
    try:  # needs `uv sync --extra classify`
        import gliclass  # noqa: F401

        from speclint.classify import classify
    except ImportError:
        classify = None
    check(load()[:5], "en", items_only)  # load the spaCy model outside the timings
    print(f"profile {profile}; seconds per stage (items/s in brackets)")
    print(
        f"{'items':>6} {'read':>8} {'rules':>8} {'spec':>8} {'report':>8} {'review':>8} {'classify':>9}"
    )
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for n in sizes or (100, 1000, 10000):
            src = tmp / f"spec-{n}.csv"
            with src.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["ID", "Text"])
                w.writerows((f"REQ-{i}", texts[i % len(texts)]) for i in range(n))
            reqs, t_read = timed(read, src)
            results, t_rules = timed(check, reqs, "en", items_only)
            _, t_spec = timed(check_spec, results, set(p.severities))
            doc, t_report = timed(report, results, p)
            empty = tmp / "none.review.json"
            empty.write_text(json.dumps({"reviews": []}))
            _, t_review = timed(review, doc, tmp / "batches", [empty])
            t_cls = f"{timed(classify, doc)[1]:9.2f}" if classify else "  skipped"
            row = [t_read, t_rules, t_spec, t_report, t_review]
            print(
                f"{n:>6} " + " ".join(f"{t:8.2f}" for t in row) + f" {t_cls}"
                f"   [rules {n / t_rules:.0f}/s, all {n / sum(row):.0f}/s]"
            )


if __name__ == "__main__":
    args = sys.argv[1:]
    name = args.pop(0) if args and not args[0].isdigit() else "system"
    main(name, *map(int, args))
