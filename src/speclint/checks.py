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
GRADES = ["A", "B", "C", "D", "F"]
NONE = "none"  # no active findings: not a top grade, nothing was detected
# An obligation verb makes an item a requirement, whatever the input or Haiku says: a weak requirement must never be hidden as information.
OBLIGATION = re.compile(
    r"\b(?:shall|must|should|is required to|are required to|muss|müssen|soll|sollen|sollte|sollten|darf|dürfen|"
    r"ist zu|sind zu|hat zu|haben zu)\b",
    re.IGNORECASE,
)
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
    kind: str = ""  # "requirement" / "information" when the input file says so (object type, heading)


@dataclass
class Finding:
    rule: str
    match: str
    start: int
    end: int
    # whole-spec rules: the other affected items, [{"key", "id"}]
    related: list[dict] = field(default_factory=list)
    message: str = ""  # overrides the rule's message (EARS names what's missing)

    @property
    def spec(self) -> dict:
        return RULES["rules"][self.rule]


@dataclass
class Result:
    req: Requirement
    lang: str
    findings: list[Finding] = field(default_factory=list)
    ears: str | None = None  # EARS pattern, with --ears only


def grade(findings: list[dict]) -> str:
    """Worst severity cap among active findings, one letter lower per extra distinct warning/error rule."""
    active = [f for f in findings if not f.get("dismissed")]
    if not active:
        return NONE
    g = RULES["grading"]
    base = max(GRADES.index(g["caps"][f["severity"]]) for f in active)
    hard = {f["rule"] for f in active if f["severity"] != "info"}
    steps = max(0, len(hard) - 1) * g["pileup_step"]
    return GRADES[min(base + steps, len(GRADES) - 1)]


# A stated ASIL/SIL ("ASIL B", "ASIL-D", "ASIL B(D)", "SIL 2"). Read, never inferred.
_INTEGRITY = re.compile(
    r"(?<!\w)(ASIL)[\s-]?(QM|[A-D](?:\([A-D]\))?)(?![\w(])|(?<!\w)(SIL)[\s-]?([1-4])(?!\w)"
)


def integrity(text: str) -> str:
    m = _INTEGRITY.search(text)
    return f"{m.group(1) or m.group(3)} {m.group(2) or m.group(4)}" if m else ""


def _input_kind(req: Requirement) -> dict:
    """The input file's own kind. An obligation verb overrides "information", as it overrides the classifier."""
    if req.kind == "information" and OBLIGATION.search(req.text):
        return {"model": "obligation verb", "kind": "requirement", "score": 1.0}
    return {"model": "input", "kind": req.kind, "score": 1.0}


def _default_profile():
    from .profiles import load_profile  # profiles imports RULES from here

    return load_profile()


def report(results: list[Result], profile=None) -> dict:
    """The results document: what the CLI writes, reviewers annotate and the viewer shows."""
    profile = profile or _default_profile()
    sev = profile.severities
    doc = {
        "tool": "speclint",
        "schema_version": 2,
        "profile": {
            "name": profile.name,
            "ears": profile.ears,
            "labels": profile.labels,
        },
        "categories": CATEGORIES,
        "rules": {
            k: {
                **{f: RULES["rules"][k][f] for f in ("category", "incose", "message")},
                "severity": s,
            }
            for k, s in sev.items()
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
                        "severity": sev[f.rule],
                        **{k: f.spec[k] for k in ("category", "incose", "message")},
                        **({"related": f.related} if f.related else {}),
                        **({"message": f.message} if f.message else {}),
                    }
                    for f in r.findings
                ],
                **({"ears": {"pattern": r.ears}} if r.ears else {}),
                **({"integrity": lv} if (lv := integrity(r.req.text)) else {}),
                **({"classification": _input_kind(r.req)} if r.req.kind else {}),
            }
            for r in results
        ],
    }
    return rescore(doc)


def rescore(doc: dict) -> dict:
    """(Re)grade every item and rebuild the summary. Items classified as information are not graded."""
    reqs = doc["requirements"]
    for r in reqs:
        r["grade"] = grade(r["findings"])
    graded = [
        r for r in reqs if r.get("classification", {}).get("kind") != "information"
    ]
    active = [f for r in graded for f in r["findings"] if not f.get("dismissed")]
    doc["summary"] = {
        "requirements": len(reqs),
        "graded": len(graded),
        "needs_clarification": sum(1 for r in graded if r["grade"] != NONE),
        "grades": {
            g: sum(1 for r in graded if r["grade"] == g) for g in GRADES + [NONE]
        },
        "categories": {
            k: sum(1 for f in active if f["category"] == k) for k in CATEGORIES
        },
        "rules": {k: sum(1 for f in active if f["rule"] == k) for k in doc["rules"]},
        "dismissed": sum(1 for r in reqs for f in r["findings"] if f.get("dismissed")),
    }
    # results written before schema v2 have no profile
    if doc.get("profile", {}).get("labels"):
        counts = {}
        for r in graded:
            for name, value in r.get("labels", {}).items():
                for v in value if isinstance(value, list) else [value]:
                    counts.setdefault(name, {}).setdefault(v, 0)
                    counts[name][v] += 1
        doc["summary"]["labels"] = counts
        doc["summary"]["safety_without_level"] = sum(
            1
            for r in graded
            if r.get("labels", {}).get("safety") == "yes" and "integrity" not in r
        )
    if doc.get("profile", {}).get("ears"):
        from .ears import PATTERNS

        seen = [r["ears"]["pattern"] for r in graded if "ears" in r]
        doc["summary"]["ears"] = {p: n for p in PATTERNS if (n := seen.count(p))}
    return doc


def detect_lang(text: str) -> str | None:
    """None when the hint words don't decide (terse items like "Versorgungsspannung höchstens 16 V.")."""
    words = re.findall(r"\w+", text.lower())
    de, en = sum(w in _DE_HINTS for w in words), sum(w in _EN_HINTS for w in words)
    if de == en and re.search(r"[äöüß]", text.lower()):
        return "de"  # umlauts decide terse items the hint words can't
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
_PROPORTION = re.compile(r"\s+(?:of|der|des|aller|von)\b", re.IGNORECASE)
_HUNDRED_PERCENT = re.compile(r"^100\s?%$")


def _missing_tolerance(text: str, lang: str) -> list[Finding]:
    out, prev_end, prev_bounded = [], 0, False
    for m in _tolerance_re().finditer(text):
        if _HUNDRED_PERCENT.match(m.group(0)):
            continue  # absolute rule territory, not a tolerance problem
        if m.group(0).endswith("%") and _PROPORTION.match(text, m.end()):
            continue  # "97% of all leads" is a share of a population, not a measured value
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


_SLASHED = re.compile(r"(?<![^\s(])[^\s/()]+(?:/+[^\s/()]+)+")  # whole slashed token
_PARENS = re.compile(r"\(([^()]*)\)")


def _oblique(text: str) -> list[Finding]:
    """word/word; not units (km/h), numbers (12/05), paths or URLs, and not and/or (ambiguous-combinator)."""
    t = RULES["tolerance"]
    skip = set(t["rates"]) | set(t["units"]) | {"and/or", "und/oder"}
    out = []
    for m in _SLASHED.finditer(text):
        word = m.group(0).rstrip(".,;:!?")
        parts = word.split("/")
        if (
            word.lower() in skip
            or "//" in word
            or len(parts) > 2
            or word.replace("/", "").isupper()  # I/O, TCP/IP: fixed technical names
            or "." in parts[0]  # host/path: www.example.com/docs
            or parts[0].endswith("-")  # German pair: Ein-/Ausgänge
            or any(p[:1].isdigit() for p in parts)
        ):
            continue
        out.append(Finding("oblique", word, m.start(), m.start() + len(word)))
    return out


def _parenthetical(text: str) -> list[Finding]:
    return [
        Finding("parenthetical", m.group(0), m.start(), m.end())
        for m in _PARENS.finditer(text)
        if len(m.group(1).split()) > 3
    ]


def _clause_verb(modal):
    """The verb a modal governs, so the span starts at the modal: EN head (aux), DE oc child.
    Falls back to the modal alone (German "und darf …" hangs the modal off the conjunction)."""
    if oc := next((c for c in modal.children if c.dep_ == "oc"), None):
        return oc
    return modal.head if modal.head.i > modal.i else modal


def _modals(doc, lang: str, active: set[str]) -> list[Finding]:
    def is_modal(t, words):
        if lang == "en":
            return t.tag_ == "MD" and t.lower_ in words
        return t.lower_ in words

    def future(t):  # "wird speichern", not the passive "wird gespeichert"
        return t.lemma_ == "werden" and any(
            c.tag_ == "VVINF" and c.dep_ == "oc" for c in t.children
        )

    out = []
    if "single-thought" in active:
        words = set(RULES["rules"]["single-thought"][lang]["obligation"])
        out += [
            _span("single-thought", doc, t, _clause_verb(t))
            for t in [t for t in doc if is_modal(t, words)][1:]
        ]
    for rule in ("weak-obligation", "soll-obligation"):
        words = set(RULES["rules"][rule].get(lang, {}).get("weak", []))
        if rule in active and words:
            out += [
                Finding(rule, t.text, t.idx, t.idx + len(t.text))
                for t in doc
                if is_modal(t, words) or (rule == "weak-obligation" and future(t))
            ]
    return out


def _purpose_de(doc) -> list[Finding]:
    """ "um … zu" (KOUI, spans to its infinitive) and the conjunction "damit" (KOUS, not the adverb)."""
    return [
        _span("purpose-phrase", doc, t, t.head)
        if t.tag_ == "KOUI"
        else Finding("purpose-phrase", t.text, t.idx, t.idx + len(t.text))
        for t in doc
        if (t.tag_ == "KOUI" and t.lower_ == "um")
        or (t.tag_ == "KOUS" and t.lower_ == "damit")
    ]


_SPANNING = {"passive-no-actor", "purpose-phrase", "single-thought"}


def _span(rule: str, doc, t1, t2) -> Finding:
    """Finding covering two tokens in text order; match is the exact text between them."""
    a, b = sorted([t1, t2], key=lambda t: t.i)
    return Finding(
        rule, doc.text[a.idx : b.idx + len(b.text)], a.idx, b.idx + len(b.text)
    )


def check_doc(doc, lang: str, active: set[str]) -> list[Finding]:
    text = doc.text
    findings = []
    for rule, spec in RULES["rules"].items():
        if rule not in active:
            continue
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
    if "missing-tolerance" in active:
        findings += _missing_tolerance(text, lang)
    if "passive-no-actor" in active:
        findings += _passive_no_actor(doc, lang)
    findings += _modals(doc, lang, active)
    if "oblique" in active:
        findings += _oblique(text)
    if "parenthetical" in active:
        findings += _parenthetical(text)
    if "purpose-phrase" in active and lang == "de":
        findings += _purpose_de(doc)
    # one finding per span: phrase and lemma lists may overlap (e.g. "so schnell wie möglich")
    findings.sort(key=lambda f: (f.start, -(f.end - f.start)))
    kept, last_end = [], -1
    for f in findings:
        if f.rule in _SPANNING:  # spans whole clauses; must not hide findings inside it
            kept.append(f)
        elif f.start >= last_end:
            kept.append(f)
            last_end = f.end
    return kept


def check(reqs: list[Requirement], lang: str = "auto", profile=None) -> list[Result]:
    profile = profile or _default_profile()
    active = set(profile.severities)
    langs = [detect_lang(r.text) if lang == "auto" else lang for r in reqs]
    majority = "de" if langs.count("de") > langs.count("en") else "en"
    results = [Result(r, code or majority) for r, code in zip(reqs, langs)]
    for code in MODELS:
        group = [res for res in results if res.lang == code]
        for res, doc in (
            zip(group, nlp(code).pipe(r.req.text for r in group)) if group else ()
        ):
            res.findings = check_doc(doc, code, active)
    from .spec_checks import check_spec  # imports Finding/Result from here

    check_spec(results, active)
    if profile.ears:
        from .ears import ears_pattern

        for res in results:
            res.ears, finding = ears_pattern(res.req.text, res.lang)
            if finding:
                res.findings.append(finding)
    return results
