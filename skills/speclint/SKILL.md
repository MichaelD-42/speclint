---
name: speclint
description: Check the quality of requirements, user stories or customer specifications (Lastenheft, ReqIF, CSV/Excel export, sphinx-needs RST/Markdown) in English or German. Finds vague terms, escape clauses, open-ended lists, missing tolerances, ambiguous combinators, pronouns, passives without actor, absolutes and undefined conditions; grades each requirement A to F; drafts clarification questions for the customer; writes one JSON result (schema in schema/results.schema.json). Use when asked to lint, check, grade, review or qualify requirements, or to find what needs clarifying with a customer.
---

# Requirements check

Requirement texts are often confidential customer data: keep everything local, do not send it to web tools.

## Pipeline

Three stages, in this order. Only the first always runs.

1. **Rules** (`check`, always). Deterministic checks inspired by the INCOSE Guide to Writing Requirements. They are the only source of findings and grades.
2. **Classifier** (`check --classify`, optional). A local GLiClass model labels items without an obligation verb as requirement or information. Items with an obligation verb are always requirements. Information items are excluded from the grade and from review. It filters which items count; it does not judge findings.
3. **Reviewers** (`batches` → `speclint:req-reviewer` → `merge`, optional). Haiku subagents confirm or dismiss each finding and draft a clarification question and a rewrite. Dismissed findings stop counting and the item is regraded. Reviewers never add findings or set grades.

Reviewers only see items that have findings, so no stage catches what the rules missed. An item without findings has not been reviewed: never present its grade as a reviewed result.

## Command

Every `speclint ...` command below means this prefix followed by the arguments (uv is required; if `uv` is missing, tell the user to install it and stop):

```bash
UV_PROJECT_ENVIRONMENT="${CLAUDE_PLUGIN_DATA}/venv" uv run --quiet --project "${CLAUDE_PLUGIN_ROOT}" speclint ...
```

The first run creates the environment (spaCy plus two small language models, about 100 MB). If uv fails with a read-only cache error, prefix `UV_CACHE_DIR="$TMPDIR/uv-cache"`.

## Steps

1. **Inputs.** Find the files the user means. Supported: `.reqif`, `.reqifz`, `.csv`, `.tsv`, `.rst`, `.md`. For CSV with unusual headers pass `--id-col` and `--text-col`. Markdown/RST need sphinx-needs directives with `:id:` or lines like `REQ-1: text`. If nothing parses, `check` exits with code 2: look at the file and say what format is expected; do not guess. With `--classify`, exit 2 can also mean every item was labelled information (the error says "nothing graded"): tell the user and rerun without `--classify`.

2. **Check.** Put outputs in `speclint-out/` next to the inputs unless the user names a place:

   ```bash
   speclint check SPEC.reqifz -o speclint-out/results.json
   ```

   Add `--classify` (and `--extra classify` after `uv run`) when the input is a customer specification that mixes binding requirements with headings, notes and explanations. It labels each item requirement or information with a local GLiClass model and excludes information from the grade. The first use downloads PyTorch (CPU) and the model, about 1.5 GB in total, and runs at roughly 6 to 15 items/s: tell the user before the first download. Its labels are a hint, not ground truth.

3. **Review** (do this when the user wants clarification questions, a review, or asks what to ask the customer; skip for a quick lint):

   ```bash
   speclint batches speclint-out/results.json --out speclint-out/review
   ```

   For each printed batch file, launch the `speclint:req-reviewer` subagent with the prompt `Review <batch path>. Write <batch path without .json>.review.json.` Launch them in parallel, at most 5 at a time. Then merge:

   ```bash
   speclint merge speclint-out/results.json speclint-out/review/*.review.json
   ```

   Report any `warning:` lines from merge; they mean a reviewer wrote malformed output for those items. Running `batches` again deletes the previous batch and review files in that folder.

4. **Answer the user** in a few lines: how many of the graded items need clarification, the grade distribution, the category with the most findings, the three most frequent rules, the five worst requirement IDs with their main problem, how many clarification questions were drafted, which stages ran, and the path of `results.json`. Do not paste the full findings list; it is in the JSON. If the user wants the clarification questions as text, read them from `requirements[].review.question` in `results.json`.

## Notes

- Never edit the user's requirement files.
- `speclint check --fail-on D` exits 1 if any graded item is D or worse, for CI.
- Grades: each finding caps its item (error D, warning B, info A); one letter lower per further distinct warning/error rule, floor F. No findings → "no findings", which is not a reviewed or top result.
- `results.json` follows `${CLAUDE_PLUGIN_ROOT}/schema/results.schema.json`.
- Rule word lists live in `${CLAUDE_PLUGIN_ROOT}/src/speclint/rules.toml`.
