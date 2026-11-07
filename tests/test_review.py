import json

import pytest

from speclint.checks import Requirement, check, report
from speclint.cli import main
from speclint.review import batches, merge


def doc():
    return report(
        check(
            [
                Requirement("A", "The browser shall never display the password."),
                Requirement("B", "The ECU shall respond quickly where possible."),
                Requirement("C", "The ECU shall start within 200 ms."),
            ],
            "en",
        )
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
        b["review"] == {"question": "Which max. response time?"}
        and b["findings"][0]["dismissed"] is False
    )
    assert d["summary"]["dismissed"] == 1
    assert (
        len(problems) == 5
    )  # index out of range, bad verdict, unknown id, findings not a list, unreadable file


def test_obligation_verb_overrides_classifier(monkeypatch):
    from speclint import classify as c

    seen = []
    monkeypatch.setattr(
        c,
        "top",
        lambda texts, labels: seen.extend(texts) or [("information", 0.9)] * len(texts),
    )
    d = c.classify(
        report(
            check(
                [
                    Requirement(
                        "A", "Im Fehlerfall sollen die Daten ggf. gespeichert werden."
                    ),
                    Requirement("B", "Hinweis: Die Position liefert der Hall-Sensor."),
                ],
                "de",
            )
        )
    )
    assert [r["classification"]["kind"] for r in d["requirements"]] == [
        "requirement",
        "information",
    ]
    assert seen == [
        "Hinweis: Die Position liefert der Hall-Sensor."
    ]  # model only sees items without obligation verb


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
    assert a["review"] == {"question": "Q for modA"} and a["findings"][0]["dismissed"]
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


def test_nothing_graded_exits_2(tmp_path, monkeypatch, capsys):
    from speclint import classify as c

    monkeypatch.setattr(
        c, "top", lambda texts, labels: [("information", 0.9)] * len(texts)
    )
    src = tmp_path / "s.md"
    src.write_text("- US-1: As a driver I want the window to close quickly.\n")
    assert main(["check", str(src), "--classify", "--fail-on", "D"]) == 2
    assert "nothing graded" in capsys.readouterr().err.lower()
