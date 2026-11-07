# Backlog

## References

- INCOSE GtWR v4, all 42 rules and 15 characteristics: https://reqi.io/articles/incose-requirements-quality-42-rule-guide
- INCOSE Requirements Workbench (a regex implementation of the rules; its rule list is useful, its regexes are too noisy to copy): https://github.com/ssaleem74/incose-requirements-workbench
- Quick reference card: https://ssaleem74.github.io/incose-requirements-workbench/quick-reference-card.pdf
- EARS lint prior art: https://github.com/tbhb/vale-ears, https://pkg.go.dev/github.com/labeth/ears-lint-go
- PROMISE_exp dataset (bench): https://github.com/AleksandarMitrevski/se-requirements-classification
- Design for profiles, checks and EARS: [specs/2026-11-07-profiles-checks-ears-design.md](superpowers/specs/2026-11-07-profiles-checks-ears-design.md)

## Now

### 1. Readers: close the metadata gap

- ReqIF: read enumeration attributes (`ATTRIBUTE-VALUE-ENUMERATION` → `ENUM-VALUE-REF` → the enum value's LONG-NAME). Today they're dropped, so a DOORS object type ("Requirement"/"Information") never arrives.
- ReqIF: emit items in SPEC-HIERARCHY order, not file order; keep headings (ReqIF.ChapterName) as information items or as section context.
- Native `needs.json` (sphinx-needs builder output), alongside ReqIF: text from the need's content, ID, `type` as the requirement/information signal, document order. Field names to verify against the sphinx-needs docs.
- An object type from the input file, when present, decides requirement vs information before any classifier.

### 2. Grading: stop overpromising — done (branch feat/profiles-checks-ears, not merged)

- Items without findings show "no findings", not A+ (agreed). They're a bucket of their own in the grade distribution, not counted as top grades.
- The summary leads with "N items need clarification" and the worst items; the overall grade comes second.
- Replace the additive score with grade caps (agreed): the item gets the worst cap among its findings. The cap comes from severity: error → D, warning → B, info → A. A profile's severity override is therefore also its cap override.
- Pile-up rule: each distinct warning/error rule beyond the first lowers the grade one letter, floor F. Infos and repeat hits of the same rule don't count. Examples: "schnell" → B; "Dies … ausreichender" → C; "ggf." + "schnell" → F.
- Calibration (2026-11-07, current nine rules): on PROMISE, 0/1/2 distinct warning/error rules per item = 797/149/23 items; none has 3. So the threshold must be "beyond the first". It fires on 23 items (2.4%), about 7 (0.7%) once the percentage false positive is fixed; all are real double problems. The example spec changes one item (LH-008 → C). Recalibrate on the eval set and with the `system` profile, which adds 9 rules.
- Recheck after the new rules (2026-11-07, PROMISE; distinct warning/error rules per item 0/1/2/3/4/5):
  - customer: 639/246/74/10/0/0 → grades A 164, B 246, C 72, D 10, F 2, none 475. The pile-up fires on 8.7% of items (was 2.4%), mostly from weak-obligation (PROMISE writes should/will a lot).
  - system: 419/282/171/53/36/8 → grades A 31, B 282, C 170, D 52, F 46, none 388. The pile-up fires on 28%; F means 4+ distinct problems. Plausible for PROMISE, but it needs the eval set before the step is trusted.
- Scale becomes A, B, C, D, F + "no findings" (+ grades can't occur with these caps).
- Numbers go (agreed): no item score, no category percentages, no overall mean. The summary shows the grade distribution, items needing clarification, and findings per category. The CI gate becomes `--fail-on <grade>` (exit 1 if any graded item is at that grade or worse) instead of `--fail-under`. Lands with schema v2.
- Rejected: worst-category grade (more lenient than today, not stricter).

### 3. Evals and benchmarks (labeled data: available next week, from work)

- Eval harness: labeled EN/DE automotive-style items, precision/recall per rule and per profile. Prerequisite for tuning rules and profiles.
- Classifier test: on labeled requirement/information items, compare GLiClass vs the plain rule "no obligation verb → information" vs Haiku. If GLiClass adds nothing over the baseline, drop it (and the 1.5 GB extra) and use Haiku only.
- Timing benchmarks per stage (read, rules, whole-spec rules, classify, review) at 100 / 1k / 10k items. Watch the O(n²) duplicate check.
- Fix: missing-tolerance flags proportions as missing tolerances ("for 97% of all leads", "used by 90% of novice users").

### 4. Profiles, new checks, EARS — done (branch feat/profiles-checks-ears, not merged)

See the design doc. Summary:

- Profiles switch rules on/off and override severities. Built-ins live in `rules.toml`; `--profile <name|path.toml>`; custom profiles can `extends` a built-in. The profile used is recorded in the results JSON (schema v2).
- `customer`: the current nine rules + temporal words, weak obligation, unexpanded acronyms, duplicates.
- `system`: `customer` + single thought (R18), purpose phrases (R20), superfluous infinitives (R10), clause combinators (R19), slash (R17), parentheticals (R21), "soll" as non-binding, decimal format (R40), unit systems (R6/R36).
- Whole-spec findings go on every affected item, count against each, and link the related items.
- `--ears` on top of any profile: pattern per item, non-conformance finding, pattern mix in the summary. German keywords: Wenn / Solange / Falls … dann / Sofern + muss.
- Left out: R16 "not", R32 all/any, R14 punctuation, R12/R13 grammar/spelling, R5 articles.

### Calibration of the new rules (2026-11-07, PROMISE under `system`, 20 hand-checked samples per rule)

Hits (items) and true positives in the sample:
- weak-obligation 248 (218): 16/20. The misses are "may" as possibility ("may be selected", "a user may have").
- single-thought 190 (153): about 16/20. The misses are a modal inside an indirect question or relative clause ("when should the doughnut be delivered").
- superfluous-infinitive 129 (124): 20/20.
- undefined-acronym 126 (84): about 15/20. The misses are generic names (ID, HTML, IBM, DB2); PROMISE also lacks the glossaries of its source documents.
- oblique 50 (45): about 17/20. The debatable ones are "his/her".
- parenthetical 25 (22): 20/20.
- duplicate 10 items = 5 pairs: 4 real. One false positive: "defensive → offensive" vs "offensive → defensive", the same word set with the opposite meaning. Word sets ignore order; the reviewer is told to dismiss such pairs.
- purpose-phrase 6/6, clause-combinator 5/5.
- temporal-word: 1 hit, a false positive ("at later points in time"). The phrase "in time" is a likely source of noise; decide with the eval set.
- decimal-format, unit-system, soll-obligation: 0 hits. PROMISE is English, with few units and no German. Unverified until the eval set.

All rules with enough hits pass the 14/20 bar, so none was removed from the profiles. Throughput: 905 req/s under `system` (was 964 with nine rules). The duplicate check now uses an exact prefix-filter join instead of O(n²) pairs, and the acronym check makes a single pass.

### Deferred from the final branch review (2026-11-07)

- Bilingual spec: a short German item whose language detection is a tie (or where English is the majority) is treated as English. It then gets decimal-format and the EARS message "no shall".
- In German, the single-thought finding starts at the conjunction ("und darf") instead of the second modal.
- Profile type errors (rules as a string, extends as a list) give a garbled message or a traceback instead of a clean exit 2. The cycle message lists names in arbitrary order.
- Oblique flags German hyphen pairs ("Ein-/Ausgänge", "Lade-/Entladestrom").
- "ECU-Software muss …" at the start of an item counts as a glossary expansion of ECU.

## Later: classification (Haiku, configurable per profile)

Labels only; they never change scores.

- Domain, multi-label: ME, EE, SW, SYS.
- Safety relevance: yes / no / unclear. Pick up an ASIL/SIL the text states; flag safety-relevant items with none stated. Never assign one (it comes from the HARA, not the text).
- Cybersecurity relevance: yes / no / unclear (CAL comes from the TARA, not the text).
- Requirement type: functional, performance, interface, constraint, safety, security.
- Level: stakeholder / system / component (R3).
- Solution-free (R31).
- Verification method: test, analysis, inspection, demonstration, or not verifiable.
- EARS rewrite suggestion.
- Contradictions between near-duplicate pairs (C11).

## Ideas (placeholders)

- Grader / rubrics
- Hooks
- Rules
