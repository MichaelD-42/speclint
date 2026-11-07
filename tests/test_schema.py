import json
from pathlib import Path

import jsonschema

from speclint.checks import Requirement, check, report
from speclint.cli import main
from speclint.review import merge

SCHEMA = json.loads(
    (Path(__file__).parents[1] / "schema" / "results.schema.json").read_text()
)
REQS = [
    Requirement("A", "Die Daten werden im Fehlerfall ggf. schnell gespeichert."),
    Requirement("B", "The browser shall never display the password."),
    Requirement("C", "Hinweis: Die Position liefert der Hall-Sensor."),
    Requirement("D", "The ECU shall start within 200 ms."),
]


def validate(doc):
    jsonschema.validate(doc, SCHEMA, cls=jsonschema.Draft202012Validator)
    for r in doc["requirements"]:
        for f in r["findings"]:
            assert r["text"][f["start"] : f["end"]] == f["match"], f


def test_schema_is_valid():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_check_and_merge_outputs_match_schema(tmp_path):
    doc = report(check(REQS))
    validate(doc)

    review = tmp_path / "r.review.json"
    review.write_text(
        json.dumps(
            {
                "reviews": [
                    {
                        "key": 1,
                        "id": "B",
                        "findings": [
                            {
                                "index": 0,
                                "rule": "absolute",
                                "verdict": "dismissed",
                                "reason": "verifiable",
                            }
                        ],
                    },
                    {"key": 2, "id": "C", "findings": [], "kind": "information"},
                    {
                        "key": 0,
                        "id": "A",
                        "findings": [
                            {
                                "index": 0,
                                "rule": "passive-no-actor",
                                "verdict": "confirmed",
                            }
                        ],
                        "question": "Welche Daten?",
                        "rewrite": "[TBD]",
                    },
                ]
            }
        )
    )
    doc, problems = merge(doc, [review])
    assert problems == []
    validate(doc)


def test_cli_json_output_matches_schema(tmp_path):
    src = tmp_path / "s.md"
    src.write_text(
        "- REQ-1: Das Steuergerät muss die Daten werden schnell gespeichert.\n- REQ-2: The ECU shall start quickly.\n"
    )
    out = tmp_path / "r.json"
    assert main(["check", str(src), "-o", str(out)]) == 0
    validate(json.loads(out.read_text()))
