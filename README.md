<h1 align="center">speclint</h1>

<p align="center"><b>A linter for requirements in English and German.</b><br>
It finds the weak spots in a customer specification that need clarifying, grades each requirement from A to F, and drafts the questions to ask the customer.</p>

<p align="center">
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a><br>
<a href="schema/results.schema.json">Results schema</a> ·
<a href="src/speclint/rules.toml">Rules</a> ·
<a href="examples/lastenheft.md">Example spec</a>
</p>

## Why speclint

A Lastenheft or a customer spec in ReqIF often has hundreds of requirements. The expensive ones are the ones nobody asked about: "schnell", "ggf.", "z. B. … usw.", a voltage with no tolerance. speclint reads the spec in the format it comes in and flags each of those weak spots with its exact position in the text. For each finding it names the matching rule from the INCOSE Guide to Writing Requirements, which inspired the rules. Then it grades every requirement, so the worst ones get reviewed first.

The rules are deterministic: the same spec always gives the same grades, and the word lists sit in one TOML file you can read and change. On top of that, speclint ships a Claude Code skill. Haiku subagents confirm or dismiss each finding and write a clarification question and a rewrite for each requirement. They never set grades.

It is not a requirements management tool and it does not edit your files. It also only finds what its rules look for. A requirement without findings is shown as "no findings", not as a top grade, and no stage reviews it again.

## What you get

```text
$ speclint check examples/lastenheft.md
LH-003  [D]  Im Fehlerfall sollen die Daten ggf. gespeichert werden.
    info    undefined-condition    R27       "Im Fehlerfall"  Condition that is rarely defined; check it is specified (glossary or definition)
    error   escape-clause          R8        "ggf."  Escape clause makes the requirement non-binding
    info    passive-no-actor       R2        "gespeichert werden"  Passive voice without actor; who is responsible?
LH-004  [B]  Das Türsteuergerät muss Signale wie z. B. Türstatus, Fensterposition usw. auf dem CAN-Bus senden.
    warning open-ended             R9        "z. B."  Open-ended list; enumerate the complete set
    warning open-ended             R9        "usw."  Open-ended list; enumerate the complete set
…
11 graded items, 7 need clarification.
  Grades: B:5  C:1  D:1  no findings:4
  Findings per category:
    Accuracy       3
    Completeness   4
    Non-ambiguity  3
    Realism        1
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
- **Vague timing:** immediately, promptly; sofort, unverzüglich, rechtzeitig.
- **Weak obligations:** should, will, may; sollte, kann, wird (future). Binding is shall/must, muss.

Across the whole spec, each finding goes on every item it affects and names the others as `related`:

- **Unexpanded acronyms:** an acronym that is never written out ("Electronic Control Unit (ECU)", or a glossary line "ECU: …") anywhere in the run.
- **Duplicates:** near-identical requirements (same words, at least five).

The `system` profile adds:

- **Purpose phrases:** in order to, so that; um … zu, damit, sodass.
- **Superfluous infinitives:** be able to, be capable of; in der Lage sein.
- **Clause combinators:** unless, except, otherwise; es sei denn, sondern, andernfalls.
- **One thought per requirement:** a second shall/must, muss/soll in the same item.
- **Slashes:** speed/position, Drehzahl/Position. Units (km/h), numbers (12/05), paths and URLs are allowed.
- **Long parentheticals:** more than three words in parentheses; "(ECU)" is fine.
- **Mixed decimal format:** "1,5 V" and "1.5 V" in the same language. Only numbers with a unit count, so "Abschnitt 4.1" is not a decimal.
- **Mixed unit systems:** metric and imperial (mm and inch, °C and °F).
- **"soll" as non-binding:** many house styles use muss = mandatory, soll = desired. In `customer`, "soll" counts as binding.

Each finding caps the grade of its item: an error at D, a warning at B, an info at A. The item gets the worst cap, then one letter lower for each further distinct warning or error rule, down to F. Infos and repeated hits of the same rule don't lower it further. An item without findings gets "no findings". The caps live in `rules.toml` under `[grading]`. The language is detected for each item; an item too short to tell takes the language of most items in the run. You can also set it with `--lang`.

## Profiles

A profile decides which rules run and how severe each one is. Since severity caps the grade, it also decides how strict the grades are. Pick one with `--profile`:

- `customer` (default): for customer specifications and Lastenhefte. Its rules find what to ask the customer.
- `system`: for system and software requirements. It runs everything in `customer` plus the style rules, and passives without an actor become warnings.

Your own profile is a TOML file with a `[profile]` table, passed as `--profile acme.toml`:

```toml
[profile]
extends = "system"
disable = ["passive-no-actor"]
severity = { vague-term = "error" }
```

`rules` replaces the inherited rule list, `enable` and `disable` add and remove rules, and `severity` overrides them. An unknown rule, severity or profile exits 2. The results JSON records the profile, because grades from different profiles aren't comparable.

## How a review runs

Three stages run in this order; only the first always runs.

1. **Rules** (`speclint check`) produce every finding and every grade.
2. **Classifier** (`--classify`, optional): a local GLiClass model labels each item as a requirement or as information, such as a heading, note or explanation. Information items are not graded or reviewed. Any item with an obligation verb (shall, must, should; muss, soll, darf) counts as a requirement, whatever the model says.
3. **Reviewers** (`batches` → `speclint:req-reviewer` → `merge`, optional): Haiku subagents confirm or dismiss each finding and draft a question and a rewrite. Dismissed findings stop counting and the item is regraded.

## Quick start

You need [uv](https://docs.astral.sh/uv/). In Claude Code:

```text
/plugin marketplace add MichaelD-42/speclint
/plugin install speclint@speclint
```

Then ask Claude to check a spec. The skill runs all three stages and answers with how many items need clarification, the grade distribution and the worst requirements.

From a clone, the CLI works on its own:

```sh
uv sync                                                  # --extra classify adds the GLiClass classifier
uv run speclint check spec.reqifz export.csv -o results.json
uv run speclint check spec.reqifz --classify -o results.json
uv run speclint batches results.json --out review/       # batch files for reviewer agents
uv run speclint merge results.json review/*.review.json  # apply reviews, regrade
```

It reads ReqIF and ReqIFz, and CSV or TSV, where the ID and text columns are found by their headers or set with `--id-col` / `--text-col`. It also reads RST or Markdown with sphinx-needs directives (`.. req::` or MyST `{req}` with `:id:`) or `ID: text` lines. `--fail-on D` exits 1 when any graded item is D or worse, for CI. Input it cannot read exits 2, and so does a `--classify` run that labels every item as information, since nothing was graded.

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
