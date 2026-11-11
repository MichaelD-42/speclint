"""Requirement vs information on items without an obligation verb: rule baseline vs Haiku.

Items with shall/muss/... are requirements whatever a model says, so only items without one matter.
The baseline is the plain rule "no obligation verb -> information". Haiku labels come from a JSON file
{id: "requirement"|"information"}, written by a Haiku subagent that saw only id, lang and text
(bench/classify_eval_prompt.md). With --decider, each item also goes to a running strands-decider server
(`strands-decider serve <checkpoint>`) as a choice question with the same two definitions. GLiClass was dropped after it scored 50% here, no better than the
baseline (see docs/backlog.md).
Usage: uv run python bench/classify_eval.py [labels.csv] [--haiku haiku.json] [--decider http://127.0.0.1:8000]
"""

import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

from speclint.checks import OBLIGATION

KINDS = ["requirement", "information"]

# Same definitions as bench/classify_eval_prompt.md, so the decider and Haiku answer the same question.
DECIDER_QUESTION = {
    "type": "choice",
    "instructions": "Is this item of a customer or system specification a requirement or information?",
    "criteria": {
        "requirement": "A binding statement of what the system, a component or the supplier does, delivers or "
        "has, including a value it must meet. It counts even without 'shall'/'muss', for example "
        "'The pump delivers 2 l/min at 3 bar', 'Storage temperature: -20 °C to +60 °C'.",
        "information": "Everything that binds no one: headings, notes, rationale or background, explanations, "
        "examples, definitions and abbreviations, references to other documents, revision history, open "
        "points, comments, and descriptions of the existing situation.",
    },
}

HERE = Path(__file__).parent


def scores(name: str, rows: list[dict], pred: list[str], seconds: float | None) -> None:
    gold = [r["label"] for r in rows]
    acc = sum(g == p for g, p in zip(gold, pred)) / len(gold)
    tp = sum(g == p == "information" for g, p in zip(gold, pred))
    p_info = tp / max(1, pred.count("information"))
    r_info = tp / max(1, gold.count("information"))
    r_req = sum(g == p == "requirement" for g, p in zip(gold, pred)) / max(
        1, gold.count("requirement")
    )
    by_lang = {
        lang: sum(g == p for g, p, r in zip(gold, pred, rows) if r["lang"] == lang)
        / sum(1 for r in rows if r["lang"] == lang)
        for lang in sorted({r["lang"] for r in rows})
    }
    speed = f"  {len(rows) / seconds:.0f} items/s" if seconds else ""
    langs = "  ".join(f"{k} {v:.0%}" for k, v in by_lang.items())
    print(
        f"{name:<9} accuracy {acc:4.0%}  information P {p_info:4.0%} R {r_info:4.0%}  "
        f"requirement R {r_req:4.0%}  [{langs}]{speed}"
    )
    wrong = [f"{r['id']}→{p}" for r, p in zip(rows, pred) if r["label"] != p]
    print(f"          wrong: {', '.join(wrong) or '-'}")


def decider(url: str, text: str) -> str:
    body = json.dumps({"state": text, "questions": {"kind": DECIDER_QUESTION}}).encode()
    req = urllib.request.Request(
        f"{url}/v1/systemone", body, {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)["answers"]["kind"]["choice"]


def main(path: Path, haiku: Path | None, decider_url: str | None) -> None:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    if bad := [r["id"] for r in rows if OBLIGATION.search(r["text"])]:
        sys.exit(f"items with an obligation verb don't belong in this set: {bad}")
    print(
        f"{len(rows)} items without obligation verb, {sum(r['label'] == 'information' for r in rows)} information"
    )
    scores("baseline", rows, ["information"] * len(rows), None)
    if haiku:
        labels = json.loads(haiku.read_text(encoding="utf-8"))
        missing = [r["id"] for r in rows if labels.get(r["id"]) not in KINDS]
        if missing:
            print(f"haiku     {len(missing)} items without a valid label: {missing}")
        scores("haiku", rows, [labels.get(r["id"], "information") for r in rows], None)
    if decider_url:
        t = time.perf_counter()
        pred = [decider(decider_url, r["text"]) for r in rows]
        scores("decider", rows, pred, time.perf_counter() - t)


if __name__ == "__main__":
    args = sys.argv[1:]
    haiku = Path(args[args.index("--haiku") + 1]) if "--haiku" in args else None
    url = args[args.index("--decider") + 1].rstrip("/") if "--decider" in args else None
    files = [a for a in args if a.endswith(".csv")]
    main(Path(files[0]) if files else HERE / "classify_eval.csv", haiku, url)
