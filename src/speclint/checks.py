"""Deterministic requirement checks and grading."""

import re
import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import spacy

RULES = tomllib.loads(
    (Path(__file__).parent / "rules.toml").read_text(encoding="utf-8")
)
CATEGORIES: dict[str, str] = RULES["categories"]
PENALTY = {"error": 30, "warning": 15, "info": 3}
GRADES = [
    (95, "A+"),
    (90, "A"),
    (85, "B+"),
    (80, "B"),
    (75, "C+"),
    (70, "C"),
    (60, "D"),
    (0, "F"),
]
MODELS = {"en": "en_core_web_sm", "de": "de_core_news_sm"}

_DE_HINTS = {
    "der",
    "die",
    "das",
    "und",
    "muss",
    "soll",
    "werden",
    "wird",
    "nicht",
    "ist",
    "eine",
    "ein",
    "mit",
    "für",
    "bei",
    "des",
    "dem",
    "den",
    "sich",
    "auf",
    "zu",
    "im",
}
_EN_HINTS = {
    "the",
    "and",
    "shall",
    "must",
    "should",
    "will",
    "be",
    "is",
    "not",
    "a",
    "an",
    "with",
    "for",
    "of",
    "to",
    "in",
    "on",
    "when",
    "if",
}


@dataclass
class Requirement:
    id: str
    text: str
    source: str = ""


@dataclass
class Finding:
    rule: str
    match: str
    start: int
    end: int

    @property
    def spec(self) -> dict:
        return RULES["rules"][self.rule]


@dataclass
class Result:
    req: Requirement
    lang: str
    findings: list[Finding] = field(default_factory=list)


def grade(score: float) -> str:
    return next(g for limit, g in GRADES if score >= limit)


def score(findings: list[dict], category: str | None = None) -> int:
    """Score from report findings; findings dismissed by a review don't count."""
    return max(
        0,
        100
        - sum(
            PENALTY[f["severity"]]
            for f in findings
            if not f.get("dismissed")
            and (category is None or f["category"] == category)
        ),
    )


def report(results: list[Result]) -> dict:
    """The results document: what the CLI writes, reviewers annotate and the viewer shows."""
    doc = {
        "tool": "speclint",
        "schema_version": 1,
        "categories": CATEGORIES,
        "rules": {
            k: {f: v[f] for f in ("category", "incose", "severity", "message")}
            for k, v in RULES["rules"].items()
        },
        "requirements": [
            {
                "id": r.req.id,
                "source": r.req.source,
                "text": r.req.text,
                "lang": r.lang,
                "findings": [
                    {
                        "rule": f.rule,
                        "match": f.match,
                        "start": f.start,
                        "end": f.end,
                        **{
                            k: f.spec[k]
                            for k in ("severity", "category", "incose", "message")
                        },
                    }
                    for f in r.findings
                ],
            }
            for r in results
        ],
    }
    return rescore(doc)


def rescore(doc: dict) -> dict:
    """(Re)compute per-requirement and summary scores. Items classified as information are not graded."""
    reqs = doc["requirements"]
    for r in reqs:
        r["score"] = score(r["findings"])
        r["grade"] = grade(r["score"])
        r["categories"] = {k: score(r["findings"], k) for k in CATEGORIES}
    graded = [
        r for r in reqs if r.get("classification", {}).get("kind") != "information"
    ]
    # round before grading so the grade, the printed score and --fail-under agree
    overall = round(sum(r["score"] for r in graded) / len(graded), 1) if graded else 100
    active = [f for r in graded for f in r["findings"] if not f.get("dismissed")]
    doc["summary"] = {
        "requirements": len(reqs),
        "graded": len(graded),
        "with_findings": sum(
            1 for r in graded if any(not f.get("dismissed") for f in r["findings"])
        ),
        "score": overall,
        "grade": grade(overall),
        "categories": {
            k: round(sum(r["categories"][k] for r in graded) / len(graded), 1)
            if graded
            else 100
            for k in CATEGORIES
        },
        "grades": {g: sum(1 for r in graded if r["grade"] == g) for _, g in GRADES},
        "rules": {k: sum(1 for f in active if f["rule"] == k) for k in RULES["rules"]},
        "dismissed": sum(1 for r in reqs for f in r["findings"] if f.get("dismissed")),
    }
    return doc


def detect_lang(text: str) -> str | None:
    """None when the hint words don't decide (terse items like "Versorgungsspannung höchstens 16 V.")."""
    words = re.findall(r"\w+", text.lower())
    de, en = sum(w in _DE_HINTS for w in words), sum(w in _EN_HINTS for w in words)
    return "de" if de > en else "en" if en > de else None


@cache
def nlp(lang: str):
    return spacy.load(MODELS[lang], exclude=["ner"])


@cache
def _phrase_re(lang: str, rule: str) -> re.Pattern | None:
    phrases = RULES["rules"][rule].get(lang, {}).get("phrases", [])
    if not phrases:
        return None
    alts = "|".join(re.escape(p) for p in sorted(phrases, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alts})(?!\w)", re.IGNORECASE)


@cache
def _tolerance_re() -> re.Pattern:
    units = "|".join(
        re.escape(u) for u in sorted(RULES["tolerance"]["units"], key=len, reverse=True)
    )
    return re.compile(rf"(?<![\w.,])(\d+(?:[.,]\d+)?)\s?(?:{units})(?![\w/²])")


@cache
def _bound_re(lang: str) -> re.Pattern:
    alts = "|".join(
        re.escape(b)
        for b in sorted(RULES["tolerance"][lang]["bounds"], key=len, reverse=True)
    )
    # the bound must stand right before the value (one word between at most): "over CAN every 10 ms" is unbounded
    return re.compile(
        rf"(?:(?<!\w)(?:{alts})(?!\w)|[≤≥<>±])[.:]?(?:\s+\S+)?\s*$", re.IGNORECASE
    )


_RANGE_BEFORE = re.compile(r"\d\s*(?:-|–|\.\.|to|bis)\s*$", re.IGNORECASE)
_RANGE_GAP = re.compile(r"\s*(-|–|\.\.|to|bis|and|und)\s*", re.IGNORECASE)
_TOL_AFTER = re.compile(r"^\s*(?:±|\+/-|\+-|\+\s?\d)")  # "12 V +10 %/-5 %" too
_TOL_SECOND = re.compile(r"/\s*[+-]\s*$")  # the "-5 %" of "+10 %/-5 %"
_HUNDRED_PERCENT = re.compile(r"^100\s?%$")


def _missing_tolerance(text: str, lang: str) -> list[Finding]:
    out, prev_end, prev_bounded = [], 0, False
    for m in _tolerance_re().finditer(text):
        if _HUNDRED_PERCENT.match(m.group(0)):
            continue  # absolute rule territory, not a tolerance problem
        # the bound must belong to this value: look back no further than the previous value
        before = text[max(prev_end, m.start() - 40) : m.start()]
        bounded = bool(
            _bound_re(lang).search(before)
            or _RANGE_BEFORE.search(before)
            or _TOL_SECOND.search(before)
            or _TOL_AFTER.match(text[m.end() : m.end() + 10])
        )
        if prev_end and (gap := _RANGE_GAP.fullmatch(text[prev_end : m.start()])):
            if gap.group(1).lower() in ("and", "und"):  # "between 9 V and 16 V"
                bounded = bounded or prev_bounded
            else:  # "9 V to 16 V" is a range: both ends are bounded
                bounded = True
                if out and out[-1].end == prev_end:
                    out.pop()
        if not bounded:
            out.append(Finding("missing-tolerance", m.group(0), m.start(), m.end()))
        prev_end, prev_bounded = m.end(), bounded
    return out


def _passive_no_actor(doc, lang: str) -> list[Finding]:
    out = []
    for sent in doc.sents:
        if lang == "en":
            for tok in sent:
                if tok.dep_ == "auxpass" and not any(
                    c.dep_ == "agent" for c in tok.head.children
                ):
                    out.append(_span("passive-no-actor", doc, tok, tok.head))
        else:
            for tok in sent:
                if tok.lemma_ == "werden":
                    part = next(
                        (
                            c
                            for c in tok.children
                            if c.tag_ == "VVPP" and c.dep_ == "oc"
                        ),
                        None,
                    )
                    # the agent (sbp, "vom X") hangs off its own participle; "durch X" parses as mo
                    # and stays flagged: it can be a channel ("durch den CAN-Bus"), not an actor
                    if part is not None and not any(
                        c.dep_ == "sbp" for c in part.children
                    ):
                        out.append(_span("passive-no-actor", doc, tok, part))
    return out


def _span(rule: str, doc, t1, t2) -> Finding:
    """Finding covering two tokens in text order; match is the exact text between them."""
    a, b = sorted([t1, t2], key=lambda t: t.i)
    return Finding(
        rule, doc.text[a.idx : b.idx + len(b.text)], a.idx, b.idx + len(b.text)
    )


def check_doc(doc, lang: str) -> list[Finding]:
    text = doc.text
    findings = []
    for rule, spec in RULES["rules"].items():
        data = spec.get(lang, {})
        if rx := _phrase_re(lang, rule):
            findings += [
                Finding(rule, m.group(0), m.start(), m.end()) for m in rx.finditer(text)
            ]
        if lemmas := set(data.get("lemmas", [])):
            findings += [
                Finding(rule, t.text, t.idx, t.idx + len(t.text))
                for t in doc
                if t.lower_ in lemmas or t.lemma_.lower() in lemmas
            ]
        if pronouns := set(data.get("pronouns", [])):
            findings += [
                Finding(rule, t.text, t.idx, t.idx + len(t.text))
                for t in doc
                if t.pos_ == "PRON"
                and t.lower_ in pronouns
                and t.tag_ not in ("WDT", "WP")  # relative "that/which"
                and t.dep_ != "ep"
            ]  # German expletive "es"
    findings += _missing_tolerance(text, lang)
    findings += _passive_no_actor(doc, lang)
    # one finding per span: phrase and lemma lists may overlap (e.g. "so schnell wie möglich")
    findings.sort(key=lambda f: (f.start, -(f.end - f.start)))
    kept, last_end = [], -1
    for f in findings:
        if (
            f.rule == "passive-no-actor"
        ):  # spans whole clauses; must not hide findings inside it
            kept.append(f)
        elif f.start >= last_end:
            kept.append(f)
            last_end = f.end
    return kept


def check(reqs: list[Requirement], lang: str = "auto") -> list[Result]:
    langs = [detect_lang(r.text) if lang == "auto" else lang for r in reqs]
    majority = "de" if langs.count("de") > langs.count("en") else "en"
    results = [Result(r, code or majority) for r, code in zip(reqs, langs)]
    for code in MODELS:
        group = [res for res in results if res.lang == code]
        for res, doc in (
            zip(group, nlp(code).pipe(r.req.text for r in group)) if group else ()
        ):
            res.findings = check_doc(doc, code)
    return results
