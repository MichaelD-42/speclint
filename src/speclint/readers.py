"""Read requirements from ReqIF/ReqIFz, CSV, sphinx-needs needs.json, reStructuredText and Markdown (sphinx-needs / MyST or `ID: text` lines)."""

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .checks import RULES, Requirement

ID_COLS = [
    "id",
    "req id",
    "requirement id",
    "key",
    "absolute number",
    "object identifier",
    "nummer",
]
TEXT_COLS = [
    "text",
    "requirement",
    "requirementtext",
    "description",
    "object text",
    "anforderung",
    "anforderungstext",
    "beschreibung",
    "requirements",
]


def read(
    path: Path, id_col: str | None = None, text_col: str | None = None
) -> list[Requirement]:
    suffix = path.suffix.lower()
    if suffix in (".reqif", ".reqifz"):
        return read_reqif(path)
    if suffix in (".csv", ".tsv"):
        return read_csv(path, id_col, text_col)
    if suffix in (".rst", ".md"):
        return read_markup(path)
    if suffix == ".json":
        return read_needs_json(path)
    raise ValueError(
        f"{path}: unsupported format (use .reqif, .reqifz, .csv, .tsv, .rst, .md, sphinx-needs .json)"
    )


def read_csv(
    path: Path, id_col: str | None = None, text_col: str | None = None
) -> list[Requirement]:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:  # German Excel saves CSV as cp1252
        raw = path.read_text(encoding="cp1252")
    # delimiter from the header line: csv.Sniffer gives up on one short row
    delimiter = max(",;\t", key=raw.partition("\n")[0].count)
    rows = list(csv.DictReader(io.StringIO(raw), delimiter=delimiter))
    headers = {h.strip().lower(): h for h in (rows[0].keys() if rows else [])}

    def pick(wanted, candidates, kind):
        if wanted:
            if wanted.lower() not in headers:
                raise ValueError(
                    f"{path}: no column {wanted!r}; columns are {list(headers.values())}"
                )
            return headers[wanted.lower()]
        hit = next((headers[c] for c in candidates if c in headers), None)
        if hit is None and kind == "text":
            raise ValueError(
                f"{path}: no text column found; pass --text-col. Columns are {list(headers.values())}"
            )
        return hit

    tcol, icol = pick(text_col, TEXT_COLS, "text"), pick(id_col, ID_COLS, "id")
    return [
        Requirement(
            ((row[icol] or "").strip() if icol else "") or f"row {n}",
            row[tcol] or "",
            str(path),
        )
        for n, row in enumerate(rows, start=2)
        if (row[tcol] or "").strip()
    ]


def read_reqif(path: Path) -> list[Requirement]:
    if path.suffix.lower() == ".reqifz":
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".reqif")), None)
            if name is None:
                raise ValueError(f"{path}: no .reqif file inside the archive")
            root = ET.fromstring(z.read(name))
    else:
        root = ET.parse(path).getroot()

    def tag(el):
        return el.tag.split("}")[-1]

    names = {
        d.get("IDENTIFIER"): d.get("LONG-NAME", "")
        for d in root.iter()
        if tag(d).startswith("ATTRIBUTE-DEFINITION-") and d.get("IDENTIFIER")
    }
    enums = {
        e.get("IDENTIFIER"): e.get("LONG-NAME", "")
        for e in root.iter()
        if tag(e) == "ENUM-VALUE"
    }
    objects = {}
    for obj in root.findall(".//{*}SPEC-OBJECT"):
        values = {}
        for val in obj.iter():
            t = tag(val)
            if not t.startswith("ATTRIBUTE-VALUE-"):
                continue
            ref = next(
                (
                    r.text
                    for r in val.iter()
                    if tag(r).startswith("ATTRIBUTE-DEFINITION-")
                    and tag(r).endswith("-REF")
                ),
                None,
            )
            if t == "ATTRIBUTE-VALUE-XHTML":
                the_value = next((v for v in val if tag(v) == "THE-VALUE"), None)
                text = (
                    " ".join(_xhtml_text(the_value).split())
                    if the_value is not None
                    else ""
                )
            elif (
                t == "ATTRIBUTE-VALUE-ENUMERATION"
            ):  # the value is a reference to an ENUM-VALUE
                text = ", ".join(
                    enums.get(r.text, r.text or "")
                    for r in val.iter()
                    if tag(r) == "ENUM-VALUE-REF"
                )
            else:
                text = val.get("THE-VALUE", "")
            values[names.get(ref, ref)] = text
        objects[obj.get("IDENTIFIER")] = values
    # document order is the SPEC-HIERARCHY (pre-order); objects outside it follow in file order
    order = [
        r.text
        for h in root.iter()
        if tag(h) == "SPEC-HIERARCHY"
        for o in h
        if tag(o) == "OBJECT"
        for r in o
        if tag(r) == "SPEC-OBJECT-REF" and r.text in objects
    ]
    order = list(dict.fromkeys(order + list(objects)))
    reqs = []
    for ident in order:
        values = objects[ident]
        text = values.get("ReqIF.Text") or next(
            (v for k, v in values.items() if "text" in (k or "").lower() and v), ""
        )
        rid = values.get("ReqIF.ForeignID") or ident
        if text.strip():
            reqs.append(Requirement(rid, text, str(path), _kind(values)))
        elif heading := values.get("ReqIF.ChapterName", "").strip():
            reqs.append(Requirement(rid, heading, str(path), "information"))
    return reqs


def _kind(values: dict) -> str:
    """requirement / information from the first object-type attribute with a known value, else ""."""
    inp = RULES["input"]
    for attr in inp["kind_attributes"]:
        value = (
            next(
                (v for k, v in values.items() if (k or "").lower() == attr.lower()), ""
            )
            .strip()
            .lower()
        )
        for kind in ("requirement", "information"):
            if value in inp[kind]:
                return kind
    return ""


def read_needs_json(path: Path) -> list[Requirement]:
    """sphinx-needs builder output: versions[current_version].needs; only the listed need types."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        versions = data["versions"]
        needs = versions.get(data.get("current_version")) or next(
            iter(versions.values())
        )
        needs = needs["needs"]
    except (ValueError, KeyError, TypeError, AttributeError, StopIteration) as e:
        raise ValueError(f"{path}: not a sphinx-needs needs.json ({e!r})") from e
    types = {t.lower() for t in RULES["input"]["need_types"]}
    picked = [
        n
        for n in needs.values()
        if str(n.get("type", "")).lower() in types and not n.get("is_external")
    ]
    # document order: by document, then line; needs without a location keep file order at the end
    picked.sort(
        key=lambda n: (
            n.get("docname") is None,
            n.get("docname") or "",
            n.get("lineno") or 0,
        )
    )
    reqs = []
    for n in picked:
        text = " ".join(str(n.get("content") or n.get("description") or "").split())
        reqs.append(
            Requirement(str(n["id"]), text or str(n.get("title", "")), str(path))
        )
    return reqs


_BLOCK = {"p", "div", "br", "li", "ul", "ol", "table", "tr", "td", "th"}


def _xhtml_text(el) -> str:
    """Text of an XHTML tree: block elements break words, inline ones (Im <b>Fehler</b>fall) don't."""
    out = [el.text or ""]
    for child in el:
        gap = " " if child.tag.split("}")[-1] in _BLOCK else ""
        out += [gap, _xhtml_text(child), gap, child.tail or ""]
    return "".join(out)


# sphinx-needs directive in RST (`.. req:: Title`) or MyST (```{req} Title / :::{req} Title)
_RST_DIRECTIVE = re.compile(r"^(\s*)\.\. ([\w-]+):: ?(.*)$")
_MYST_DIRECTIVE = re.compile(r"^(```+|:::+)\{([\w-]+)\} ?(.*)$")
_CODE_FENCE = re.compile(r"^\s*(```+|~~~+)")


def _closes(line: str, fence: str) -> bool:
    """CommonMark: a closing fence is the opening fence or longer, nothing else on the line."""
    s = line.strip()
    return s.startswith(fence) and s == fence[0] * len(s)


_OPTION = re.compile(r"^\s*:([\w-]+):\s*(.*)$")
_ID_LINE = re.compile(
    r"^\s*(?:[-*]\s+)?\**\[?([A-Z][A-Z0-9]*(?:[-_.][A-Z0-9]+)*[-_.]?\d+)\]?\**\s*[:–-]\s+(.+)$"
)


def read_markup(path: Path) -> list[Requirement]:
    lines = path.read_text(encoding="utf-8").splitlines()
    reqs, i = [], 0
    while i < len(lines):
        line = lines[i]
        if m := _RST_DIRECTIVE.match(line):
            indent, kind, title = len(m.group(1)), m.group(2), m.group(3)
            body, i = [], i + 1
            while i < len(lines) and (
                not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent
            ):
                body.append(lines[i])
                i += 1
            reqs += _need(body, kind, title, path)
            continue
        if m := _MYST_DIRECTIVE.match(line):
            fence, kind, title = m.group(1), m.group(2), m.group(3)
            body, i = [], i + 1
            while i < len(lines) and not _closes(lines[i], fence):
                body.append(lines[i])
                i += 1
            reqs += _need(body, kind, title, path)
        elif m := _CODE_FENCE.match(
            line
        ):  # examples in code blocks are not requirements
            i += 1
            while i < len(lines) and not _closes(lines[i], m.group(1)):
                i += 1
        elif m := _ID_LINE.match(line):
            reqs.append(Requirement(m.group(1), m.group(2), str(path)))
        i += 1
    return reqs


def _need(body: list[str], kind: str, title: str, path: Path) -> list[Requirement]:
    opts, content = {}, []
    for ln in body:
        if not content and (m := _OPTION.match(ln)):
            opts[m.group(1)] = m.group(2)
        elif ln.strip() or content:
            content.append(ln.strip())
    if (
        "id" not in opts
    ):  # not a sphinx-needs object (e.g. a note or code-block directive)
        return []
    if kind.lower() not in {t.lower() for t in RULES["input"]["need_types"]}:
        return []  # a need type that isn't a requirement (test, impl, ...)
    text = " ".join(" ".join(content).split()) or title
    return [Requirement(opts["id"], text, str(path))]
