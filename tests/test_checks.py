import pytest

from speclint.checks import Requirement, check, detect_lang, grade, report, rescore


def rules(text, lang):
    return [f.rule for f in check([Requirement("X", text)], lang)[0].findings]


@pytest.mark.parametrize(
    "lang,text,rule",
    [
        ("en", "The system shall respond quickly.", "vague-term"),
        (
            "de",
            "Das Steuergerät muss ausreichende Speicherreserven bereitstellen.",
            "vague-term",
        ),  # inflected
        ("de", "Die Reaktionszeit soll ca. 100 ms betragen.", "vague-term"),
        ("en", "The ECU shall start within 200 ms where possible.", "escape-clause"),
        (
            "de",
            "Das Steuergerät soll ggf. einen Neustart durchführen.",
            "escape-clause",
        ),
        ("en", "The HMI shall display speed, gear, etc.", "open-ended"),
        (
            "de",
            "Das HMI muss Signale wie z. B. Geschwindigkeit anzeigen.",
            "open-ended",
        ),
        (
            "en",
            "In case of failure the ECU shall enter safe state.",
            "undefined-condition",
        ),
        (
            "de",
            "Im Fehlerfall muss das Steuergerät in den sicheren Zustand wechseln.",
            "undefined-condition",
        ),
        ("en", "The ECU shall log errors and/or warnings.", "ambiguous-combinator"),
        (
            "de",
            "Das Steuergerät muss den Fehler speichern bzw. melden.",
            "ambiguous-combinator",
        ),
        ("en", "It shall be configurable by the tester.", "unresolved-reference"),
        (
            "de",
            "Das Steuergerät muss dies innerhalb von 10 ms melden.",
            "unresolved-reference",
        ),
        ("en", "Data shall be encrypted.", "passive-no-actor"),
        ("de", "Die Daten müssen gespeichert werden.", "passive-no-actor"),
        ("de", "Die Daten werden durch den CAN-Bus übertragen.", "passive-no-actor"),
        ("en", "The ECU shall always be available.", "absolute"),
        ("de", "Das Steuergerät muss jederzeit erreichbar sein.", "absolute"),
        ("en", "The supply voltage shall be 12 V.", "missing-tolerance"),
        ("de", "Die Versorgungsspannung muss 12 V betragen.", "missing-tolerance"),
    ],
)
def test_rule_fires(lang, text, rule):
    assert rule in rules(text, lang)


@pytest.mark.parametrize(
    "lang,text",
    [
        ("en", "The ECU shall start within 200 ms."),
        ("en", "The supply voltage shall be 12 V ± 0.5 V."),
        ("en", "The supply voltage shall be between 9 V and 16 V."),
        ("en", "Data shall be encrypted by the ECU."),
        (
            "en",
            "The sensor that measures the temperature shall report the value to the ECU.",
        ),
        ("de", "Die Versorgungsspannung muss zwischen 9 V und 16 V liegen."),
        ("de", "Das Steuergerät muss die Daten innerhalb von 10 ms speichern."),
        ("de", "Die Daten müssen vom Steuergerät gespeichert werden."),
        ("de", "Die Spannung darf höchstens 16 V betragen."),
    ],
)
def test_clean_requirement(lang, text):
    assert rules(text, lang) == []


def test_german_expletive_es_is_not_a_pronoun_finding():
    assert "unresolved-reference" not in rules(
        "Es muss sichergestellt werden, dass das Steuergerät startet.", "de"
    )


def test_detect_lang():
    assert detect_lang("Das Steuergerät muss die Daten speichern.") == "de"
    assert detect_lang("The ECU shall store the data.") == "en"


def test_grading():
    doc = report(
        check(
            [
                Requirement("X", "The ECU shall start within 200 ms where possible."),
                Requirement("Y", "The ECU shall start within 200 ms."),
            ],
            "en",
        )
    )
    x = doc["requirements"][0]
    assert x["score"] == 70 and x["grade"] == "C"
    assert x["categories"]["completeness"] == 70 and x["categories"]["accuracy"] == 100
    assert doc["summary"]["score"] == 85 and doc["summary"]["grade"] == "B+"
    assert grade(100) == "A+" and grade(59) == "F"


def test_information_items_are_not_graded():
    doc = report(
        check(
            [
                Requirement("X", "The ECU shall start quickly."),
                Requirement("Y", "This chapter is quickly read."),
            ],
            "en",
        )
    )
    doc["requirements"][1]["classification"] = {"kind": "information"}
    s = rescore(doc)["summary"]
    assert (s["requirements"], s["graded"], s["score"]) == (2, 1, 85)


def test_passive_span_does_not_hide_findings_inside_it():
    # audit 1/9: the passive "werden ... gespeichert" used to swallow everything between its two verbs
    found = rules("Die Daten werden im Fehlerfall ggf. schnell gespeichert.", "de")
    assert sorted(found) == [
        "escape-clause",
        "passive-no-actor",
        "undefined-condition",
        "vague-term",
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Das Steuergerät muss an vielen Stellen messen.",
        "Das Steuergerät muss mit einigen Sensoren arbeiten.",
        "Das Steuergerät muss bei wenigen Fehlern melden.",
    ],
)
def test_inflected_german_vague_quantifiers(text):
    assert "vague-term" in rules(text, "de")


def test_weniger_als_is_a_bound_not_a_vague_term():
    assert rules("Die Reaktionszeit muss weniger als 10 ms betragen.", "de") == []


@pytest.mark.parametrize(
    "lang,text",
    [
        ("de", "Der Strom darf max. 2 A betragen und die Spannung muss 12 V betragen."),
        ("en", "The current shall be at most 2 A and the voltage shall be 12 V."),
    ],
)
def test_bound_on_first_value_does_not_cover_the_next(lang, text):
    assert [
        f.match
        for f in check([Requirement("X", text)], lang)[0].findings
        if f.rule == "missing-tolerance"
    ] == ["12 V"]


def test_nothing_graded_gives_full_category_scores():
    s = report(check([]))["summary"]
    assert s["score"] == 100 and set(s["categories"].values()) == {100}


@pytest.mark.parametrize(
    "lang,text",
    [
        ("en", "The supply voltage shall be 9 V to 16 V."),
        ("de", "Die Versorgungsspannung muss 9 V bis 16 V betragen."),
    ],
)
def test_value_ranges_are_bounded(lang, text):
    assert rules(text, lang) == []


@pytest.mark.parametrize(
    "lang,text",
    [
        ("en", "The ECU shall send data over CAN every 10 ms."),
        ("de", "Das Steuergerät muss den Status über den CAN-Bus alle 10 ms senden."),
        ("de", "Das Steuergerät muss bis zum Abschalten alle 10 ms senden."),
    ],
)
def test_bound_word_far_from_the_value_does_not_bound_it(lang, text):
    assert "missing-tolerance" in rules(text, lang)


@pytest.mark.parametrize(
    "lang,text",
    [
        ("en", "The current shall be max. 2 A."),
        ("en", "The ECU shall start within a maximum of 5 s."),
        ("de", "Das Steuergerät muss innerhalb von 10 ms antworten."),
    ],
)
def test_bound_right_before_the_value(lang, text):
    assert "missing-tolerance" not in rules(text, lang)


def test_item_without_language_hints_takes_the_majority_language():
    results = check(
        [
            Requirement("X", "Das Steuergerät muss die Daten speichern."),
            Requirement("Y", "Versorgungsspannung höchstens 16 V."),
        ]
    )
    assert [r.lang for r in results] == ["de", "de"]
    assert results[1].findings == []


def test_german_agent_only_covers_its_own_passive():
    found = check(
        [
            Requirement(
                "X",
                "Die Daten werden vom Steuergerät gespeichert und die Fehler werden gelöscht.",
            )
        ],
        "de",
    )[0].findings
    assert [(f.rule, f.match) for f in found] == [
        ("passive-no-actor", "werden gelöscht")
    ]


@pytest.mark.parametrize(
    "lang,text",
    [
        ("de", "Die Spannung muss 12 V +10 %/-5 % betragen."),
        ("en", "The supply voltage shall be 12 V +10 %/-5 %."),
    ],
)
def test_asymmetric_tolerance_is_bounded(lang, text):
    assert "missing-tolerance" not in rules(text, lang)


def test_overall_grade_matches_the_reported_score():
    reqs = [Requirement(str(i), "The ECU shall start quickly.") for i in range(99)]
    reqs.append(Requirement("Z", "The ECU shall start quickly. Data shall be stored."))
    s = report(check(reqs, "en"))["summary"]
    assert (s["score"], s["grade"]) == (85.0, "B+")
