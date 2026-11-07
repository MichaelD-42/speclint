# Profiles, New Checks, EARS and Grading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the additive score with grade caps, add rule profiles (`customer`, `system`, custom files), 13 new rules (9 single-item, 4 whole-spec), and an `--ears` conformance mode.

**Architecture:** Rule data and profiles live in `rules.toml`. A resolved `Profile` (active rule → effective severity) is passed through `check()` and `report()`. Severity is the grade cap, so `rescore()`/`merge` stay profile-agnostic. Whole-spec checks run after the per-item pass in `check()`, and EARS is computed per item in `check()` when the profile has `ears=True`.

**Tech Stack:** Python 3.12, spaCy (`en_core_web_sm`, `de_core_news_sm`), tomllib, pytest, jsonschema, uv, ruff.

**Spec:** `docs/superpowers/specs/2026-11-07-profiles-checks-ears-design.md`

## Global Constraints

- English and German for every rule; tests in both languages unless a rule is DE-only (`soll-obligation`).
- Every finding keeps `match == text[start:end]` (`tests/test_schema.py::validate` checks it).
- Model output never changes grades except through `merge` dismissals.
- Rule word lists and profiles live in `src/speclint/rules.toml`; no word lists in Python.
- Bad profile input (unknown name, unknown rule, unknown severity, `extends` cycle, missing file) → message on stderr, exit 2.
- Grade scale `A`, `B`, `C`, `D`, `F`, `none`; caps error → D, warning → B, info → A; each distinct warning/error rule beyond the first lowers one letter, floor F.
- Default profile: `customer`.
- Results `schema_version` 2, `$id` `urn:speclint:results:2`.
- Rules throughput on PROMISE stays within ~20% of today's ~950 req/s (`uv run python bench/promise.py`).
- Before each commit: `uv run ruff check . && uv run ruff format src tests bench && uv run pytest`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- A bilingual spec (EN items write "1.5 V", DE items "1,5 V") must not produce `decimal-format` findings: decimals are compared within one language only. Test in Task 6.
- All-caps keywords and units (SHALL, NOT, MUSS, NICHT, MB) must not become `undefined-acronym` findings. Test in Task 6.
- Section numbers ("siehe Abschnitt 4.1", "chapter 3.2") are not decimals: only a number followed by a unit counts. Test in Task 6.
- The same ID in two input files: `related` must point at the right item by `key`, not by `id`. Test in Task 6.
- URLs and paths ("https://host/path", "src/main") must not produce `oblique` findings. Test in Task 5.

---

### Task 1: Grade caps instead of the additive score

**Files:**
- Modify: `src/speclint/checks.py` (`PENALTY`, `GRADES`, `grade`, `score`, `rescore`)
- Modify: `src/speclint/rules.toml` (new `[grading]` table)
- Modify: `src/speclint/cli.py` (`text_report`, `--fail-under` → `--fail-on`)
- Modify: `schema/results.schema.json`, `bench/promise.py`, `README.md` (grading paragraph, `--fail-under` lines), `skills/speclint/SKILL.md` (answer format, `--fail-under` line)
- Test: `tests/test_checks.py`, `tests/test_review.py`, `tests/test_schema.py`

**Interfaces:**
- Produces: `GRADES: list[str] = ["A", "B", "C", "D", "F"]`; `NONE = "none"`; `grade(findings: list[dict]) -> str` (reads `severity`, `rule`, `dismissed`); `rescore(doc: dict) -> dict` sets `r["grade"]` per item and `doc["summary"]` = `{requirements, graded, needs_clarification, grades, categories, rules, dismissed}` where `grades` has keys `A..F` and `none`, and `categories` is `{category: active finding count}` over graded items. `score()`, `r["score"]`, `r["categories"]`, `summary.score/grade/with_findings` are removed.
- `rules.toml`: `[grading] caps = { error = "D", warning = "B", info = "A" }`, `pileup_step = 1`.

- [ ] **Step 1: Write the failing tests** (replace `test_grading`, `test_information_items_are_not_graded`, `test_nothing_graded_gives_full_category_scores`, delete `test_overall_grade_matches_the_reported_score`)

```python
def f(rule, severity, dismissed=False):
    return {"rule": rule, "severity": severity, "dismissed": dismissed}

def test_grade_caps_and_pileup():
    assert grade([]) == "none"
    assert grade([f("passive-no-actor", "info")]) == "A"
    assert grade([f("vague-term", "warning")]) == "B"
    assert grade([f("escape-clause", "error")]) == "D"
    assert grade([f("vague-term", "warning"), f("absolute", "warning")]) == "C"
    assert grade([f("vague-term", "warning"), f("vague-term", "warning")]) == "B"
    assert grade([f("vague-term", "warning"), f("passive-no-actor", "info"), f("undefined-condition", "info")]) == "B"
    assert grade([f("escape-clause", "error"), f("vague-term", "warning")]) == "F"
    assert grade([f(r, "warning") for r in ("a", "b", "c", "d", "e", "g")]) == "F"
    assert grade([f("escape-clause", "error", dismissed=True)]) == "none"

def test_item_grades_and_summary():
    doc = report(check([  # no acronyms: Task 6 adds undefined-acronym to customer
        Requirement("X", "The controller shall start within 200 ms where possible."),
        Requirement("Y", "The controller shall start within 200 ms."),
        Requirement("Z", "Dies muss mit ausreichender Genauigkeit erfolgen."),
    ]))
    assert [r["grade"] for r in doc["requirements"]] == ["D", "none", "C"]
    s = doc["summary"]
    assert s["needs_clarification"] == 2
    assert s["grades"] == {"A": 0, "B": 0, "C": 1, "D": 1, "F": 0, "none": 1}
    assert s["categories"]["completeness"] == 1 and s["categories"]["non_ambiguity"] == 1
    assert "score" not in s and "score" not in doc["requirements"][0]

def test_information_items_are_not_graded():  # same setup as today
    ...
    assert (s["requirements"], s["graded"], s["needs_clarification"]) == (2, 1, 1)

def test_nothing_graded_gives_empty_summary():
    s = report(check([]))["summary"]
    assert s["graded"] == 0 and set(s["categories"].values()) == {0}
```

In `tests/test_review.py`: `test_merge_dismisses_rescores_and_rejects_garbage` asserts `d["requirements"][0]["grade"] == "B"` before and `a["grade"] == "none"` after the dismissal. Replace `test_fail_under_exits_1_…` with:

```python
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
```

`test_nothing_graded_exits_2` swaps `--fail-under 80` for `--fail-on D`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_checks.py tests/test_review.py -q`
Expected: FAIL (`grade()` takes a score, `needs_clarification` missing, `--fail-on` unknown)

- [ ] **Step 3: Implement**

`grade(findings)`: active = not dismissed. No active → `NONE`. Base = worst cap over active severities (order in `GRADES`). Steps = number of distinct `rule` among active warning/error findings minus 1 (min 0), times `pileup_step`. Result index = min(base index + steps, index of "F"). `rescore`: drop the numeric fields, fill the summary per Interfaces. `GRADES`/`PENALTY` tuples go; `PENALTY` is removed. `--fail-on` choices `GRADES`; exit 1 when any graded item (not `none`, not information) has `GRADES.index(grade) >= GRADES.index(fail_on)`. Text report: item tag `[C]`, and `[no findings]` with `-v`. The summary block is `"{graded} graded items, {needs_clarification} need clarification."`, then `Grades: A:n B:n … no findings:n` (non-zero only), then `Findings per category:` with one line per category and its count. Schema: requirement `grade` enum adds `none`; drop `score`/`categories` from requirement and `score`/`grade`/`with_findings` from summary; add `needs_clarification`; summary `categories` values are integers; `schema_version` const 2; `$id` `urn:speclint:results:2`; `meanScore`/`score` defs removed. `bench/promise.py` prints `summary["grades"]` instead of "Overall … (%)". README: replace the "Each item starts at 100 …" paragraph with the cap rules and the example output block, and `--fail-under 80` with `--fail-on D`. SKILL.md step 4: lead with the needs-clarification count and grade distribution; no score.

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass

- [ ] **Step 5: Commit** — `feat: grade caps and pile-up instead of additive score`

---

### Task 2: Profiles

**Files:**
- Create: `src/speclint/profiles.py`
- Modify: `src/speclint/rules.toml` (`[profiles.customer]`, `[profiles.system]`)
- Modify: `src/speclint/checks.py` (`check_doc`, `check`, `report`)
- Modify: `src/speclint/cli.py` (`--profile`, `--ears` flag parsed and stored; EARS logic comes in Task 7), `schema/results.schema.json` (top-level `profile`), `README.md` (profiles section), `skills/speclint/SKILL.md` (customer vs system, grades not comparable across profiles)
- Test: `tests/test_profiles.py`

**Interfaces:**
- Produces: `@dataclass Profile: name: str; severities: dict[str, str]; ears: bool = False` and `load_profile(spec: str = "customer", ears: bool = False) -> Profile` (raises `ValueError` on bad input) in `profiles.py`.
- `check(reqs, lang="auto", profile: Profile | None = None) -> list[Result]` (None → `load_profile()`), only active rules run. `report(results, profile: Profile | None = None) -> dict` writes each finding's severity from `profile.severities`, `doc["rules"]` only for active rules with effective severity, `doc["profile"] = {"name": ..., "ears": ...}`.
- Built-ins now: `customer.rules` = today's nine rules; `system` = `extends = "customer"`, `severity = { passive-no-actor = "warning" }`. Tasks 3–6 append their rules to these lists as given in the spec's profile block.

- [ ] **Step 1: Write the failing tests** in `tests/test_profiles.py`

```python
def test_builtin_customer_has_todays_rules():
    p = load_profile("customer")
    assert p.name == "customer" and set(p.severities) == set(NINE_RULES)

def test_system_extends_and_overrides_severity():
    assert load_profile("system").severities["passive-no-actor"] == "warning"

def test_custom_file_extends_enable_disable_severity(tmp_path):
    f = tmp_path / "acme.toml"
    f.write_text('[profile]\nextends = "customer"\ndisable = ["absolute"]\nseverity = { vague-term = "error" }\n')
    p = load_profile(str(f))
    assert p.name == str(f) and "absolute" not in p.severities and p.severities["vague-term"] == "error"

@pytest.mark.parametrize("body", [
    'rules = ["no-such-rule"]',
    'severity = { vague-term = "fatal" }',
    'extends = "nope"',
])
def test_bad_custom_profile_raises(tmp_path, body):
    f = tmp_path / "x.toml"; f.write_text(f"[profile]\n{body}\n")
    with pytest.raises(ValueError):
        load_profile(str(f))

def test_extends_cycle_raises(monkeypatch):  # patch RULES["profiles"] with a→b→a
    ...
    with pytest.raises(ValueError, match="cycle"):
        load_profile("a")

def test_disabled_rule_does_not_run_and_profile_is_recorded(tmp_path):
    f = tmp_path / "p.toml"; f.write_text('[profile]\nextends = "customer"\ndisable = ["absolute"]\n')
    doc = report(check([Requirement("A", "The ECU shall never reset.")], "en", load_profile(str(f))), load_profile(str(f)))
    assert doc["requirements"][0]["findings"] == [] and "absolute" not in doc["rules"]
    assert doc["profile"] == {"name": str(f), "ears": False}

def test_cli_unknown_profile_exits_2(tmp_path, capsys):
    src = tmp_path / "s.md"; src.write_text("- R-1: The ECU shall start.\n")
    assert main(["check", str(src), "--profile", "nope"]) == 2
    assert "error:" in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/test_profiles.py -q`, expected ImportError.

- [ ] **Step 3: Implement**

`load_profile`: a built-in name looks up `RULES["profiles"][spec]`; otherwise, if `Path(spec).is_file()`, read `tomllib` `["profile"]`; else `ValueError(f"unknown profile {spec!r}")`. Resolve recursively: start from the `extends` result (a seen-set detects cycles → `ValueError("profile extends cycle: …")`), then `rules` replaces the set if given, `enable` adds, `disable` removes, and `severity` overrides. Each rule's base severity is `RULES["rules"][r]["severity"]`. Validate names against `RULES["rules"]` and severities against `{"error","warning","info"}`. `check_doc(doc, lang, active: set[str])` skips inactive rules, including `_missing_tolerance`/`_passive_no_actor`. CLI: `--profile` (default `"customer"`), `--ears` (store_true); call `load_profile(a.profile, a.ears)` inside the existing `try` so `ValueError` exits 2. The text report's first line is `Profile: <name>` (+ `, EARS` when set). Schema: required top-level `profile` object `{name: string, ears: boolean}`.

- [ ] **Step 4: Run tests** — `uv run pytest -q`, all pass.

- [ ] **Step 5: Commit** — `feat: rule profiles (customer, system, custom files)`

---

### Task 3: Phrase-list rules (temporal-word, purpose-phrase, superfluous-infinitive, clause-combinator)

**Files:**
- Modify: `src/speclint/rules.toml` (four `[rules.*]` tables; add `temporal-word` to `customer.rules`, the other three to `system.enable`)
- Modify: `src/speclint/checks.py` (DE `um … zu` for purpose-phrase; spanning-rule exemption)
- Modify: `README.md` ("What it checks")
- Test: `tests/test_checks.py`

**Interfaces:**
- Consumes: `load_profile("system")` from Task 2. Change the test helper to `rules(text, lang, profile="system")` and run `check([...], lang, load_profile(profile))`. If a pre-existing "clean" test text now triggers a new rule: when the finding is correct, change the text; when it isn't, the rule is wrong, so fix the rule, not the test.
- Produces: rule keys `temporal-word` (accuracy, R35, warning), `purpose-phrase` (non_ambiguity, R20, info), `superfluous-infinitive` (accuracy, R10, warning), `clause-combinator` (non_ambiguity, R19, warning). Word lists as in the spec table. "zeitnah"/"schnellstmöglich" stay only in `vague-term`.

- [ ] **Step 1: Write the failing tests** — add to the `test_rule_fires` parametrization:

```python
("en", "The ECU shall stop the motor immediately.", "temporal-word"),
("de", "Das Steuergerät muss den Motor sofort stoppen.", "temporal-word"),
("en", "The ECU shall log errors in order to support diagnosis.", "purpose-phrase"),
("de", "Das Steuergerät muss Fehler speichern, um die Diagnose zu unterstützen.", "purpose-phrase"),
("de", "Das Steuergerät muss Fehler speichern, damit die Werkstatt sie auslesen kann.", "purpose-phrase"),
("en", "The ECU shall be able to store 100 errors.", "superfluous-infinitive"),
("de", "Das Steuergerät muss in der Lage sein, 100 Fehler zu speichern.", "superfluous-infinitive"),
("en", "The ECU shall wake up unless the battery is low.", "clause-combinator"),
("de", "Das Steuergerät muss aufwachen, es sei denn, die Batterie ist leer.", "clause-combinator"),
```

```python
def test_um_zu_span_does_not_hide_a_vague_term_inside_it():
    assert {"purpose-phrase", "vague-term"} <= set(rules("Das Steuergerät muss Fehler speichern, um eine schnelle Diagnose zu ermöglichen.", "de"))

def test_customer_profile_has_temporal_word_but_not_purpose_phrase():
    assert rules("The ECU shall log errors in order to support diagnosis immediately.", "en", "customer") == ["temporal-word"]
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/test_checks.py -q`

- [ ] **Step 3: Implement** — TOML entries (EN/DE `phrases`/`lemmas`). DE `um … zu`: a token with `tag_ == "KOUI"` and `lower_ == "um"` → `_span("purpose-phrase", doc, tok, tok.head)`. In the dedupe loop of `check_doc`, replace the `passive-no-actor` special case with a module constant `_SPANNING = {"passive-no-actor", "purpose-phrase", "single-thought"}` (single-thought arrives in Task 4). Spanning findings never block others.

- [ ] **Step 4: Run tests** — `uv run pytest -q`, all pass.

- [ ] **Step 5: Commit** — `feat: temporal, purpose, superfluous-infinitive and combinator rules`

---

### Task 4: Modal rules (single-thought, weak-obligation, soll-obligation)

**Files:**
- Modify: `src/speclint/checks.py` (new `_modals(doc, lang) -> list[Finding]` called from `check_doc`)
- Modify: `src/speclint/rules.toml` (three tables plus the modal word sets; `weak-obligation` → `customer.rules`; `single-thought`, `soll-obligation` → `system.enable`)
- Modify: `README.md`
- Test: `tests/test_checks.py`

**Interfaces:**
- Produces: `single-thought` (non_ambiguity, R18, warning), `weak-obligation` (completeness, "ISO 29148", warning), `soll-obligation` (completeness, "—", info, DE only). TOML word sets: `en.obligation = ["shall","must","should","will"]`, `de.obligation = ["müssen","sollen","dürfen","können"]` (lemmas), `en.weak = ["should","will","may"]`, `de.weak = ["sollte","sollten","kann","können","könnte","könnten"]` (surface forms) plus future "wird/werden", and `de.soll = ["soll","sollen"]`.

- [ ] **Step 1: Write the failing tests**

```python
("en", "The ECU shall store the error and shall notify the gateway.", "single-thought"),
("de", "Das Steuergerät muss den Fehler speichern und muss das Gateway informieren.", "single-thought"),
("en", "The ECU should store the error.", "weak-obligation"),
("de", "Das Steuergerät sollte den Fehler speichern.", "weak-obligation"),
("de", "Das Steuergerät wird den Fehler speichern.", "weak-obligation"),
("de", "Das Steuergerät soll den Fehler speichern.", "soll-obligation"),
```

```python
@pytest.mark.parametrize("lang,text", [
    ("en", "The ECU shall store the last will of the user."),   # noun "will"
    ("en", "The ECU shall store the date of 1 May."),           # month
    ("de", "Der Fehler wird vom Steuergerät gespeichert."),     # passive, not future
])
def test_modal_rules_do_not_fire(lang, text):
    assert not {"weak-obligation", "single-thought"} & set(rules(text, lang))

def test_single_thought_keeps_weak_obligation_visible():
    assert {"single-thought", "weak-obligation"} <= set(rules("The ECU shall store the error and should notify the gateway.", "en"))

def test_soll_is_binding_in_customer_profile():
    assert "soll-obligation" not in rules("Das Steuergerät soll den Fehler speichern.", "de", "customer")
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement `_modals`** — EN: tokens with `tag_ == "MD"`; DE: `tag_ == "VMFIN"`, plus `werden` (`VAFIN`) with a child `VVINF` and dep `oc` as future. Obligation tokens are counted per item; from the second one on, emit `single-thought` as `_span(tok, tok.head)`. Weak and soll emit single-token findings.

- [ ] **Step 4: Run tests** — all pass.

- [ ] **Step 5: Commit** — `feat: single-thought and obligation-strength rules`

---

### Task 5: Pattern rules (oblique, parenthetical)

**Files:**
- Modify: `src/speclint/checks.py` (`_oblique(text) -> list[Finding]`, `_parenthetical(text) -> list[Finding]`)
- Modify: `src/speclint/rules.toml` (two tables + `tolerance.rates = ["km/h","m/s","m/s²","kbit/s","Mbit/s","U/min"]`; both → `system.enable`)
- Modify: `README.md`
- Test: `tests/test_checks.py`

**Interfaces:**
- Produces: `oblique` (non_ambiguity, R17, warning), `parenthetical` (non_ambiguity, R21, info).

- [ ] **Step 1: Write the failing tests**

```python
("en", "The ECU shall report speed/position to the gateway.", "oblique"),
("de", "Das Steuergerät muss Drehzahl/Position melden.", "oblique"),
("en", "The ECU shall store the error (including the time stamp and the voltage).", "parenthetical"),
("de", "Das Steuergerät muss den Fehler (mit Zeitstempel und Spannung) speichern.", "parenthetical"),
```

```python
@pytest.mark.parametrize("lang,text", [
    ("en", "The vehicle shall reach 100 km/h within 10 s ± 1 s."),
    ("en", "The ECU shall accept dates like 12/05 and ratios like 1/2."),
    ("en", "The ECU shall load its firmware from https://host/fw and src/main."),
    ("en", "The ECU shall send and/or log the error."),   # stays ambiguous-combinator only
    ("de", "Das Steuergerät (ECU) muss starten."),
])
def test_oblique_and_parenthetical_do_not_fire(lang, text):
    assert not {"oblique", "parenthetical"} & set(rules(text, lang))
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement** — `_oblique`: match `\S+/\S+` tokens; skip if the token contains `://`, is in `tolerance.rates` or `tolerance.units`, has digits on both sides of the slash, contains a further `/` (a path), or is `and/or`/`und/oder`. The finding spans the token without trailing punctuation. `_parenthetical`: `\(([^()]*)\)` with more than 3 whitespace-separated words inside; the finding spans the parentheses.

- [ ] **Step 4: Run tests** — all pass.

- [ ] **Step 5: Commit** — `feat: oblique and parenthetical rules`

---

### Task 6: Whole-spec rules and `related`

**Files:**
- Create: `src/speclint/spec_checks.py`
- Modify: `src/speclint/checks.py` (`Finding.related`, call `check_spec` at the end of `check`, `report` emits `related`)
- Modify: `src/speclint/rules.toml` (four tables; `known_acronyms`; `tolerance.metric`, `tolerance.imperial`; `undefined-acronym` and `duplicate` → `customer.rules`, `decimal-format` and `unit-system` → `system.enable`)
- Modify: `src/speclint/review.py` (`batches` adds `related` with `id` and `text`), `agents/req-reviewer.md` (one paragraph: whole-spec findings and `related`), `schema/results.schema.json` (finding `related`), `README.md`
- Test: `tests/test_spec_checks.py`

**Interfaces:**
- Consumes: `Result`, `Finding` from `checks.py`; the active rule set from `Profile.severities`.
- Produces: `Finding.related: list[dict] = field(default_factory=list)`, entries `{"key": int, "id": str}` where key is the index in the results list. `check_spec(results: list[Result], active: set[str]) -> None` appends findings in place. Rule keys: `undefined-acronym` (completeness, "R37, R38, R4", info), `decimal-format` (accuracy, R40, info), `unit-system` (accuracy, "R6, R36", warning), `duplicate` (completeness, R30, warning).
- `known_acronyms` starts with: CAN, LIN, USB, LED, SHALL, MUST, SHOULD, NOT, AND, OR, MUSS, SOLL, DARF, KANN, NICHT, UND, ODER, plus everything in `tolerance.units`.
- `tolerance.metric = ["m","mm","cm","km","µm","km/h","m/s","kg","g","t","°C","bar","mbar","Pa","kPa","N","Nm"]`, `tolerance.imperial = ["°F","inch","ft","lb","lbs","mph","psi","gal"]` ("in" is left out: it's an English word).

- Produces also: `SPEC_RULES = {"undefined-acronym", "decimal-format", "unit-system", "duplicate"}` in `spec_checks.py`. Single-item tests must not depend on whole-spec rules: `tests/test_checks.py::rules()` and `tests/test_review.py::doc()` build their profile as `Profile(p.name, {k: v for k, v in p.severities.items() if k not in SPEC_RULES})`. Otherwise every "The ECU shall …" text gains an acronym finding.

- [ ] **Step 1: Write the failing tests** in `tests/test_spec_checks.py` (helper `run(*texts, profile="system", lang="auto")` → `report(check(...))["requirements"]`)

```python
def test_duplicates_point_at_each_other():
    a, b, c = run("The ECU shall store the last ten errors in memory.",
                  "The ECU shall store the last ten errors in memory!",
                  "The ECU shall start within 200 ms.")
    da = [f for f in a["findings"] if f["rule"] == "duplicate"][0]
    assert da["related"] == [{"key": 1, "id": "1"}] and da["match"] == a["text"]
    assert [f["related"] for f in b["findings"] if f["rule"] == "duplicate"] == [[{"key": 0, "id": "0"}]]
    assert not [f for f in c["findings"] if f["rule"] == "duplicate"]

def test_duplicate_ids_across_files_resolve_by_key():  # two Requirement("R-1", same text, source=...)
    ...
    assert dup["related"] == [{"key": 1, "id": "R-1"}]

def test_short_items_are_not_duplicates():
    assert not any(f["rule"] == "duplicate" for r in run("Overview.", "Overview.") for f in r["findings"])

def test_unexpanded_acronym_on_every_item_and_expanded_one_not():
    a, b, c = run("The HVB shall report its state.", "The HVB shall report errors.",
                  "The Electronic Control Unit (ECU) shall start. The ECU shall log.")
    assert [f["match"] for f in a["findings"] if f["rule"] == "undefined-acronym"] == ["HVB"]
    assert [f["related"] for f in a["findings"] if f["rule"] == "undefined-acronym"] == [[{"key": 1, "id": "1"}]]
    assert not [f for f in c["findings"] if f["rule"] == "undefined-acronym"]

def test_glossary_item_expands_an_acronym():
    assert not any(f["rule"] == "undefined-acronym" for r in run("ECU: Electronic Control Unit", "The ECU shall start.") for f in r["findings"])

def test_caps_keywords_and_units_are_not_acronyms():
    (r,) = run("The ECU SHALL NOT store more than 2 MB.", "ECU: Electronic Control Unit")[:1]
    assert not [f for f in r["findings"] if f["rule"] == "undefined-acronym"]

def test_decimal_format_flags_the_minority_within_one_language():
    a, b, c = run("Die Spannung muss 1,5 V betragen.", "Der Strom muss 2,5 A betragen.", "Die Zeit muss 0.5 s betragen.", lang="de")
    assert [f["match"] for f in c["findings"] if f["rule"] == "decimal-format"] == ["0.5"]
    assert not [f for f in a["findings"] if f["rule"] == "decimal-format"]

def test_bilingual_spec_and_section_numbers_are_not_decimal_findings():
    rs = run("The voltage shall be 1.5 V max.", "Die Spannung muss max. 1,5 V betragen.", "Siehe Abschnitt 4.1 und 3,2 Seiten.")
    assert not any(f["rule"] == "decimal-format" for r in rs for f in r["findings"])

def test_unit_system_flags_the_minority():
    a, b, c = run("The housing shall be at most 20 mm wide.", "The cable shall be at most 300 mm long.", "The display shall be at most 7 inch wide.")
    assert [f["match"] for f in c["findings"] if f["rule"] == "unit-system"] == ["7 inch"]

def test_batches_carry_related_text(tmp_path):  # duplicate pair → batch finding has related [{"id","text"}]
    ...
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement `check_spec`** — per spec "New whole-spec rules", with these choices pinned:
  - Duplicates: tokens `re.findall(r"\w+", text.lower())` as sets; skip pairs whose sizes differ so much that Jaccard can't reach 0.9 (`min/max < 0.9`); require both ≥ 5 tokens and Jaccard ≥ 0.9. Comment: `# shortcut: O(n²) pairwise, fine to a few thousand items; switch to MinHash if specs get larger`.
  - Acronyms: `(?<!\w)[A-ZÄÖÜ]{2,}\d*(?!\w)`, minus `known_acronyms` and the run's item IDs. Expanded if anywhere in the run it appears as `(ACR)`, `ACR (`, or an item matches `^ACR\s*[:–-]\s*\S`.
  - Decimals: only a number followed by an optional space and a unit from `tolerance.units`: `(?<![\d.,])\d+([.,])\d{1,2}(?=\s?(?:units))`. Group by `Result.lang`. Flag the minority separator; on a tie, flag the one that isn't the language's convention (`de` → `.`, `en` → `,`).
  - Units: value + unit from `metric`/`imperial` (same number regex as `_tolerance_re`); fire only if both occur; flag the minority, tie → imperial.
  - `related` lists every other affected item once.

  `check` calls `check_spec(results, set(profile.severities))` after the per-item loop and sets each new finding's severity in `report` like any other finding.

- [ ] **Step 4: Run tests** — `uv run pytest -q`, including `tests/test_schema.py`.

- [ ] **Step 5: Commit** — `feat: whole-spec rules (acronyms, decimals, units, duplicates)`

---

### Task 7: EARS mode

**Files:**
- Create: `src/speclint/ears.py`
- Modify: `src/speclint/checks.py` (`Result.ears`, call from `check` when `profile.ears`), `src/speclint/rules.toml` (`[rules.ears-nonconforming]` + `[ears]` keywords), `src/speclint/profiles.py` (`ears=True` adds `ears-nonconforming` at its base severity unless the profile overrides it), `src/speclint/cli.py` (EARS mix in the summary), `schema/results.schema.json` (requirement `ears`, summary `ears`), `README.md`, `skills/speclint/SKILL.md` (when to add `--ears`), `agents/req-reviewer.md` (EARS findings: a rewrite should use the pattern)
- Test: `tests/test_ears.py`

**Interfaces:**
- Produces: `ears_pattern(text: str, lang: str) -> tuple[str, Finding | None]` returning one of `"ubiquitous","event","state","unwanted","optional","complex","non-conforming"`. `Result.ears: str | None = None`. Report: requirement `ears: {"pattern": ...}`. `rescore` adds `summary.ears = {pattern: count}` over graded items when `doc["profile"]["ears"]`. Rule `ears-nonconforming`: non_ambiguity, R1, warning.
- `[ears]` TOML: `en.keywords = { while = "state", when = "event", if = "unwanted", where = "optional" }`, `en.modal = "shall"`, `en.then = "then"`; `de.keywords = { solange = "state", wenn = "event", falls = "unwanted", sofern = "optional" }`, `de.modal = "muss"`, `de.then = "dann"`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("lang,text,pattern", [
    ("en", "The ECU shall store the error.", "ubiquitous"),
    ("en", "When the ignition is switched on, the ECU shall start.", "event"),
    ("en", "While the vehicle is moving, the ECU shall lock the doors.", "state"),
    ("en", "If the voltage drops below 9 V, then the ECU shall enter safe state.", "unwanted"),
    ("en", "Where a sunroof is fitted, the ECU shall close it.", "optional"),
    ("en", "While the vehicle is moving, when a door opens, the ECU shall warn the driver.", "complex"),
    ("de", "Das Steuergerät muss den Fehler speichern.", "ubiquitous"),
    ("de", "Wenn die Zündung eingeschaltet wird, muss das Steuergerät starten.", "event"),
    ("de", "Solange das Fahrzeug fährt, muss das Steuergerät die Türen verriegeln.", "state"),
    ("de", "Falls die Spannung unter 9 V fällt, dann muss das Steuergerät in den sicheren Zustand wechseln.", "unwanted"),
    ("de", "Sofern ein Schiebedach verbaut ist, muss das Steuergerät es schließen.", "optional"),
])
def test_patterns(lang, text, pattern):
    assert ears_pattern(text, lang) == (pattern, None)

@pytest.mark.parametrize("lang,text,match", [
    ("en", "The ECU must store the error.", "The"),                    # no shall
    ("en", "The ECU shall start when the ignition is on.", "when the ignition is on"),  # condition after response
    ("en", "If the voltage drops, the ECU shall enter safe state.", "If"),  # if without then
    ("en", "The ECU shall start and shall log.", "shall"),            # second shall
    ("en", "After start-up, the ECU shall log.", "After"),             # unknown preamble
    ("de", "Das Steuergerät soll starten.", "Das"),
    ("de", "Das Steuergerät muss starten, wenn die Zündung an ist.", "wenn die Zündung an ist"),
])
def test_non_conforming(lang, text, match):
    pattern, f = ears_pattern(text, lang)
    assert pattern == "non-conforming" and f.rule == "ears-nonconforming" and f.match == match
    assert text[f.start:f.end] == f.match

def test_ears_flag_adds_pattern_and_summary(tmp_path):
    p = load_profile("customer", ears=True)
    doc = report(check([Requirement("A", "The ECU shall start."), Requirement("B", "The ECU must start.")], "en", p), p)
    assert doc["requirements"][0]["ears"] == {"pattern": "ubiquitous"}
    assert doc["summary"]["ears"] == {"ubiquitous": 1, "non-conforming": 1}

def test_without_ears_flag_no_ears_fields():
    doc = report(check([Requirement("A", "The ECU must start.")], "en"))
    assert "ears" not in doc["requirements"][0] and "ears" not in doc["summary"]
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement `ears_pattern`** with a regex skeleton (no spaCy; deterministic and fast):
  1. Count `\b<modal>\b` (case-insensitive). 0 → non-conforming, match = first word. More than 1 → non-conforming, match = the second modal.
  2. Main clause: EN `(?:^|,\s*)(?:then\s+)?the\s+.+?\s+shall\b` (case-insensitive); DE `(?:^|,\s*)(?:dann\s+)?muss\s+(?:der|die|das)\b` or ubiquitous `^(?:der|die|das)\s+.+?\s+muss\b`. The preamble is the text before the main clause.
  3. Empty preamble: if a keyword (EN when/while/if/where/during/after/before/unless; DE wenn/solange/falls/sofern/sobald) follows the modal → non-conforming, match = from that keyword to the end without the final period. Otherwise ubiquitous.
  4. Preamble: split on commas; each clause's first word must be a keyword, otherwise non-conforming with match = that word. An `unwanted` keyword without `then`/`dann` before the main clause → non-conforming, match = the keyword. One distinct pattern → that pattern; two or more → `complex`.

- [ ] **Step 4: Run tests** — `uv run pytest -q`, all pass.

- [ ] **Step 5: Commit** — `feat: --ears conformance mode`

---

### Task 8: Calibration and throughput check

**Files:**
- Modify: `bench/promise.py` (run with `load_profile("system")`; print per-rule hits for all active rules; it already loops over `RULES["rules"]`, so restrict the loop to the profile's rules)
- Modify: `docs/backlog.md` (calibration results)

- [ ] **Step 1: Run the bench** — `uv run python bench/promise.py 20`. Record the throughput and the per-rule hit counts.
- [ ] **Step 2: Hand-check 20 samples per new rule.** For each rule, count true positives. A rule with fewer than 14/20 (70%) stays out of the built-in profiles: remove it from `customer.rules`/`system.enable` and note why in the backlog. Don't tune word lists to the sample.
- [ ] **Step 3: Recheck pile-up** — on PROMISE under `system`, count distinct warning/error rules per item and the resulting `summary.grades`. Record both in the backlog's Grading section next to the 797/149/23 baseline.
- [ ] **Step 4: Throughput** — must be ≥ ~760 req/s (within 20% of 950). If not, profile `check_spec` and the modal pass before anything else.
- [ ] **Step 5: Final verification** — `uv run ruff check . && uv run ruff format --check src tests bench && uv run pytest && uv run speclint check examples/lastenheft.md`. The output starts with `Profile: customer`.
- [ ] **Step 6: Commit** — `chore: calibrate new rules on PROMISE`
