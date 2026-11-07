# Profiles, new checks and EARS mode — design

Status: draft for review. Backlog: [docs/backlog.md](../../backlog.md), section "Now".

## Why

speclint has nine rules and one fixed rule set. Customer specs (Lastenheft) and system specs (Pflichtenheft) need different strictness: a customer spec is read to find the questions to ask the customer, a system spec is held to a writing standard. Today both get the same rules, so either the customer spec drowns in style findings or the system spec gets let off. Some weak spots are also only visible across the whole spec (an acronym never expanded, the same requirement twice), and the per-item checks can't see them. Some teams write system requirements in EARS and want conformance checked.

## Goals

- Profiles that turn rules on/off and override severities: built-in `customer` and `system`, plus custom profiles from a TOML file.
- Eight new single-item rules and four whole-spec rules, in English and German.
- An `--ears` mode that works on top of any profile.
- Grades from severity caps plus a pile-up rule instead of the additive score, and "no findings" instead of A+.
- The results JSON records the profile and EARS mode, so grades from different profiles can't be mixed up.

## Non-goals

- Haiku classification (domain, safety/security relevance, type, level, …). That's the "Later" section of the backlog. Profiles will configure it, but this round doesn't reserve or parse a key for it.
- Word lists or new rules defined in a custom profile. A profile only picks rules and severities; rule data stays in `rules.toml`.
- A glossary input file for acronyms.
- Reader changes (ReqIF metadata/order, needs.json). They're a separate backlog item.

## Anti-goals

- Noisy rules. A rule that fires on a large share of normal, well-written requirements is worse than no rule. The workbench's regexes (any "not", any "all", a missing final period) are the counter-example. Every new rule has negative tests for the common legitimate phrasings and is checked on PROMISE with `bench/promise.py` (hits per rule, plus a hand-checked sample) before it's switched on in a built-in profile.
- Breaking the offset contract: every finding keeps `match == text[start:end]`.
- Model output changing scores: unchanged; Haiku still only confirms or dismisses.

## Grading (replaces the additive score)

Today an item scores 100 minus 30/15/3 per error/warning/info, and the summary averages the scores. That gives A+ to every item without findings (616 of 969 on PROMISE), and the mean hides the bad items. Replaced by:

- No findings (none active, i.e. not dismissed) → grade `none`, shown as "no findings". It's not a top grade and is listed separately in the distribution.
- Otherwise the base grade is the worst severity cap among the active findings: info → A, warning → B, error → D.
- Pile-up: each distinct warning/error rule beyond the first lowers the grade one letter (A→B→C→D→F, floor F). Infos and repeat hits of the same rule don't count.
- Scale: A, B, C, D, F, none. The caps and the pile-up step live in `rules.toml` (`[grading]`), so recalibration on the eval set is a data change.
- No numbers: item `score`, `categories` percentages, summary `score`, `grade` and category means are removed. The summary keeps `grades` (now including `none`), adds `needs_clarification` (graded items with active findings, replacing `with_findings`) and `categories` as active finding counts per category.
- `--fail-under` is replaced by `--fail-on <grade>`: exit 1 if any graded item is at that grade or worse. Default: off.
- Dismissals in `merge` regrade the item the same way (`rescore` keeps its role, with the new logic).

Calibration (current nine rules, PROMISE): 0/1/2 distinct warning/error rules per item = 797/149/23; none has 3. The pile-up fires on 2.4% of items, about 0.7% once the percentage false positive in `missing-tolerance` is fixed (backlog). Rerun with the `system` profile and on the eval set.

## Profiles

Built-ins live in `rules.toml` under `[profiles.<name>]`; a custom profile is a TOML file with the same keys under `[profile]`.

```toml
[profiles.customer]
rules = ["vague-term", "missing-tolerance", "escape-clause", "open-ended",
         "undefined-condition", "ambiguous-combinator", "unresolved-reference",
         "passive-no-actor", "absolute",
         "temporal-word", "weak-obligation", "undefined-acronym", "duplicate"]

[profiles.system]
extends = "customer"
enable = ["single-thought", "purpose-phrase", "superfluous-infinitive",
          "clause-combinator", "oblique", "parenthetical", "soll-obligation",
          "decimal-format", "unit-system"]
severity = { passive-no-actor = "warning" }
```

Resolution: start from `extends` (resolved recursively, cycles are an error), set `rules` if given, then add `enable`, remove `disable`, then apply `severity`. A custom profile file: `--profile path/to/x.toml`, which can `extends` a built-in. `--profile` takes a built-in name or a path. An unknown rule name, unknown severity, unknown profile or cycle: print the error and exit 2, like unreadable input.

The default is `customer`. This is a call made for the user (README positions speclint for customer specs). It adds four rules to today's default output, so existing `--fail-under` thresholds can drop. The README says so.

Effective severity is written into each finding at report time (it already is: `report()` copies `severity` from the rule spec). Since severity is the grade cap, `rescore()` and `merge` need no profile awareness. `doc["rules"]` lists only the rules that are active, with their effective severity.

Why `customer` gets those four additions: each produces a direct question to the customer ("what does 'sofort' mean in ms?", "is 'sollte' binding?", "what is ABS-K?", "LH-012 and LH-031 say the same, which one counts?").

German "soll": in customer specs it's normally binding, but in system specs many house styles use muss = mandatory, soll = desired, kann = optional. So "soll" is its own rule `soll-obligation` (DE only, on in `system`, off in `customer`). That avoids per-profile word lists. `weak-obligation` covers should/will/may and sollte/kann/könnte/wird in both profiles.

## New single-item rules

| Rule key | INCOSE | Category | Severity | EN | DE |
|---|---|---|---|---|---|
| single-thought | R18 | non_ambiguity | warning | more than one obligation verb (shall/must/should/will) per item | muss/soll/sollte/darf/kann, more than one per item |
| purpose-phrase | R20 | non_ambiguity | info | in order to, so that, for the purpose of, so as to | um … zu (parse: `zu`-infinitive with `um`), damit, sodass, so dass |
| superfluous-infinitive | R10 | accuracy | warning | be able to, be capable of, have the capability to | in der Lage sein, imstande sein, die Möglichkeit haben |
| temporal-word | R35 | accuracy | warning | immediately, promptly, soon, instantly, eventually, in time | sofort, unverzüglich, umgehend, rechtzeitig, alsbald, sogleich |
| clause-combinator | R19 | non_ambiguity | warning | unless, except, however, otherwise | es sei denn, außer wenn, sondern, andernfalls |
| oblique | R17 | non_ambiguity | warning | "/" between words | same |
| parenthetical | R21 | non_ambiguity | info | parentheses with more than 3 words inside | same |
| weak-obligation | — (ISO 29148) | completeness | warning | should, will, may (as modal) | sollte, kann, könnte, wird (as modal) |
| soll-obligation | — | completeness | info | — | soll as modal |

Notes for the builder:
- `oblique` excludes units and rates (km/h, m/s², kbit/s, U/min), number ranges, dates, and "and/or", "und/oder" (those stay `ambiguous-combinator`). `ambiguous-combinator` keeps working as today.
- `temporal-word` vs `vague-term`: "zeitnah" and "schnellstmöglich" stay in `vague-term`; don't list the same word in both.
- Modal detection (`single-thought`, `weak-obligation`, `soll-obligation`) uses spaCy tags (`MD` in EN, `VMFIN` in DE; "wird" only with an infinitive, i.e. future, not passive). "will" as a noun and "may" as a month must not fire.
- `single-thought` counts obligation verbs per item, not per sentence. The finding spans the second verb onward (from the second modal to the end of its clause is fine), so the match points at what to split off.

## New whole-spec rules

They run in `check()` after the per-item pass, over all items of the run (all input files together). Each finding goes on every affected item, counts toward each item's grade like any other finding, and carries `related`: the other affected items as `[{"key": <index in requirements>, "id": "..."}]` (key because IDs can repeat across files). The match/offsets point at the relevant text in that item.

| Rule key | INCOSE | Category | Severity | Fires when | Finding on |
|---|---|---|---|---|---|
| undefined-acronym | R37, R38, R4 | completeness | info | an acronym (2+ capitals, optional digits: ECU, CAN, ASIL, HV2) is never expanded anywhere in the run | each occurrence |
| decimal-format | R40 | accuracy | info | within one language, both "1,5" and "1.5" style decimals occur | each decimal of the minority style |
| unit-system | R6, R36 | accuracy | warning | both metric and imperial units occur (°F, inch/in, ft, lb, mph, psi, gal) | each value in the minority system |
| duplicate | R30 | completeness | warning | two items are near-identical | the whole text of each, `related` names the other |

Notes for the builder:
- Expanded means: `Electronic Control Unit (ECU)`, `ECU (Electronic Control Unit)`, or an item whose whole text is a definition like `ECU: Electronic Control Unit` / `ECU – Steuergerät`. `rules.toml` gets a `known_acronyms` list for ones that need no expansion in this domain (CAN, LIN, USB, LED, …). Requirement IDs and all-caps words in the ID column are not acronyms.
- Decimals: "1,500" and "1.500" (three digits after the separator) are ambiguous thousands notation and are ignored. Only 1–2 digits after the separator count.
- Duplicates: normalize (lowercase, strip punctuation, collapse whitespace), compare token sets, Jaccard ≥ 0.9 and both items at least 5 tokens. Items classified as information don't take part (classification runs after `check`, so this means duplicates are computed before classification. Accepted: headings are rarely 5+ tokens and identical). Pairwise O(n²) with a length prefilter is fine up to a few thousand items. Mark it with a `shortcut:` comment.
- Dismissing a whole-spec finding in review dismisses it on that item only. The other items keep theirs (my call: keeps `merge` unchanged).

## EARS mode (`--ears`)

Adds EARS conformance on top of the selected profile. It's a flag, not a profile, so `--profile system --ears` and `--profile ./acme.toml --ears` both work.

Patterns (EN keywords from EARS; DE keywords are our own definition):

| Pattern | EN | DE |
|---|---|---|
| ubiquitous | The <system> shall <response> | Das/Die/Der <System> muss <Reaktion> |
| event | When <trigger>, the <system> shall … | Wenn <Auslöser>, muss das <System> … |
| state | While <state>, the <system> shall … | Solange <Zustand>, muss das <System> … |
| unwanted | If <trigger>, then the <system> shall … | Falls <Auslöser>, dann muss das <System> … |
| optional | Where <feature>, the <system> shall … | Sofern <Merkmal>, muss das <System> … |
| complex | combination of state/event/optional preambles (While …, when …, the … shall …) | same with Solange/Wenn/Sofern |

Each graded item gets `ears: {"pattern": "<pattern or non-conforming>"}`. A non-conforming item also gets one `ears-nonconforming` finding (R1, category non_ambiguity, warning) whose message names what's missing or out of order. Cases the builder must cover: no "shall"/"muss" (EARS mode accepts only shall/muss, so "must"/"should"/"soll" are non-conforming), condition after the response ("The system shall X when Y"), "If" without "then", more than one shall (also `single-thought`), preamble keyword not at the start. The match spans the offending part or, if nothing specific, the first word. `summary.ears` counts items per pattern.

The parsing approach (regex on the sentence skeleton vs spaCy) is the builder's call. It must handle German verb-second inversion ("Wenn X, muss das System Y").

## Results JSON (schema_version 2)

- Grading fields as in "Grading" above (scores and percentages removed, `none` grade, `needs_clarification`, category counts).
- Top level: `profile: {"name": "customer" | "<file path>", "ears": bool}`.
- `rules`: only active rules, effective severity.
- Finding: optional `related: [{key, id}]`.
- Requirement: optional `ears: {pattern}`.
- Summary: optional `ears: {<pattern>: count}` when EARS mode ran.
- `schema/results.schema.json` and `tests/test_schema.py` are updated; `$id` becomes `urn:speclint:results:2`.

## Other places that change

- `cli.py`: `--profile`, `--ears`, `--fail-on` (replaces `--fail-under`). Text report: header line naming the profile, item tag `[C]` / `[no findings]` instead of `[C 70%]`, `related` IDs printed after whole-spec findings, a summary that leads with "N of M items need clarification" and then the grade distribution and finding counts per category, and the EARS pattern mix.
- `[grading]` is global, not per profile (my call: profiles change severities, and that already changes the caps).
- `bench/promise.py`: prints the grade distribution instead of "Overall A+ (96%)".
- `tests/test_checks.py`, `tests/test_review.py`: assertions on `score` / `with_findings` are rewritten for grades. `classification.score` (model confidence, `classify.py`) is a different thing and stays.
- `review.py` `batches`: include `related` IDs and texts for whole-spec findings so the reviewer can judge a duplicate. `merge`: unchanged.
- `agents/req-reviewer.md`: one paragraph on whole-spec findings and EARS findings.
- `skills/speclint/SKILL.md`: when to pick `customer` vs `system`, when to add `--ears`, that grades from different profiles aren't comparable, and the answer to the user leads with how many items need clarification (no score, no weakest-category percentage any more).
- `README.md`: profiles, new rules, EARS mode, the new grading, `--fail-on`, the default-profile change.
- `bench/promise.py`: report the new rules (it reads the rule list, so it may already do this).

## Success criteria

- `uv run pytest` passes. For each new rule, at least one EN and one DE positive test and the negative cases named above. Profile resolution tests: extends, enable/disable, severity override, custom file, each error exits 2. A whole-spec test where a duplicate pair both carry the finding with `related` pointing at each other. EARS tests for each pattern in EN and DE plus each non-conforming case.
- `speclint check examples/lastenheft.md` with no flags runs the `customer` profile, and the output names it.
- Grading tests: no findings → `none`; each cap; pile-up across distinct rules, not across repeats or infos; floor F; a dismissal in `merge` regrades; `--fail-on` exit codes.
- `bench/promise.py` shows hits per new rule. A hand-checked sample of 20 hits per rule is mostly true positives. A rule that isn't stays out of the built-in profiles, and the result is reported, not tuned away silently.
- Rules throughput on PROMISE stays within ~20% of today's ~950 req/s.

## Left to the builder

The exact word lists beyond the examples above, the EARS parsing technique, the internal structure of profile resolution, the text-report layout details.
