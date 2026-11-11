import json

import pytest
from conftest import item_only

from speclint.checks import Requirement, check, report
from speclint.cli import main
from speclint.review import batches, merge


def doc():
    p = item_only("customer")
    return report(
        check(
            [
                Requirement("A", "The browser shall never display the password."),
                Requirement("B", "The ECU shall respond quickly where possible."),
                Requirement("C", "The ECU shall start within 200 ms."),
            ],
            "en",
            p,
        ),
        p,
    )


def test_batches_contain_only_items_with_findings(tmp_path):
    paths = batches(doc(), tmp_path, size=1)
    batch = [json.loads(p.read_text())["requirements"] for p in paths]
    assert [b[0]["id"] for b in batch] == ["A", "B"]
    assert batch[1][0]["findings"][0]["index"] == 0


def test_merge_dismisses_rescores_and_rejects_garbage(tmp_path):
    d = doc()
    assert d["requirements"][0]["grade"] == "B"
    review = tmp_path / "r.review.json"
    review.write_text(
        json.dumps(
            {
                "reviews": [
                    {
                        "key": 0,
                        "id": "A",
                        "findings": [
                            {
                                "index": 0,
                                "rule": "absolute",
                                "verdict": "dismissed",
                                "reason": "verifiable prohibition",
                            }
                        ],
                        "question": "",
                        "rewrite": "",
                    },
                    {
                        "key": 1,
                        "id": "B",
                        "findings": [
                            {"index": 0, "rule": "vague-term", "verdict": "confirmed"},
                            {"index": 7, "verdict": "confirmed"},
                            {"index": 1, "verdict": "maybe"},
                        ],
                        "question": "Which max. response time?",
                    },
                    {"id": "ZZ", "findings": []},
                    {"key": 2, "id": "C", "findings": 5},
                ]
            }
        )
    )
    broken = tmp_path / "broken.review.json"
    broken.write_text("{not json")
    d, problems = merge(d, [review, broken])
    a, b = d["requirements"][0], d["requirements"][1]
    assert a["grade"] == "none" and a["findings"][0]["dismissed"]
    assert (
        b["review"] == {"model": "haiku", "question": "Which max. response time?"}
        and b["findings"][0]["dismissed"] is False
    )
    assert d["summary"]["dismissed"] == 1
    assert (
        len(problems) == 5
    )  # index out of range, bad verdict, unknown id, findings not a list, unreadable file


def haiku_doc():
    p = item_only("customer")
    reqs = [
        Requirement("A", "Im Fehlerfall sollen die Daten ggf. gespeichert werden."),
        Requirement("B", "Hinweis: Die Position liefert der Hall-Sensor."),
        Requirement("C", "Türsteuerung", kind="information"),
        Requirement("D", "Supply voltage range: 9 V to 16 V."),
    ]
    return report(check(reqs, "auto", p), p)


def test_batches_ask_haiku_to_classify_only_undecided_items(tmp_path):
    (path,) = batches(haiku_doc(), tmp_path)
    items = {r["id"]: r for r in json.loads(path.read_text())["requirements"]}
    assert set(items) == {"A", "B", "D"}  # C is information from the input
    assert "classify" not in items["A"]  # obligation verb: always a requirement
    assert items["B"]["classify"] is True and items["D"]["classify"] is True
    assert items["B"]["findings"] == []


def test_merge_applies_haiku_kind_only_where_undecided(tmp_path):
    d = haiku_doc()
    assert d["summary"]["graded"] == 3
    review = tmp_path / "r.review.json"
    review.write_text(
        json.dumps(
            {
                "reviews": [
                    {"key": 0, "id": "A", "findings": [], "kind": "information"},
                    {"key": 1, "id": "B", "findings": [], "kind": "information"},
                    {"key": 3, "id": "D", "findings": [], "kind": "requirement"},
                    {"key": 2, "id": "C", "findings": [], "kind": "maybe"},
                ]
            }
        )
    )
    d, problems = merge(d, [review])
    cls = [r.get("classification") for r in d["requirements"]]
    assert "classification" not in d["requirements"][0]  # obligation verb wins
    assert cls[1] == {"model": "haiku", "kind": "information"}
    assert cls[2] == {"model": "input", "kind": "information", "score": 1.0}
    assert cls[3] == {"model": "haiku", "kind": "requirement"}
    assert d["summary"]["graded"] == 2
    assert len(problems) == 2 and all("kind" in p for p in problems)


def test_duplicate_ids_get_their_own_review(tmp_path):
    d = report(
        check(
            [
                Requirement("12", "The ECU shall start quickly.", "modA.csv"),
                Requirement("12", "The ECU shall never stop.", "modB.csv"),
            ],
            "en",
        )
    )
    [path] = batches(d, tmp_path)
    keys = [r["key"] for r in json.loads(path.read_text())["requirements"]]
    review = tmp_path / "batch-001.review.json"
    review.write_text(
        json.dumps(
            {
                "reviews": [
                    {
                        "key": keys[0],
                        "id": "12",
                        "findings": [
                            {"index": 0, "rule": "vague-term", "verdict": "dismissed"}
                        ],
                        "question": "Q for modA",
                    }
                ]
            }
        )
    )
    d, problems = merge(d, [review])
    a, b = d["requirements"]
    assert problems == []
    assert (
        a["review"] == {"model": "haiku", "question": "Q for modA"}
        and a["findings"][0]["dismissed"]
    )
    assert "review" not in b and "dismissed" not in b["findings"][0]


def test_review_with_mismatched_id_is_rejected(tmp_path):
    d = doc()
    review = tmp_path / "r.review.json"
    review.write_text(
        json.dumps(
            {
                "reviews": [
                    {
                        "key": 0,
                        "id": "B",
                        "findings": [{"index": 0, "verdict": "dismissed"}],
                    }
                ]
            }
        )
    )
    d, problems = merge(d, [review])
    assert len(problems) == 1 and "dismissed" not in d["requirements"][0]["findings"][0]


def test_batches_removes_files_from_a_previous_run(tmp_path):
    for name in ("batch-007.json", "batch-007.review.json"):
        (tmp_path / name).write_text("{}")
    (tmp_path / "notes.txt").write_text("keep")
    paths = batches(doc(), tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [p.name for p in paths] + ["notes.txt"]
    )


def test_zero_items_read_exits_2(tmp_path, capsys):
    src = tmp_path / "s.md"
    src.write_text("# Spec\n\nThe ECU shall start quickly.\n")
    assert main(["check", str(src)]) == 2
    assert "no requirements" in capsys.readouterr().err.lower()


def test_unreadable_input_exits_2(tmp_path, capsys):
    src = tmp_path / "s.csv"
    src.write_text("ID,Foo\n1,x\n")
    assert main(["check", str(src)]) == 2
    assert "no text column" in capsys.readouterr().err


def test_verdict_for_a_different_rule_is_rejected(tmp_path):
    # reviews from an earlier run: same key and id, but finding 0 is now another rule
    d = doc()
    review = tmp_path / "r.review.json"
    review.write_text(
        json.dumps(
            {
                "reviews": [
                    {
                        "key": 1,
                        "id": "B",
                        "findings": [
                            {"index": 0, "rule": "absolute", "verdict": "dismissed"}
                        ],
                    }
                ]
            }
        )
    )
    d, problems = merge(d, [review])
    assert len(problems) == 1 and "dismissed" not in d["requirements"][1]["findings"][0]


@pytest.mark.parametrize(
    "name,content",
    [
        ("bad.reqif", b"<REQ-IF><broken"),
        ("bad.reqifz", b"not a zip"),
        ("missing.md", None),
    ],
)
def test_broken_input_exits_2(tmp_path, capsys, name, content):
    src = tmp_path / name
    if content is not None:
        src.write_bytes(content)
    assert main(["check", str(src)]) == 2
    assert "error:" in capsys.readouterr().err


def test_fail_on_exits_1_and_output_folder_is_created(tmp_path):
    src = tmp_path / "s.md"
    src.write_text("- REQ-1: The controller shall start quickly.\n")
    out = tmp_path / "new" / "results.json"
    assert main(["check", str(src), "-o", str(out), "--fail-on", "B"]) == 1
    assert main(["check", str(src), "--fail-on", "C"]) == 0
    assert out.exists()


def test_fail_on_ignores_items_without_findings(tmp_path):
    src = tmp_path / "s.md"
    src.write_text("- REQ-1: The controller shall start within 200 ms.\n")
    assert main(["check", str(src), "--fail-on", "A"]) == 0


def test_batch_size_below_1_is_a_usage_error(tmp_path):
    results = tmp_path / "r.json"
    results.write_text(json.dumps(doc()))
    with pytest.raises(SystemExit) as e:
        main(["batches", str(results), "--out", str(tmp_path), "--size", "0"])
    assert e.value.code == 2


def test_nothing_graded_exits_2(tmp_path, capsys):
    from test_readers import REQIF_META

    # keep only the heading object: everything is information
    src = tmp_path / "h.reqif"
    src.write_text(
        REQIF_META.split("<SPEC-OBJECTS>")[0]
        + "<SPEC-OBJECTS>"
        + REQIF_META[REQIF_META.index('<SPEC-OBJECT IDENTIFIER="o-h">') :].split(
            '<SPEC-OBJECT IDENTIFIER="o-x">'
        )[0]
        + "</SPEC-OBJECTS></REQ-IF-CONTENT></CORE-CONTENT></REQ-IF>",
        encoding="utf-8",
    )
    assert main(["check", str(src), "--fail-on", "D"]) == 2
    assert "nothing graded" in capsys.readouterr().err.lower()


def test_input_kind_is_classification_and_obligation_verb_wins():
    reqs = [
        Requirement("A", "Die Position liefert der Hall-Sensor.", kind="information"),
        Requirement(
            "B", "Hinweis: das Steuergerät muss schnell starten.", kind="information"
        ),
        Requirement("C", "The ECU shall start quickly.", kind="requirement"),
    ]
    d = report(check(reqs, "auto", item_only("customer")), item_only("customer"))
    kinds = [r["classification"] for r in d["requirements"]]
    assert kinds[0] == {"model": "input", "kind": "information", "score": 1.0}
    assert kinds[1]["kind"] == "requirement" and kinds[1]["model"] == "obligation verb"
    assert kinds[2] == {"model": "input", "kind": "requirement", "score": 1.0}
    assert d["summary"]["graded"] == 2
