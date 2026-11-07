"""Deferred minor findings from the final branch review."""

import pytest
from conftest import item_only

from speclint import profiles
from speclint.checks import RULES, Requirement, check, detect_lang, report
from speclint.profiles import load_profile


def test_terse_german_item_in_an_english_majority_spec_is_german():  # M1
    reqs = [
        Requirement("A", "The ECU shall start within 200 ms."),
        Requirement("B", "The ECU shall log errors."),
        Requirement("C", "Versorgungsspannung höchstens 1,5 V."),
    ]
    assert detect_lang(reqs[2].text) == "de"
    assert [r.lang for r in check(reqs, "auto", item_only("customer"))] == [
        "en",
        "en",
        "de",
    ]


def test_german_single_thought_starts_at_the_second_modal():  # M2
    p = item_only("system")
    text = (
        "Das Steuergerät muss den Fehler speichern und darf das Gateway nicht wecken."
    )
    (r,) = check([Requirement("A", text)], "de", p)
    (f,) = [f for f in r.findings if f.rule == "single-thought"]
    assert f.match.startswith("darf") and text[f.start : f.end] == f.match


@pytest.mark.parametrize(
    "body,msg",
    [
        ('rules = "vague-term"', "rules must be a list"),
        ('enable = "vague-term"', "enable must be a list"),
        ('extends = ["customer"]', "extends must be a profile name"),
        ('severity = "error"', "severity must be a table"),
    ],
)
def test_profile_type_errors_have_clear_messages(tmp_path, body, msg):  # M3
    f = tmp_path / "x.toml"
    f.write_text(f"[profile]\n{body}\n")
    with pytest.raises(ValueError, match=msg):
        load_profile(str(f))


def test_cycle_message_follows_the_extends_chain(monkeypatch):  # M3
    monkeypatch.setitem(
        RULES,
        "profiles",
        {"a": {"extends": "b"}, "b": {"extends": "c"}, "c": {"extends": "a"}},
    )
    with pytest.raises(ValueError, match="a -> b -> c -> a"):
        profiles.load_profile("a")


@pytest.mark.parametrize(
    "text",
    [
        "Das Steuergerät muss alle Ein-/Ausgänge überwachen.",
        "Der Lade-/Entladestrom muss gemessen werden.",
    ],
)
def test_german_hyphen_pairs_are_not_oblique(text):  # M4
    (r,) = check([Requirement("A", text)], "de", item_only("system"))
    assert "oblique" not in [f.rule for f in r.findings]


def test_hyphen_compound_is_not_an_acronym_expansion():  # M5
    p = load_profile("customer")
    reqs = [
        Requirement("A", "ECU-Software muss starten."),
        Requirement("B", "The ECU shall log errors."),
    ]
    doc = report(check(reqs, "auto", p), p)
    assert any(
        f["rule"] == "undefined-acronym" for f in doc["requirements"][1]["findings"]
    )


@pytest.mark.parametrize(
    "gloss", ["ECU – Steuergerät", "ECU: Electronic Control Unit", "ECU - Steuergerät"]
)
def test_glossary_lines_still_expand(gloss):  # M5
    p = load_profile("customer")
    reqs = [Requirement("A", gloss), Requirement("B", "The ECU shall log errors.")]
    doc = report(check(reqs, "auto", p), p)
    assert not any(
        f["rule"] == "undefined-acronym"
        for r in doc["requirements"]
        for f in r["findings"]
    )
