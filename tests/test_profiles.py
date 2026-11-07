import pytest

from speclint import profiles
from speclint.checks import RULES, Requirement, check, report
from speclint.cli import main
from speclint.profiles import load_profile

NINE_RULES = [
    "vague-term",
    "missing-tolerance",
    "escape-clause",
    "open-ended",
    "undefined-condition",
    "ambiguous-combinator",
    "unresolved-reference",
    "passive-no-actor",
    "absolute",
]


def test_builtin_customer_has_todays_rules():
    p = load_profile("customer")
    assert p.name == "customer" and set(NINE_RULES) <= set(p.severities)


def test_system_extends_and_overrides_severity():
    assert load_profile("system").severities["passive-no-actor"] == "warning"
    assert load_profile("customer").severities["passive-no-actor"] == "info"


def test_custom_file_extends_enable_disable_severity(tmp_path):
    f = tmp_path / "acme.toml"
    f.write_text(
        '[profile]\nextends = "customer"\ndisable = ["absolute"]\n'
        'severity = { vague-term = "error" }\n'
    )
    p = load_profile(str(f))
    assert p.name == str(f)
    assert "absolute" not in p.severities and p.severities["vague-term"] == "error"


@pytest.mark.parametrize(
    "body",
    [
        'rules = ["no-such-rule"]',
        'severity = { vague-term = "fatal" }',
        'extends = "nope"',
        'enable = ["no-such-rule"]',
    ],
)
def test_bad_custom_profile_raises(tmp_path, body):
    f = tmp_path / "x.toml"
    f.write_text(f"[profile]\n{body}\n")
    with pytest.raises(ValueError):
        load_profile(str(f))


def test_unknown_profile_raises():
    with pytest.raises(ValueError, match="unknown profile"):
        load_profile("nope")


def test_extends_cycle_raises(monkeypatch):
    monkeypatch.setitem(
        RULES, "profiles", {"a": {"extends": "b"}, "b": {"extends": "a"}}
    )
    with pytest.raises(ValueError, match="cycle"):
        profiles.load_profile("a")


def test_disabled_rule_does_not_run_and_profile_is_recorded(tmp_path):
    f = tmp_path / "p.toml"
    f.write_text('[profile]\nextends = "customer"\ndisable = ["absolute"]\n')
    p = load_profile(str(f))
    doc = report(
        check([Requirement("A", "The controller shall never reset.")], "en", p), p
    )
    assert doc["requirements"][0]["findings"] == []
    assert "absolute" not in doc["rules"]
    assert doc["profile"] == {"name": str(f), "ears": False}


def test_severity_override_reaches_finding_and_grade(tmp_path):
    f = tmp_path / "p.toml"
    f.write_text('[profile]\nextends = "customer"\nseverity = { absolute = "error" }\n')
    p = load_profile(str(f))
    doc = report(
        check([Requirement("A", "The controller shall never reset.")], "en", p), p
    )
    r = doc["requirements"][0]
    assert r["findings"][0]["severity"] == "error" and r["grade"] == "D"
    assert doc["rules"]["absolute"]["severity"] == "error"


def test_cli_unknown_profile_exits_2(tmp_path, capsys):
    src = tmp_path / "s.md"
    src.write_text("- R-1: The controller shall start.\n")
    assert main(["check", str(src), "--profile", "nope"]) == 2
    assert "error:" in capsys.readouterr().err


def test_cli_names_the_profile(tmp_path, capsys):
    src = tmp_path / "s.md"
    src.write_text("- R-1: The controller shall start quickly.\n")
    main(["check", str(src), "--profile", "system"])
    assert capsys.readouterr().out.startswith("Profile: system\n")
