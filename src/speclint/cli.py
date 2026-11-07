import argparse
import json
import sys
import zipfile
from pathlib import Path

from .checks import GRADES, NONE, check, report
from .profiles import load_profile
from .readers import read
from .review import batches, main_merge


def text_report(doc: dict, verbose: bool) -> str:
    p = doc["profile"]
    out = [f"Profile: {p['name']}" + (", EARS" if p["ears"] else "")]
    for r in doc["requirements"]:
        kind = r.get("classification", {}).get("kind")
        if not verbose and (r["grade"] == NONE or kind == "information"):
            continue
        tag = (
            "info item"
            if kind == "information"
            else "no findings"
            if r["grade"] == NONE
            else r["grade"]
        )
        out.append(f"{r['id']}  [{tag}]  {r['text']}")
        for f in r["findings"]:
            mark = " (dismissed)" if f.get("dismissed") else ""
            if rel := [x["id"] for x in f.get("related", [])]:
                more = f", +{len(rel) - 5} more" if len(rel) > 5 else ""
                mark = f" (also {', '.join(rel[:5])}{more})" + mark
            out.append(
                f'    {f["severity"]:<7} {f["rule"]:<22} {f["incose"]:<9} "{f["match"]}"  {f["message"]}{mark}'
            )
    s = doc["summary"]
    out += [
        "",
        f"{s['graded']} graded items, {s['needs_clarification']} need clarification.",
        "  Grades: "
        + "  ".join(
            f"{'no findings' if g == NONE else g}:{n}"
            for g, n in s["grades"].items()
            if n
        ),
        "  Findings per category:",
    ]
    out += [f"    {doc['categories'][k]:<14} {n}" for k, n in s["categories"].items()]
    if "ears" in s:
        out.append("  EARS: " + "  ".join(f"{p}:{n}" for p, n in s["ears"].items()))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="speclint", description="Lint requirements (English/German)."
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="check requirement files")
    c.add_argument("files", nargs="+", type=Path)
    c.add_argument("--lang", choices=["auto", "en", "de"], default="auto")
    c.add_argument(
        "--profile",
        default="customer",
        help="built-in profile (customer, system) or a profile TOML file",
    )
    c.add_argument("--ears", action="store_true", help="also check EARS conformance")
    c.add_argument("--id-col", help="CSV column holding the requirement ID")
    c.add_argument("--text-col", help="CSV column holding the requirement text")
    c.add_argument("-o", "--output", type=Path, help="write the results JSON here")
    c.add_argument(
        "--fail-on",
        choices=GRADES,
        help="exit 1 if any graded item has this grade or worse",
    )
    c.add_argument(
        "-v", "--verbose", action="store_true", help="also list items without findings"
    )

    b = sub.add_parser(
        "batches", help="split findings into batch files for reviewer agents"
    )
    b.add_argument("results", type=Path)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--size", type=int, default=25)

    m = sub.add_parser(
        "merge",
        help="merge reviewer output into the results JSON (in place) and regrade",
    )
    m.add_argument("results", type=Path)
    m.add_argument("reviews", nargs="+", type=Path)

    a = p.parse_args(argv)
    if a.cmd == "batches":
        if a.size < 1:
            p.error("--size must be at least 1")
        paths = batches(
            json.loads(a.results.read_text(encoding="utf-8")), a.out, a.size
        )
        print("\n".join(map(str, paths)) or "No findings to review.")
        return 0
    if a.cmd == "merge":
        return main_merge(a.results, a.reviews)

    try:
        profile = load_profile(a.profile, a.ears)
        reqs = [r for f in a.files for r in read(f, a.id_col, a.text_col)]
    # unreadable input (unsupported format, missing column or file, broken XML or zip): exit 2, not the --fail-on code
    except (ValueError, OSError, SyntaxError, zipfile.BadZipFile) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not reqs:  # a wrong column or a file without IDs must not pass as a perfect spec
        print(
            f"error: no requirements found in {', '.join(map(str, a.files))}",
            file=sys.stderr,
        )
        return 2
    doc = report(check(reqs, a.lang, profile), profile)
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(text_report(doc, a.verbose))
    if not doc["summary"][
        "graded"
    ]:  # every item is information (from the input file): no grade, not a perfect one
        print(
            "error: nothing graded; every item is information (headings, notes, …)",
            file=sys.stderr,
        )
        return 2
    worst = [
        GRADES.index(r["grade"])
        for r in doc["requirements"]
        if r["grade"] != NONE
        and r.get("classification", {}).get("kind") != "information"
    ]
    return 1 if a.fail_on and worst and max(worst) >= GRADES.index(a.fail_on) else 0


if __name__ == "__main__":
    sys.exit(main())
