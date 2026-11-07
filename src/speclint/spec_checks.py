"""Checks across the whole run: each finding goes on every affected item and names the others in `related`."""

import math
import re
from collections import Counter, defaultdict
from functools import cache

from .checks import RULES, Finding, Result

SPEC_RULES = {"undefined-acronym", "decimal-format", "unit-system", "duplicate"}

_ACRONYM = re.compile(r"(?<!\w)[A-ZÄÖÜ]{2,}\d*(?!\w)")
_TOKENS = re.compile(r"\w+")
_A = r"[A-ZÄÖÜ]{2,}\d*"
# "Electronic Control Unit (ECU)", "ECU (Electronic Control Unit)", a glossary line "ECU: …"
_EXPANDED = re.compile(rf"\(({_A})\)|(?<!\w)({_A})\s+\(|^\s*({_A})\s*[:–-]\s*\S")


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


def _duplicate_pairs(toks: list[set[str]], t: float = 0.9) -> set[tuple[int, int]]:
    """Pairs i < j with at least 5 tokens each and Jaccard ≥ t. Exact prefix-filter join, not O(n²):
    with tokens ordered rarest first, two sets with Jaccard ≥ t share a token among the first
    n - ceil(t·n) + 1 tokens of each."""
    freq = Counter(w for s in toks for w in s)
    index, pairs = defaultdict(list), set()
    for i, s in enumerate(toks):
        if len(s) < 5:
            continue
        ordered = sorted(s, key=lambda w: (freq[w], w))
        prefix = ordered[: len(s) - math.ceil(t * len(s) - 1e-9) + 1]
        cands = {j for w in prefix for j in index[w]}
        for j in cands:
            b = toks[j]
            if (
                min(len(s), len(b)) / max(len(s), len(b)) >= t
                and len(s & b) / len(s | b) >= t
            ):
                pairs.add((j, i))
        for w in prefix:
            index[w].append(i)
    return pairs


def _duplicates(results) -> None:
    toks = [set(_TOKENS.findall(r.req.text.lower())) for r in results]
    others = defaultdict(set)
    for i, j in _duplicate_pairs(toks):
        others[i].add(j)
        others[j].add(i)
    for key, rel in others.items():
        text = results[key].req.text
        related = [{"key": k, "id": results[k].req.id} for k in sorted(rel)]
        results[key].findings.append(Finding("duplicate", text, 0, len(text), related))


def _acronyms(results) -> None:
    t = RULES["tolerance"]
    # IDs and their letter prefixes (LH in "LH-001") are references, not acronyms
    ids = {r.req.id for r in results}
    prefixes = {p for i in ids for p in re.findall(r"[A-Za-zÄÖÜäöü]+", i)}
    known = set(RULES["acronyms"]["known"]) | set(t["units"]) | ids | prefixes
    texts = [r.req.text for r in results]
    hits = defaultdict(lambda: defaultdict(list))
    for key, text in enumerate(texts):
        for m in _ACRONYM.finditer(text):
            if m.group(0) not in known:
                hits[m.group(0)][key].append(m.span())
    expanded = {
        m.group(1) or m.group(2) or m.group(3)
        for t in texts
        for m in _EXPANDED.finditer(t)
    }
    for acr, by_item in hits.items():
        if acr not in expanded:
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
