import pytest

from speclint.checks import Requirement, check, report
from speclint.cli import main
from speclint.ears import ears_pattern
from speclint.profiles import load_profile


@pytest.mark.parametrize(
    "lang,text,pattern",
    [
        ("en", "The ECU shall store the error.", "ubiquitous"),
        ("en", "When the ignition is switched on, the ECU shall start.", "event"),
        ("en", "While the vehicle is moving, the ECU shall lock the doors.", "state"),
        (
            "en",
            "If the voltage drops below 9 V, then the ECU shall enter safe state.",
            "unwanted",
        ),
        ("en", "Where a sunroof is fitted, the ECU shall close it.", "optional"),
        (
            "en",
            "While the vehicle is moving, when a door opens, the ECU shall warn the driver.",
            "complex",
        ),
        ("de", "Das Steuergerät muss den Fehler speichern.", "ubiquitous"),
        (
            "de",
            "Wenn die Zündung eingeschaltet wird, muss das Steuergerät starten.",
            "event",
        ),
        (
            "de",
            "Solange das Fahrzeug fährt, muss das Steuergerät die Türen verriegeln.",
            "state",
        ),
        (
            "de",
            "Falls die Spannung unter 9 V fällt, dann muss das Steuergerät in den sicheren Zustand wechseln.",
            "unwanted",
        ),
        (
            "de",
            "Sofern ein Schiebedach verbaut ist, muss das Steuergerät es schließen.",
            "optional",
        ),
    ],
)
def test_patterns(lang, text, pattern):
    assert ears_pattern(text, lang) == (pattern, None)


@pytest.mark.parametrize(
    "lang,text,match",
    [
        ("en", "The ECU must store the error.", "The"),  # no shall
        (
            "en",
            "The ECU shall start when the ignition is on.",
            "when the ignition is on",
        ),  # condition after the response
        (
            "en",
            "If the voltage drops, the ECU shall enter safe state.",
            "If",
        ),  # no then
        ("en", "The ECU shall start and shall log.", "shall"),  # second shall
        ("en", "After start-up, the ECU shall log.", "After"),  # unknown preamble
        ("de", "Das Steuergerät soll starten.", "Das"),
        (
            "de",
            "Das Steuergerät muss starten, wenn die Zündung an ist.",
            "wenn die Zündung an ist",
        ),
    ],
)
def test_non_conforming(lang, text, match):
    pattern, f = ears_pattern(text, lang)
    assert pattern == "non-conforming" and f.rule == "ears-nonconforming"
    assert f.match == match and text[f.start : f.end] == f.match


def test_second_shall_points_at_the_second_one():
    text = "The ECU shall start and shall log."
    _, f = ears_pattern(text, "en")
    assert f.start == text.rindex("shall")


def test_ears_flag_adds_pattern_and_summary():
    p = load_profile("customer", ears=True)
    reqs = [
        Requirement("A", "The controller shall start."),
        Requirement("B", "The controller must start."),
    ]
    doc = report(check(reqs, "en", p), p)
    assert doc["requirements"][0]["ears"] == {"pattern": "ubiquitous"}
    assert doc["summary"]["ears"] == {"ubiquitous": 1, "non-conforming": 1}
    b = doc["requirements"][1]
    assert [f["rule"] for f in b["findings"]] == ["ears-nonconforming"]
    assert b["grade"] == "B" and doc["profile"]["ears"] is True


def test_without_ears_flag_no_ears_fields():
    doc = report(check([Requirement("A", "The controller must start.")], "en"))
    assert "ears" not in doc["requirements"][0] and "ears" not in doc["summary"]
    assert "ears-nonconforming" not in doc["rules"]


def test_cli_ears_prints_pattern_mix(tmp_path, capsys):
    src = tmp_path / "s.md"
    src.write_text(
        "- R-1: The controller shall start.\n- R-2: The controller must start.\n"
    )
    main(["check", str(src), "--ears"])
    out = capsys.readouterr().out
    assert out.startswith("Profile: customer, EARS\n")
    assert "EARS: ubiquitous:1  non-conforming:1" in out


def test_ears_output_matches_schema():
    from test_schema import validate

    p = load_profile("system", ears=True)
    reqs = [
        Requirement("A", "When the ignition is on, the controller shall start."),
        Requirement("B", "The controller shall start when the ignition is on."),
    ]
    validate(report(check(reqs, "en", p), p))


def test_german_message_uses_the_german_template():
    _, f = ears_pattern("Dies muss mit Genauigkeit erfolgen.", "de")
    assert "das <System> muss" in f.message
