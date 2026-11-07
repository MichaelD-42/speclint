"""Regressions from the final branch review."""

import json

import pytest

from speclint.checks import Requirement, check, report
from speclint.cli import main
from speclint.ears import ears_pattern
from speclint.profiles import load_profile


def findings(texts, profile="system", ears=False, lang="auto"):
    p = load_profile(profile, ears)
    reqs = [Requirement(f"R-{i}", t) for i, t in enumerate(texts)]
    return [
        (f["rule"], f["match"])
        for r in report(check(reqs, lang, p), p)["requirements"]
        for f in r["findings"]
    ]


def test_merge_cli_exits_0_and_reports_new_summary(tmp_path, capsys):  # C1
    src = tmp_path / "s.md"
    src.write_text("- R-1: The controller shall start quickly.\n")
    results = tmp_path / "r.json"
    main(["check", str(src), "-o", str(results)])
    review = tmp_path / "x.review.json"
    review.write_text('{"reviews": []}')
    capsys.readouterr()
    assert main(["merge", str(results), str(review)]) == 0
    assert "need clarification" in capsys.readouterr().out


def test_merge_of_results_without_profile_does_not_crash(tmp_path):  # I7
    src = tmp_path / "s.md"
    src.write_text("- R-1: The controller shall start quickly.\n")
    results = tmp_path / "r.json"
    main(["check", str(src), "-o", str(results)])
    doc = json.loads(results.read_text())
    del doc["profile"]
    results.write_text(json.dumps(doc))
    review = tmp_path / "x.review.json"
    review.write_text('{"reviews": []}')
    assert main(["merge", str(results), str(review)]) == 0


@pytest.mark.parametrize(
    "lang,text,pattern",
    [
        (
            "de",
            "Wenn die Spannung unter 1,5 V fällt, muss das Steuergerät den Ausgang abschalten.",
            "event",
        ),  # I1
        (
            "en",
            "When the speed exceeds 1,000 rpm, the system shall limit the torque.",
            "event",
        ),  # I1
        ("de", "Die Ausgänge müssen kurzschlussfest sein.", "ubiquitous"),  # I2
        ("en", "The system shall check if the value is valid.", "ubiquitous"),  # I3
        (
            "en",
            "The system shall store the data after each ignition cycle.",
            "ubiquitous",
        ),  # I3
    ],
)
def test_ears_review_regressions(lang, text, pattern):
    assert ears_pattern(text, lang)[0] == pattern


def test_id_prefix_is_not_an_acronym():  # I4
    p = load_profile("customer")
    reqs = [
        Requirement("LH-001", "Das Steuergerät muss starten."),
        Requirement("LH-002", "Das Steuergerät muss gemäß LH-001 starten."),
    ]
    rules = [
        f["rule"]
        for r in report(check(reqs, "de", p), p)["requirements"]
        for f in r["findings"]
    ]
    assert "undefined-acronym" not in rules


def test_switch_states_are_not_acronyms():  # I5
    hits = findings(
        [
            "Der Schalter muss in Stellung AUS oder EIN stehen.",
            "The switch shall be OFF in position ON.",
        ]
    )
    assert not [m for r, m in hits if r == "undefined-acronym"]


@pytest.mark.parametrize(
    "text",
    [
        "The ECU shall provide one I/O port.",
        "The ECU shall support TCP/IP.",
        "See www.example.com/docs for details.",
    ],
)
def test_caps_pairs_and_hosts_are_not_oblique(text):  # I5
    assert not [m for r, m in findings([text], lang="en") if r == "oblique"]


def test_ears_with_profile_that_disables_ears_rule_does_not_crash(tmp_path):  # I6
    f = tmp_path / "p.toml"
    f.write_text('[profile]\nextends = "system"\ndisable = ["ears-nonconforming"]\n')
    hits = findings(
        ["Das System muss X speichern und muss Y speichern."],
        str(f),
        ears=True,
        lang="de",
    )
    assert ("ears-nonconforming", "muss") in hits
