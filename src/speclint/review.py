"""Split findings into batches for reviewer agents and merge their reviews back into the results document."""

import json
import sys
from pathlib import Path

from .checks import rescore

VERDICTS = {"confirmed", "dismissed"}


def batches(doc: dict, out_dir: Path, size: int = 25) -> list[Path]:
    # key = position in the document: IDs repeat across files (e.g. DOORS absolute numbers per module)
    todo = [
        (key, r)
        for key, r in enumerate(doc["requirements"])
        if r["findings"] and r.get("classification", {}).get("kind") != "information"
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(
        "batch-*.json"
    ):  # reviews of a previous run would point at other findings
        old.unlink()
    paths = []
    for n in range(0, len(todo), size):
        path = out_dir / f"batch-{n // size + 1:03d}.json"
        path.write_text(
            json.dumps(
                {
                    "requirements": [
                        {
                            "key": key,
                            "id": r["id"],
                            "lang": r["lang"],
                            "text": r["text"],
                            "findings": [
                                {
                                    "index": i,
                                    "rule": f["rule"],
                                    "match": f["match"],
                                    "incose": f["incose"],
                                    "severity": f["severity"],
                                    "message": f["message"],
                                }
                                for i, f in enumerate(r["findings"])
                            ],
                        }
                        for key, r in todo[n : n + size]
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def merge(doc: dict, review_files: list[Path]) -> tuple[dict, list[str]]:
    """Apply reviews. Model-written input: anything malformed is skipped and reported, never trusted."""
    reqs = doc["requirements"]
    problems = []
    for path in review_files:
        try:
            reviews = json.loads(path.read_text(encoding="utf-8"))["reviews"]
        except (OSError, ValueError, KeyError, TypeError) as e:
            problems.append(f"{path}: unreadable ({e})")
            continue
        for rv in reviews if isinstance(reviews, list) else []:
            key = rv.get("key") if isinstance(rv, dict) else None
            req = reqs[key] if isinstance(key, int) and 0 <= key < len(reqs) else None
            if req is None or req["id"] != rv.get("id"):
                problems.append(
                    f"{path}: no requirement with key and id of {rv!r:.120}"
                )
                continue
            findings = rv.get("findings") or []
            if not isinstance(findings, list):
                problems.append(f"{path}: {req['id']}: findings is not a list")
                continue
            for v in findings:
                i = v.get("index") if isinstance(v, dict) else None
                if (
                    not isinstance(i, int)
                    or not 0 <= i < len(req["findings"])
                    or v.get("verdict") not in VERDICTS
                    # guards against reviews of an earlier run whose finding i was another rule
                    or v.get("rule") != req["findings"][i]["rule"]
                ):
                    problems.append(
                        f"{path}: {req['id']}: invalid finding verdict {v!r}"
                    )
                    continue
                req["findings"][i]["dismissed"] = v["verdict"] == "dismissed"
                req["findings"][i]["review_reason"] = str(v.get("reason") or "")
            req["review"] = {
                k: str(rv[k]) for k in ("question", "rewrite") if rv.get(k)
            }
    return rescore(doc), problems


def main_merge(results: Path, review_files: list[Path]) -> int:
    doc, problems = merge(json.loads(results.read_text(encoding="utf-8")), review_files)
    results.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    for p in problems:
        print(f"warning: {p}", file=sys.stderr)
    reviewed = sum(1 for r in doc["requirements"] if "review" in r)
    print(
        f"Merged {reviewed} reviews, {doc['summary']['dismissed']} findings dismissed. "
        f"Overall {doc['summary']['grade']} ({doc['summary']['score']}%)"
    )
    return 0
