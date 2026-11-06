<h1 align="center">speclint</h1>

<p align="center"><b>A linter for requirements in English and German.</b><br>
It finds the weak spots in a customer specification that need clarifying, grades each requirement from A+ to F, and drafts the questions to ask the customer.</p>

<p align="center">
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a><br>
<a href="schema/results.schema.json">Results schema</a> ·
<a href="src/speclint/rules.toml">Rules</a> ·
<a href="examples/lastenheft.md">Example spec</a>
</p>

## Why speclint

A Lastenheft or a customer spec in ReqIF often has hundreds of requirements. The expensive ones are the ones nobody asked about: "schnell", "ggf.", "z. B. … usw.", a voltage with no tolerance. speclint reads the spec in the format it comes in and flags each of those weak spots with its exact position in the text. For each finding it names the matching rule from the INCOSE Guide to Writing Requirements, which inspired the rules. Then it scores every requirement, so the worst ones get reviewed first.

The rules are deterministic: the same spec always gives the same grades, and the word lists sit in one TOML file you can read and change. On top of that, speclint ships a Claude Code skill. Haiku subagents confirm or dismiss each finding and write a clarification question and a rewrite for each requirement. They never set scores.

It is not a requirements management tool and it does not edit your files. It also only finds what its rules look for. A requirement without findings gets an A+, and no stage reviews it again.

## What you get

```text
$ speclint check examples/lastenheft.md
LH-003  [D 64%]  Im Fehlerfall sollen die Daten ggf. gespeichert werden.
    info    undefined-condition    R27       "Im Fehlerfall"  Condition that is rarely defined; check it is specified (glossary or definition)
    error   escape-clause          R8        "ggf."  Escape clause makes the requirement non-binding
    info    passive-no-actor       R2        "gespeichert werden"  Passive voice without actor; who is responsible?
LH-004  [C 70%]  Das Türsteuergerät muss Signale wie z. B. Türstatus, Fensterposition usw. auf dem CAN-Bus senden.
    warning open-ended             R9        "z. B."  Open-ended list; enumerate the complete set
    warning open-ended             R9        "usw."  Open-ended list; enumerate the complete set
…
11 items, 11 graded, 7 with findings. Overall B+ (86%)
  Accuracy        95.9%
  Completeness    94.3%
  Non-ambiguity   97.0%
  Realism         98.6%
  Grades: A+:4  B+:4  C:2  D:1
```

With `-o results.json`, the same goes to one JSON file defined by [`schema/results.schema.json`](schema/results.schema.json). Every finding carries `start`/`end` character offsets with `match == text[start:end]`, so a viewer can highlight it.

## What it checks

- **Vague terms:** fast, sufficient, user-friendly, approximately; schnell, ausreichend, zeitnah, ca.
- **Escape clauses:** where possible, if necessary, as appropriate; ggf., möglichst, nach Bedarf.
- **Open-ended lists:** etc., such as, including but not limited to; usw., z. B., insbesondere.
- **Missing tolerances:** a value with a unit and no bound, range or ±. "12 V" is flagged; "max. 16 V", "9 V bis 16 V", "200 ms ± 20 ms" and "12 V +10 %/-5 %" are not.
- **Ambiguous combinators:** and/or; und/oder, bzw.
- **Unresolved references:** it, this, the above; dies, o. g., vorgenannte.
- **Passives without an actor:** "Data shall be encrypted", "Die Daten müssen gespeichert werden".
- **Absolutes:** always, never, at all times; immer, jederzeit, ausnahmslos.
- **Undefined conditions:** in case of failure, in normal operation; im Fehlerfall, bei Bedarf.

Each item starts at 100 and loses 30 per error, 15 per warning and 3 per info finding. The grades are A+ ≥95, A ≥90, B+ ≥85, B ≥80, C+ ≥75, C ≥70 and D ≥60; anything lower is F. The language is detected for each item; an item too short to tell takes the language of most items in the run. You can also set it with `--lang`.

## How a review runs

Three stages run in this order; only the first always runs.

1. **Rules** (`speclint check`) produce every finding and every score.
2. **Classifier** (`--classify`, optional): a local GLiClass model labels each item as a requirement or as information, such as a heading, note or explanation. Information items are not graded or reviewed. Any item with an obligation verb (shall, must, should; muss, soll, darf) counts as a requirement, whatever the model says.
3. **Reviewers** (`batches` → `speclint:req-reviewer` → `merge`, optional): Haiku subagents confirm or dismiss each finding and draft a question and a rewrite. Dismissed findings stop counting and the item is rescored.

## Quick start

You need [uv](https://docs.astral.sh/uv/). In Claude Code:

```text
/plugin marketplace add MichaelD-42/speclint
/plugin install speclint@speclint
```

Then ask Claude to check a spec. The skill runs all three stages and answers with the overall grade, the weakest category and the worst requirements.

From a clone, the CLI works on its own:

```sh
uv sync                                                  # --extra classify adds the GLiClass classifier
uv run speclint check spec.reqifz export.csv -o results.json
uv run speclint check spec.reqifz --classify -o results.json
uv run speclint batches results.json --out review/       # batch files for reviewer agents
uv run speclint merge results.json review/*.review.json  # apply reviews, rescore
```

It reads ReqIF and ReqIFz, and CSV or TSV, where the ID and text columns are found by their headers or set with `--id-col` / `--text-col`. It also reads RST or Markdown with sphinx-needs directives (`.. req::` or MyST `{req}` with `:id:`) or `ID: text` lines. `--fail-under 80` exits 1 when the overall score is below 80, for CI. Input it cannot read exits 2, and so does a `--classify` run that labels every item as information, since nothing was graded.

The classifier's first run downloads PyTorch (CPU) and the model, about 1.5 GB, and runs at 6 to 15 items/s. Its labels are a hint, not ground truth.

## Benchmarks

On PROMISE_exp (969 English requirements), the rules run at about 950 requirements/s: `uv run python bench/promise.py` prints the hits per rule and random samples to check precision by hand, because PROMISE has no quality labels. Zero-shot GLiClass scores 38% on its 12 type classes and 44–56% on functional vs non-functional, against a 51% majority baseline (`bench/classify_promise.py`). So speclint uses the model only to tell requirements from information.

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format src tests bench
```

The tests validate every output the CLI produces against the schema.

## License

[MIT](LICENSE) © Michael Dold
