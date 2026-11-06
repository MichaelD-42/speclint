import argparse
import json
import sys
import zipfile
from pathlib import Path

from .checks import check, report, rescore
from .readers import read
from .review import batches, main_merge


def text_report(doc: dict, verbose: bool) -> str:
    out = []
    for r in doc["requirements"]:
        kind = r.get("classification", {}).get("kind")
        if not verbose and (not r["findings"] or kind == "information"):
            continue
        tag = "info item" if kind == "information" else f"{r['grade']} {r['score']}%"
        out.append(f"{r['id']}  [{tag}]  {r['text']}")
        for f in r["findings"]:
            mark = " (dismissed)" if f.get("dismissed") else ""
            out.append(
                f'    {f["severity"]:<7} {f["rule"]:<22} {f["incose"]:<9} "{f["match"]}"  {f["message"]}{mark}'
            )
    s = doc["summary"]
    out += [
        "",
        (
            f"{s['requirements']} items, {s['graded']} graded, {s['with_findings']} with findings. "
            f"Overall {s['grade']} ({s['score']:.0f}%)"
        ),
    ]
    out += [
        f"  {doc['categories'][k]:<14} {v:5.1f}%" for k, v in s["categories"].items()
    ]
    out.append(
        "  Grades: " + "  ".join(f"{g}:{n}" for g, n in s["grades"].items() if n)
    )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="speclint", description="Lint requirements (English/German)."
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="check requirement files")
    c.add_argument("files", nargs="+", type=Path)
    c.add_argument("--lang", choices=["auto", "en", "de"], default="auto")
    c.add_argument("--id-col", help="CSV column holding the requirement ID")
    c.add_argument("--text-col", help="CSV column holding the requirement text")
    c.add_argument(
        "--classify",
        action="store_true",
        help="label requirement vs information with GLiClass (extra 'classify')",
    )
    c.add_argument("-o", "--output", type=Path, help="write the results JSON here")
    c.add_argument(
        "--fail-under",
        type=int,
        default=0,
        help="exit 1 if the overall score is below this percentage",
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
        help="merge reviewer output into the results JSON (in place) and rescore",
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
        reqs = [r for f in a.files for r in read(f, a.id_col, a.text_col)]
    # unreadable input (unsupported format, missing column or file, broken XML or zip): exit 2, not the --fail-under code
    except (ValueError, OSError, SyntaxError, zipfile.BadZipFile) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not reqs:  # a wrong column or a file without IDs must not pass as a perfect spec
        print(
            f"error: no requirements found in {', '.join(map(str, a.files))}",
            file=sys.stderr,
        )
        return 2
    doc = report(check(reqs, a.lang))
    if a.classify:
        from .classify import classify

        doc = rescore(classify(doc))
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(text_report(doc, a.verbose))
    if not doc["summary"][
        "graded"
    ]:  # all classified as information: no grade, not a perfect one
        print(
            "error: nothing graded; every item was classified as information",
            file=sys.stderr,
        )
        return 2
    return 1 if doc["summary"]["score"] < a.fail_under else 0


if __name__ == "__main__":
    sys.exit(main())
