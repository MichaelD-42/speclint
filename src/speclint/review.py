"""Split findings into batches for reviewer agents and merge their reviews back into the results document."""

import json
import sys
from pathlib import Path

from .checks import OBLIGATION, RULES, rescore

VERDICTS = {"confirmed", "dismissed"}
KINDS = {"requirement", "information"}


def needs_kind(r: dict) -> bool:
    """Neither an obligation verb nor the input file decided whether the item is a requirement: a reviewer does."""
    cls = r.get("classification")
    undecided = cls is None or cls.get("model") not in (
        "input",
        "obligation verb",
    )  # a reviewer's own label may be revised
    return undecided and not OBLIGATION.search(r["text"])


def batches(
    doc: dict, out_dir: Path, size: int = 25, unsure: bool = False
) -> list[Path]:
    """With unsure, only the items a reviewer was unsure about, for a stronger model to review again."""
    # key = position in the document: IDs repeat across files (e.g. DOORS absolute numbers per module)
    labels = doc.get("profile", {}).get("labels", [])
    todo = [  # with labels on, every requirement needs a review
        (key, r)
        for key, r in enumerate(doc["requirements"])
        if (
            r.get("review", {}).get("unsure")
            if unsure
            else (r["findings"] or needs_kind(r) or labels)
            and r.get("classification", {}).get("kind") != "information"
        )
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
                            **({"classify": True} if needs_kind(r) else {}),
                            "findings": [
                                {
                                    "index": i,
                                    "rule": f["rule"],
                                    "match": f["match"],
                                    "incose": f["incose"],
                                    "severity": f["severity"],
                                    "message": f["message"],
                                    **(
                                        {
                                            "related": [
                                                {
                                                    "id": x["id"],
                                                    "text": doc["requirements"][
                                                        x["key"]
                                                    ]["text"],
                                                }
                                                for x in f["related"]
                                            ]
                                        }
                                        if f.get("related")
                                        else {}
                                    ),
                                }
                                for i, f in enumerate(r["findings"])
                            ],
                        }
                        for key, r in todo[n : n + size]
                    ],
                    **(
                        {"labels": {name: RULES["labels"][name] for name in labels}}
                        if labels
                        else {}
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def merge(
    doc: dict, review_files: list[Path], model: str = "haiku"
) -> tuple[dict, list[str]]:
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
                "model": model,
                **{k: str(rv[k]) for k in ("question", "rewrite") if rv.get(k)},
            }
            unsure = rv.get("unsure") or []
            if not isinstance(unsure, list):
                problems.append(f"{path}: {req['id']}: unsure is not a list")
                unsure = []
            allowed = ["kind", *doc.get("profile", {}).get("labels", [])]
            problems += [
                f"{path}: {req['id']}: unsure {u!r} is not kind or a requested label"
                for u in unsure
                if u not in allowed
            ]
            if valid_unsure := [u for u in allowed if u in unsure]:
                req["review"]["unsure"] = valid_unsure
            if "kind" in rv:
                if rv["kind"] not in KINDS:
                    problems.append(f"{path}: {req['id']}: invalid kind {rv['kind']!r}")
                elif not needs_kind(req):
                    # an obligation verb or the input file already decided
                    problems.append(
                        f"{path}: {req['id']}: kind ignored, already decided"
                    )
                else:
                    req["classification"] = {"model": model, "kind": rv["kind"]}
            if "labels" in rv:
                valid, bad = _labels(
                    rv["labels"], doc.get("profile", {}).get("labels", [])
                )
                problems += [f"{path}: {req['id']}: {b}" for b in bad]
                if req.get("classification", {}).get("kind") == "information":
                    req.pop("labels", None)  # information items get no labels
                elif valid:
                    req["labels"] = valid
    return rescore(doc), problems


def _labels(given, requested: list[str]) -> tuple[dict, list[str]]:
    """Keep the labels that the profile requested and whose values are allowed; report the rest."""
    if not isinstance(given, dict):
        return {}, [f"labels is not an object: {given!r:.80}"]
    valid, bad = {}, []
    for name, value in given.items():
        spec = RULES["labels"].get(name)
        if spec is None or name not in requested:
            bad.append(f"label {name!r} was not requested")
        elif spec.get("multi"):
            if (
                isinstance(value, list)
                and value
                and all(v in spec["values"] for v in value)
            ):
                valid[name] = list(dict.fromkeys(value))
            else:
                bad.append(
                    f"label {name}: {value!r:.60} is not a list of {spec['values']}"
                )
        elif isinstance(value, str) and value in spec["values"]:
            valid[name] = value
        else:
            bad.append(f"label {name}: {value!r:.60} is not one of {spec['values']}")
    return valid, bad


def main_merge(results: Path, review_files: list[Path], model: str = "haiku") -> int:
    doc, problems = merge(
        json.loads(results.read_text(encoding="utf-8")), review_files, model
    )
    results.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    for p in problems:
        print(f"warning: {p}", file=sys.stderr)
    reviewed = sum(1 for r in doc["requirements"] if "review" in r)
    print(
        f"Merged {reviewed} reviews, {doc['summary']['dismissed']} findings dismissed. "
        f"{doc['summary']['needs_clarification']} of {doc['summary']['graded']} graded items need clarification."
    )
    s = doc["summary"]
    if s.get("labels"):
        print(
            "Labels: "
            + " · ".join(
                f"{name} " + " ".join(f"{v}:{n}" for v, n in counts.items())
                for name, counts in s["labels"].items()
            )
        )
    if n := s.get("safety_without_level"):
        noun = "items state" if n > 1 else "item states"
        print(f"{n} safety-relevant {noun} no ASIL/SIL.")
    if n := sum(1 for r in doc["requirements"] if r.get("review", {}).get("unsure")):
        print(f"{model} was unsure about {n} items.")
    return 0
