"""Checks across the whole run: each finding goes on every affected item and names the others in `related`."""

import re
from collections import defaultdict
from functools import cache

from .checks import RULES, Finding, Result

SPEC_RULES = {"undefined-acronym", "decimal-format", "unit-system", "duplicate"}

_ACRONYM = re.compile(r"(?<!\w)[A-ZÄÖÜ]{2,}\d*(?!\w)")
_TOKENS = re.compile(r"\w+")


def check_spec(results: list[Result], active: set[str]) -> None:
    """Append whole-spec findings to `results` in place. Keys are positions in `results` (IDs can repeat)."""
    if "duplicate" in active:
        _duplicates(results)
    if "undefined-acronym" in active:
        _acronyms(results)
    if "decimal-format" in active:
        _decimals(results)
    if "unit-system" in active:
        _unit_systems(results)


def _add(results, hits: dict[int, list[tuple[int, int]]], rule: str) -> None:
    """hits: item key -> spans. Each finding relates to every other item with a hit."""
    for key, spans in hits.items():
        related = [{"key": k, "id": results[k].req.id} for k in hits if k != key]
        text = results[key].req.text
        for s, e in spans:
            results[key].findings.append(Finding(rule, text[s:e], s, e, related))


def _duplicates(results) -> None:
    # shortcut: O(n²) pairwise, fine to a few thousand items; switch to MinHash if specs get larger
    toks = [set(_TOKENS.findall(r.req.text.lower())) for r in results]
    pairs = defaultdict(set)
    for i, a in enumerate(toks):
        if len(a) < 5:
            continue
        for j in range(i + 1, len(toks)):
            b = toks[j]
            if len(b) < 5 or min(len(a), len(b)) / max(len(a), len(b)) < 0.9:
                continue  # Jaccard ≤ size ratio, so it can't reach 0.9
            if len(a & b) / len(a | b) >= 0.9:
                pairs[i].add(j)
                pairs[j].add(i)
    for key, others in pairs.items():
        text = results[key].req.text
        related = [{"key": k, "id": results[k].req.id} for k in sorted(others)]
        results[key].findings.append(Finding("duplicate", text, 0, len(text), related))


def _acronyms(results) -> None:
    t = RULES["tolerance"]
    known = (
        set(RULES["acronyms"]["known"]) | set(t["units"]) | {r.req.id for r in results}
    )
    texts = [r.req.text for r in results]
    hits = defaultdict(lambda: defaultdict(list))
    for key, text in enumerate(texts):
        for m in _ACRONYM.finditer(text):
            if m.group(0) not in known:
                hits[m.group(0)][key].append(m.span())
    for acr, by_item in hits.items():
        a = re.escape(acr)
        expanded = re.compile(rf"\({a}\)|(?<!\w){a}\s+\(|^\s*{a}\s*[:–-]\s*\S")
        if not any(expanded.search(text) for text in texts):
            _add(results, by_item, "undefined-acronym")


@cache
def _number_with_unit(units: tuple[str, ...], decimal_only: bool) -> re.Pattern:
    alts = "|".join(re.escape(u) for u in sorted(units, key=len, reverse=True))
    num = r"\d+([.,])\d{1,2}" if decimal_only else r"\d+(?:[.,]\d+)?"
    # only numbers with a unit: "Abschnitt 4.1" is a section, not a decimal
    return re.compile(rf"(?<![\w.,]){num}(?=\s?(?:{alts})(?![\w/²]))")


def _decimals(results) -> None:
    rx = _number_with_unit(tuple(RULES["tolerance"]["units"]), True)
    by_lang = defaultdict(lambda: {".": defaultdict(list), ",": defaultdict(list)})
    for key, r in enumerate(results):
        for m in rx.finditer(r.req.text):
            by_lang[r.lang][m.group(1)][key].append(m.span())
    for lang, styles in by_lang.items():
        dots, commas = (sum(len(v) for v in styles[s].values()) for s in ".,")
        if not dots or not commas:
            continue
        # minority style; on a tie, the one that isn't the language's convention
        odd = "." if dots < commas or (dots == commas and lang == "de") else ","
        _add(results, styles[odd], "decimal-format")


def _unit_systems(results) -> None:
    t = RULES["tolerance"]
    found = {}
    for system in ("metric", "imperial"):
        rx = _number_with_unit(tuple(t[system]), False)
        unit = re.compile(
            rf"\s?(?:{'|'.join(re.escape(u) for u in sorted(t[system], key=len, reverse=True))})"
        )
        hits = defaultdict(list)
        for key, r in enumerate(results):
            for m in rx.finditer(r.req.text):
                end = unit.match(r.req.text, m.end()).end()
                hits[key].append((m.start(), end))
        found[system] = hits
    counts = {s: sum(len(v) for v in h.values()) for s, h in found.items()}
    if counts["metric"] and counts["imperial"]:
        odd = "metric" if counts["metric"] < counts["imperial"] else "imperial"
        _add(results, found[odd], "unit-system")
