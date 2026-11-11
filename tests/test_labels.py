"""Haiku labels (domain, safety, security, ...): requested per profile, applied by merge, never graded."""

import json

import pytest
from test_schema import validate

from speclint.checks import Requirement, check, report
from speclint.profiles import load_profile
from speclint.review import batches, merge

ALL = ["domain", "safety", "security", "type", "level", "verification", "solution"]


def doc(profile="system", texts=None):
    p = load_profile(profile)
    texts = texts or [
        "The controller shall start within 200 ms ± 20 ms.",  # no findings
        "The controller shall start quickly.",
        "Hinweis: Die Position liefert der Hall-Sensor.",
    ]
    reqs = [Requirement(f"R-{i}", t) for i, t in enumerate(texts)]
    return report(check(reqs, "auto", p), p)


def test_profiles_choose_labels(tmp_path):
    assert load_profile("customer").labels == ["domain", "safety", "security"]
    assert load_profile("system").labels == ALL
    f = tmp_path / "p.toml"
    f.write_text('[profile]\nextends = "system"\nlabels = ["domain"]\n')
    assert load_profile(str(f)).labels == ["domain"]
    f.write_text('[profile]\nextends = "customer"\nlabels = ["colour"]\n')
    with pytest.raises(ValueError, match="unknown label"):
        load_profile(str(f))


def test_profile_records_labels():
    assert doc()["profile"]["labels"] == ALL


@pytest.mark.parametrize(
    "text,level",
    [
        ("The ECU shall detect a stuck window within 1 s (ASIL B).", "ASIL B"),
        ("Das Steuergerät muss den Fehler melden. ASIL-D", "ASIL D"),
        ("The brake request shall be checked, ASIL B(D).", "ASIL B(D)"),
        ("The pump control shall meet SIL 2.", "SIL 2"),
        ("The display shall show the time. ASIL QM", "ASIL QM"),
    ],
)
def test_stated_integrity_level_is_extracted(text, level):
    (r,) = doc(texts=[text])["requirements"]
    assert r["integrity"] == level


def test_no_integrity_field_without_a_stated_level():
    (r,) = doc(texts=["The ECU shall log the QM report."])["requirements"]
    assert "integrity" not in r


def test_batches_send_every_requirement_with_label_definitions(tmp_path):
    (path,) = batches(doc(), tmp_path)
    batch = json.loads(path.read_text())
    assert [r["id"] for r in batch["requirements"]] == ["R-0", "R-1", "R-2"]
    assert list(batch["labels"]) == ALL
    assert batch["labels"]["domain"]["values"] == ["ME", "EE", "SW", "SYS"]
    assert batch["labels"]["domain"]["multi"] is True
    assert batch["labels"]["safety"]["description"]


def test_without_labels_batches_hold_only_findings_and_classify(tmp_path):
    d = doc()
    d["profile"]["labels"] = []
    (path,) = batches(d, tmp_path)
    batch = json.loads(path.read_text())
    assert "labels" not in batch
    assert [r["id"] for r in batch["requirements"]] == ["R-1", "R-2"]


def review(tmp_path, entries):
    f = tmp_path / "x.review.json"
    f.write_text(json.dumps({"reviews": entries}))
    return f


def test_merge_applies_valid_labels_and_counts_them(tmp_path):
    d = doc(
        texts=[
            "The controller shall start within 200 ms ± 20 ms.",
            "The controller shall brake (ASIL B).",
        ]
    )
    labels0 = {
        "domain": ["EE", "SW"],
        "safety": "yes",
        "security": "no",
        "type": "performance",
        "level": "system",
        "verification": "test",
        "solution": "free",
    }
    labels1 = {**labels0, "domain": ["SYS"]}
    f = review(
        tmp_path,
        [
            {"key": 0, "id": "R-0", "findings": [], "labels": labels0},
            {"key": 1, "id": "R-1", "findings": [], "labels": labels1},
        ],
    )
    d, problems = merge(d, [f])
    assert problems == []
    r0, r1 = d["requirements"]
    assert r0["labels"] == labels0 and r0["grade"] == "none"
    assert r1["integrity"] == "ASIL B" and r1["labels"]["domain"] == ["SYS"]
    s = d["summary"]["labels"]
    assert s["domain"] == {"EE": 1, "SW": 1, "SYS": 1}
    assert s["safety"] == {"yes": 2}
    assert d["summary"]["safety_without_level"] == 1  # R-0 states no ASIL
    validate(d)


def test_merge_rejects_bad_labels_one_by_one(tmp_path):
    d = doc(texts=["The controller shall start within 200 ms ± 20 ms."])
    f = review(
        tmp_path,
        [
            {
                "key": 0,
                "id": "R-0",
                "findings": [],
                "labels": {
                    "domain": "EE",  # must be a list
                    "safety": "maybe",
                    "security": "no",
                    "colour": "red",
                    "level": ["system"],  # must be one value
                },
            }
        ],
    )
    d, problems = merge(d, [f])
    assert d["requirements"][0]["labels"] == {"security": "no"}
    assert len(problems) == 4 and all("label" in p for p in problems)


def test_labels_are_dropped_for_information_items(tmp_path):
    d = doc(texts=["Hinweis: Die Position liefert der Hall-Sensor."])
    f = review(
        tmp_path,
        [
            {
                "key": 0,
                "id": "R-0",
                "findings": [],
                "kind": "information",
                "labels": {"domain": ["EE"]},
            }
        ],
    )
    d, problems = merge(d, [f])
    assert "labels" not in d["requirements"][0] and problems == []
    assert d["summary"]["labels"] == {}


def test_merge_cli_prints_label_counts_and_safety_gap(tmp_path, capsys):
    from speclint.cli import main

    src = tmp_path / "s.md"
    src.write_text("- R-1: The controller shall brake within 200 ms ± 20 ms.\n")
    results = tmp_path / "r.json"
    main(["check", str(src), "-o", str(results)])
    f = review(
        tmp_path,
        [
            {
                "key": 0,
                "id": "R-1",
                "findings": [],
                "labels": {"domain": ["SW"], "safety": "yes", "security": "no"},
            }
        ],
    )
    capsys.readouterr()
    assert main(["merge", str(results), str(f)]) == 0
    out = capsys.readouterr().out
    assert "domain SW:1" in out and "safety yes:1" in out
    assert "1 safety-relevant item states no ASIL/SIL" in out


def test_merge_records_unsure_decisions_and_the_reviewer_model(tmp_path):
    d = doc()
    f = review(
        tmp_path,
        [
            {
                "key": 0,
                "id": "R-0",
                "findings": [],
                "labels": {"safety": "no"},
                "unsure": ["safety", "colour"],
            },
            {
                "key": 2,
                "id": "R-2",
                "findings": [],
                "kind": "information",
                "unsure": ["kind"],
            },
        ],
    )
    d, problems = merge(d, [f])
    r0, _, r2 = d["requirements"]
    assert r0["review"] == {"model": "haiku", "unsure": ["safety"]}
    assert r2["review"]["unsure"] == ["kind"]
    assert problems == [f"{f}: R-0: unsure 'colour' is not kind or a requested label"]
    validate(d)


def test_unsure_batches_hold_only_unsure_items_even_information(tmp_path):
    d = doc()
    f = review(
        tmp_path,
        [
            {"key": 0, "id": "R-0", "findings": [], "labels": {"safety": "no"}},
            {
                "key": 2,
                "id": "R-2",
                "findings": [],
                "kind": "information",
                "unsure": ["kind"],
            },
        ],
    )
    d, _ = merge(d, [f])
    (path,) = batches(d, tmp_path / "esc", unsure=True)
    (item,) = json.loads(path.read_text())["requirements"]
    assert item["id"] == "R-2" and item["classify"] is True
    assert batches(merge(doc(), [])[0], tmp_path / "none", unsure=True) == []


def test_escalated_review_replaces_the_first_one(tmp_path):
    d = doc()
    first = review(
        tmp_path,
        [
            {
                "key": 2,
                "id": "R-2",
                "findings": [],
                "kind": "information",
                "unsure": ["kind"],
            }
        ],
    )
    d, _ = merge(d, [first])
    second = tmp_path / "s.review.json"
    second.write_text(
        json.dumps(
            {
                "reviews": [
                    {
                        "key": 2,
                        "id": "R-2",
                        "findings": [],
                        "kind": "requirement",
                        "labels": {"safety": "no"},
                    }
                ]
            }
        )
    )
    d, problems = merge(d, [second], model="sonnet")
    r2 = d["requirements"][2]
    assert problems == []
    assert r2["classification"] == {"model": "sonnet", "kind": "requirement"}
    assert r2["review"] == {"model": "sonnet"} and r2["labels"] == {"safety": "no"}
    validate(d)
