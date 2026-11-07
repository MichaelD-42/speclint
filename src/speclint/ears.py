"""EARS conformance (--ears): which of the six patterns an item follows, or what breaks it.

A regex skeleton, not a parse: preamble clauses (While/When/If/Where; Solange/Wenn/Falls/Sofern),
then the main clause "the <system> shall <response>" / "muss das <System> <Reaktion>" (German verb-second).
"""

import re
from functools import cache

from .checks import RULES, Finding

PATTERNS = [
    "ubiquitous",
    "event",
    "state",
    "unwanted",
    "optional",
    "complex",
    "non-conforming",
]
RULE = "ears-nonconforming"
_TRAILING = {
    "en": ["when", "while", "if", "where", "during", "after", "before", "unless"],
    "de": ["wenn", "solange", "falls", "sofern", "sobald"],
}


@cache
def _rx(lang: str) -> dict[str, re.Pattern]:
    e = RULES["ears"][lang]
    modal, then = re.escape(e["modal"]), re.escape(e["then"])
    if lang == "en":
        main = [rf"(?:^|,\s*)(?:({then})\s+)?the\s+[^,]+?\s+{modal}\b"]
    else:  # "Das System muss …" or, after a preamble, ", (dann) muss das System …"
        main = [
            rf"^(?:der|die|das)\s+[^,]+?\s+{modal}\b",
            rf",\s*(?:({then})\s+)?{modal}\s+(?:der|die|das)\b",
        ]
    return {
        "modal": re.compile(rf"\b{modal}\b", re.IGNORECASE),
        "main": [re.compile(m, re.IGNORECASE) for m in main],
        "trailing": re.compile(rf"\b(?:{'|'.join(_TRAILING[lang])})\b", re.IGNORECASE),
    }


def _bad(text: str, start: int, end: int, why: str) -> tuple[str, Finding]:
    return "non-conforming", Finding(RULE, text[start:end], start, end, message=why)


def ears_pattern(text: str, lang: str) -> tuple[str, Finding | None]:
    e, rx = RULES["ears"][lang], _rx(lang)
    first = re.search(r"\w[\w-]*", text)
    at_first = (first.start(), first.end()) if first else (0, 0)
    modals = list(rx["modal"].finditer(text))
    if not modals:
        return _bad(
            text,
            *at_first,
            f'No "{e["modal"]}": EARS states each requirement with "{e["modal"]}"',
        )
    if len(modals) > 1:
        return _bad(
            text,
            *modals[1].span(),
            f'More than one "{e["modal"]}": one response per requirement',
        )
    main = next((m for p in rx["main"] if (m := p.search(text))), None)
    if main is None:
        return _bad(text, *at_first, f'No main clause "{e["main"]}"')
    preamble = text[: main.start()]
    if not preamble.strip():
        if t := rx["trailing"].search(text, modals[0].end()):
            end = len(text.rstrip().rstrip("."))
            return _bad(
                text,
                t.start(),
                end,
                "Condition after the response; move it to the start of the sentence",
            )
        return "ubiquitous", None
    found = []
    for clause in re.finditer(r"[^,]+", preamble):
        word = re.match(r"\s*(\w+)", clause.group(0))
        if not word:
            continue
        start = clause.start() + word.start(1)
        kind = e["keywords"].get(word.group(1).lower())
        if kind is None:
            keys = "/".join(k.capitalize() for k in e["keywords"])
            return _bad(
                text,
                start,
                start + len(word.group(1)),
                f"Preamble must start with {keys}",
            )
        if kind == "unwanted" and not main.group(1):
            return _bad(
                text,
                start,
                start + len(word.group(1)),
                f'"{word.group(1)}" needs "{e["then"]}" before the main clause',
            )
        found.append(kind)
    kinds = set(found)
    return (kinds.pop() if len(kinds) == 1 else "complex"), None
