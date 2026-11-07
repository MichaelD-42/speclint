import json

from speclint.checks import Requirement, check, report
from speclint.profiles import load_profile
from speclint.review import batches


def doc(*texts, profile="system", lang="auto"):
    p = load_profile(profile)
    reqs = [Requirement(str(i), t) for i, t in enumerate(texts)]
    return report(check(reqs, lang, p), p)


def run(*texts, **kw):
    return doc(*texts, **kw)["requirements"]


def hits(r, rule):
    return [f for f in r["findings"] if f["rule"] == rule]


def test_duplicates_point_at_each_other():
    a, b, c = run(
        "The ECU shall store the last ten errors in memory.",
        "The ECU shall store the last ten errors in memory!",
        "The ECU shall start within 200 ms.",
    )
    (da,) = hits(a, "duplicate")
    assert da["related"] == [{"key": 1, "id": "1"}] and da["match"] == a["text"]
    assert [f["related"] for f in hits(b, "duplicate")] == [[{"key": 0, "id": "0"}]]
    assert not hits(c, "duplicate")


def test_duplicate_ids_across_files_resolve_by_key():
    p = load_profile("system")
    text = "The ECU shall store the last ten errors in memory."
    reqs = [Requirement("R-1", text, "a.csv"), Requirement("R-1", text, "b.csv")]
    a, _ = report(check(reqs, "en", p), p)["requirements"]
    assert hits(a, "duplicate")[0]["related"] == [{"key": 1, "id": "R-1"}]


def test_short_items_are_not_duplicates():
    assert not any(hits(r, "duplicate") for r in run("Overview.", "Overview."))


def test_unexpanded_acronym_on_every_item_and_expanded_one_not():
    a, b, c = run(
        "The HVB shall report its state.",
        "The HVB shall report errors.",
        "The Electronic Control Unit (ECU) shall start. The ECU shall log.",
    )
    assert [f["match"] for f in hits(a, "undefined-acronym")] == ["HVB"]
    assert [f["related"] for f in hits(a, "undefined-acronym")] == [
        [{"key": 1, "id": "1"}]
    ]
    assert hits(b, "undefined-acronym")
    assert not hits(c, "undefined-acronym")


def test_glossary_item_expands_an_acronym():
    rs = run("ECU: Electronic Control Unit", "The ECU shall start.")
    assert not any(hits(r, "undefined-acronym") for r in rs)


def test_caps_keywords_and_units_are_not_acronyms():
    r = run("The ECU SHALL NOT store more than 2 MB.", "ECU: Electronic Control Unit")[
        0
    ]
    assert not hits(r, "undefined-acronym")


def test_item_ids_are_not_acronyms():
    p = load_profile("system")
    reqs = [Requirement("LH", "See LH for the overview.")]
    (r,) = report(check(reqs, "en", p), p)["requirements"]
    assert not hits(r, "undefined-acronym")


def test_decimal_format_flags_the_minority_within_one_language():
    a, b, c = run(
        "Die Spannung muss 1,5 V betragen.",
        "Der Strom muss 2,5 A betragen.",
        "Die Zeit muss 0.5 s betragen.",
        lang="de",
    )
    assert [f["match"] for f in hits(c, "decimal-format")] == ["0.5"]
    assert not hits(a, "decimal-format") and not hits(b, "decimal-format")


def test_bilingual_spec_and_section_numbers_are_not_decimal_findings():
    rs = run(
        "The voltage shall be 1.5 V max.",
        "Die Spannung muss max. 1,5 V betragen.",
        "Siehe Abschnitt 4.1 und 3,2 Seiten.",
    )
    assert not any(hits(r, "decimal-format") for r in rs)


def test_unit_system_flags_the_minority():
    a, _, c = run(
        "The housing shall be at most 20 mm wide.",
        "The cable shall be at most 300 mm long.",
        "The display shall be at most 7 inch wide.",
    )
    assert [f["match"] for f in hits(c, "unit-system")] == ["7 inch"]
    assert not hits(a, "unit-system")


def test_customer_profile_runs_acronyms_and_duplicates_only():
    d = doc(
        "The HVB shall be 1.5 V max.", "Das HVB muss 1,5 V haben.", profile="customer"
    )
    assert "undefined-acronym" in d["rules"] and "duplicate" in d["rules"]
    assert "decimal-format" not in d["rules"] and "unit-system" not in d["rules"]


def test_batches_carry_related_text(tmp_path):
    d = doc(
        "The ECU shall store the last ten errors in memory.",
        "The ECU shall store the last ten errors in memory!",
    )
    (path, *_) = batches(d, tmp_path)
    first = json.loads(path.read_text())["requirements"][0]
    (dup,) = [f for f in first["findings"] if f["rule"] == "duplicate"]
    assert dup["related"] == [
        {"id": "1", "text": "The ECU shall store the last ten errors in memory!"}
    ]


def test_text_report_names_related_items(tmp_path, capsys):
    from speclint.cli import main

    src = tmp_path / "s.md"
    src.write_text(
        "- R-1: The ECU shall store the last ten errors in memory.\n"
        "- R-2: The ECU shall store the last ten errors in memory!\n"
    )
    main(["check", str(src)])
    out = capsys.readouterr().out
    assert "duplicate" in out and "(also R-2)" in out and "(also R-1)" in out
