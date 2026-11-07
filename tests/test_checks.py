import pytest

from speclint.checks import Requirement, check, detect_lang, grade, report, rescore
from speclint.profiles import load_profile


def rules(text, lang, profile="system"):
    return [
        f.rule
        for f in check([Requirement("X", text)], lang, load_profile(profile))[
            0
        ].findings
    ]


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
        ("en", "The ECU shall stop the motor immediately.", "temporal-word"),
        ("de", "Das Steuergerät muss den Motor sofort stoppen.", "temporal-word"),
        (
            "en",
            "The ECU shall log errors in order to support diagnosis.",
            "purpose-phrase",
        ),
        (
            "de",
            "Das Steuergerät muss Fehler speichern, um die Diagnose zu unterstützen.",
            "purpose-phrase",
        ),
        (
            "de",
            "Das Steuergerät muss Fehler speichern, damit die Werkstatt sie auslesen kann.",
            "purpose-phrase",
        ),
        ("en", "The ECU shall be able to store 100 errors.", "superfluous-infinitive"),
        (
            "de",
            "Das Steuergerät muss in der Lage sein, 100 Fehler zu speichern.",
            "superfluous-infinitive",
        ),
        ("en", "The ECU shall wake up unless the battery is low.", "clause-combinator"),
        (
            "de",
            "Das Steuergerät muss aufwachen, es sei denn, die Batterie ist leer.",
            "clause-combinator",
        ),
        (
            "en",
            "The ECU shall store the error and shall notify the gateway.",
            "single-thought",
        ),
        (
            "de",
            "Das Steuergerät muss den Fehler speichern und muss das Gateway informieren.",
            "single-thought",
        ),
        ("en", "The ECU should store the error.", "weak-obligation"),
        ("de", "Das Steuergerät sollte den Fehler speichern.", "weak-obligation"),
        ("de", "Das Steuergerät wird den Fehler speichern.", "weak-obligation"),
        ("de", "Das Steuergerät soll den Fehler speichern.", "soll-obligation"),
        ("en", "The ECU shall report speed/position to the gateway.", "oblique"),
        ("de", "Das Steuergerät muss Drehzahl/Position melden.", "oblique"),
        (
            "en",
            "The ECU shall store the error (including the time stamp and the voltage).",
            "parenthetical",
        ),
        (
            "de",
            "Das Steuergerät muss den Fehler (mit Zeitstempel und Spannung) speichern.",
            "parenthetical",
        ),
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


def f(rule, severity, dismissed=False):
    return {"rule": rule, "severity": severity, "dismissed": dismissed}


def test_grade_caps_and_pileup():
    assert grade([]) == "none"
    assert grade([f("passive-no-actor", "info")]) == "A"
    assert grade([f("vague-term", "warning")]) == "B"
    assert grade([f("escape-clause", "error")]) == "D"
    assert grade([f("vague-term", "warning"), f("absolute", "warning")]) == "C"
    assert grade([f("vague-term", "warning"), f("vague-term", "warning")]) == "B"
    assert (
        grade(
            [
                f("vague-term", "warning"),
                f("passive-no-actor", "info"),
                f("undefined-condition", "info"),
            ]
        )
        == "B"
    )
    assert grade([f("escape-clause", "error"), f("vague-term", "warning")]) == "F"
    assert grade([f(r, "warning") for r in ("a", "b", "c", "d", "e", "g")]) == "F"
    assert grade([f("escape-clause", "error", dismissed=True)]) == "none"


def test_item_grades_and_summary():
    # no acronyms: undefined-acronym is part of the customer profile
    doc = report(
        check(
            [
                Requirement(
                    "X", "The controller shall start within 200 ms where possible."
                ),
                Requirement("Y", "The controller shall start within 200 ms."),
                Requirement("Z", "Dies muss mit ausreichender Genauigkeit erfolgen."),
            ]
        )
    )
    assert [r["grade"] for r in doc["requirements"]] == ["D", "none", "C"]
    s = doc["summary"]
    assert s["needs_clarification"] == 2
    assert s["grades"] == {"A": 0, "B": 0, "C": 1, "D": 1, "F": 0, "none": 1}
    assert s["categories"]["completeness"] == 1
    assert s["categories"]["non_ambiguity"] == 1
    assert "score" not in s and "score" not in doc["requirements"][0]


def test_information_items_are_not_graded():
    doc = report(
        check(
            [
                Requirement("X", "The controller shall start quickly."),
                Requirement("Y", "This chapter is quickly read."),
            ],
            "en",
        )
    )
    doc["requirements"][1]["classification"] = {"kind": "information"}
    s = rescore(doc)["summary"]
    assert (s["requirements"], s["graded"], s["needs_clarification"]) == (2, 1, 1)


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


def test_nothing_graded_gives_empty_summary():
    s = report(check([]))["summary"]
    assert s["graded"] == 0 and set(s["categories"].values()) == {0}


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


def test_um_zu_span_does_not_hide_a_vague_term_inside_it():
    found = rules(
        "Das Steuergerät muss Fehler speichern, um eine schnelle Diagnose zu ermöglichen.",
        "de",
    )
    assert {"purpose-phrase", "vague-term"} <= set(found)


def test_customer_profile_has_temporal_word_but_not_purpose_phrase():
    assert rules(
        "The ECU shall log errors in order to support diagnosis immediately.",
        "en",
        "customer",
    ) == ["temporal-word"]


@pytest.mark.parametrize(
    "lang,text",
    [
        ("en", "The ECU shall store the last will of the user."),  # noun "will"
        ("en", "The ECU shall store the date of 1 May."),  # month
        ("de", "Der Fehler wird vom Steuergerät gespeichert."),  # passive, not future
    ],
)
def test_modal_rules_do_not_fire(lang, text):
    assert not {"weak-obligation", "single-thought"} & set(rules(text, lang))


def test_single_thought_keeps_weak_obligation_visible():
    found = rules("The ECU shall store the error and should notify the gateway.", "en")
    assert {"single-thought", "weak-obligation"} <= set(found)


def test_soll_is_binding_in_customer_profile():
    assert "soll-obligation" not in rules(
        "Das Steuergerät soll den Fehler speichern.", "de", "customer"
    )


@pytest.mark.parametrize(
    "lang,text",
    [
        ("en", "The vehicle shall reach 100 km/h within 10 s ± 1 s."),
        ("en", "The ECU shall accept dates like 12/05 and ratios like 1/2."),
        ("en", "The ECU shall load its firmware from https://host/fw and src/main/fw."),
        ("en", "The ECU shall send and/or log the error."),  # ambiguous-combinator only
        ("de", "Das Steuergerät (ECU) muss starten."),
    ],
)
def test_oblique_and_parenthetical_do_not_fire(lang, text):
    assert not {"oblique", "parenthetical"} & set(rules(text, lang))
