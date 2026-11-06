"""Benchmark on PROMISE_exp (969 English requirements, labelled F/NFR type; no quality labels).

Reports runtime, hit rate per rule and a random sample of hits per rule for manual precision review.
Usage: uv run python bench/promise.py [samples-per-rule]
"""

import csv
import random
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

from speclint.checks import RULES, Requirement, check, report

URL = "https://raw.githubusercontent.com/AleksandarMitrevski/se-requirements-classification/master/0-datasets/PROMISE_exp/PROMISE_exp.arff"
DATA = Path(__file__).parent / "data" / "PROMISE_exp.arff"


def load() -> list[Requirement]:
    if not DATA.exists():
        DATA.parent.mkdir(parents=True, exist_ok=True)
        part = DATA.with_suffix(".part")  # an interrupted download must not be reused
        urllib.request.urlretrieve(URL, part)
        part.rename(DATA)
    lines = (
        DATA.read_text(encoding="utf-8", errors="replace")
        .split("@DATA", 1)[1]
        .strip()
        .splitlines()
    )
    # rows look like: 1,'The system shall ...',PE
    return [
        Requirement(f"P{row[0]}-{n}", row[1], row[2])
        for n, row in enumerate(csv.reader(lines, quotechar="'", escapechar="\\"))
        if len(row) >= 3
    ]


def main(samples: int = 5) -> None:
    reqs = load()
    t = time.perf_counter()
    results = check(reqs, "en")
    elapsed = time.perf_counter() - t
    s = report(results)["summary"]
    print(
        f"{len(results)} requirements in {elapsed:.2f}s ({len(results) / elapsed:.0f}/s). Overall {s['grade']} ({s['score']:.0f}%)"
    )
    print(f"{sum(1 for r in results if r.findings)} with findings\n")

    hits = Counter(f.rule for r in results for f in r.findings)
    rng = random.Random(0)
    for rule in RULES["rules"]:
        found = [(r, f) for r in results for f in r.findings if f.rule == rule]
        print(
            f"== {rule}: {hits[rule]} hits in {len({id(r) for r, _ in found})} requirements"
        )
        for r, f in rng.sample(found, min(samples, len(found))):
            print(f"   [{f.match}] {r.req.text[:140]}")


if __name__ == "__main__":
    main(*map(int, sys.argv[1:]))
