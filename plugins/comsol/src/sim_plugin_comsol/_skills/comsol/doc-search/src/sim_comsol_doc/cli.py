"""`sim-comsol-doc` CLI: search, retrieve, where. No index step — scans on demand."""

from __future__ import annotations

import argparse
import json as _json
import sys
from pathlib import Path

from . import __version__, discover, searcher


def _resolve_root(explicit: Path | None) -> Path:
    try:
        return discover.locate_doc_root(explicit)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_search(args: argparse.Namespace) -> int:
    doc_root = _resolve_root(args.comsol_root)
    hits = searcher.search(
        doc_root=doc_root,
        term=args.term,
        module=args.module,
        limit=args.limit,
        workers=args.workers,
    )

    if args.format == "json":
        payload = [
            {
                "plugin": h.plugin,
                "rel_path": h.rel_path,
                "title": h.title,
                "snippet": h.snippet,
                "match_count": h.match_count,
            }
            for h in hits
        ]
        print(_json.dumps(payload, indent=2))
        return 0

    if not hits:
        print("(no matches)")
        return 0

    for i, h in enumerate(hits, 1):
        print(f"[{i}] {h.title}  ({h.match_count} matches)")
        print(f"    path:    {h.rel_path}")
        print(f"    snippet: {h.snippet}")
        print()
    return 0


def _cmd_retrieve(args: argparse.Namespace) -> int:
    doc_root = _resolve_root(args.comsol_root)
    try:
        text = searcher.retrieve(doc_root, args.rel_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(text)
    return 0


def _cmd_where(args: argparse.Namespace) -> int:
    print(_resolve_root(args.comsol_root))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sim-comsol-doc",
        description="On-demand search over an installed COMSOL documentation tree.",
    )
    p.add_argument("--version", action="version", version=f"sim-comsol-doc {__version__}")

    sub = p.add_subparsers(dest="cmd", required=True)

    def add_root(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--comsol-root",
            type=Path,
            default=None,
            help="Override the Multiphysics install dir or doc/ plugin tree.",
        )

    ps = sub.add_parser("search", help="Scan the doc tree for a term.")
    ps.add_argument("term", help="Substring to search for (case-insensitive).")
    ps.add_argument("--module", "-m", default=None,
                    help="Substring filter on plugin folder name, e.g. 'battery' or 'models.battery'.")
    ps.add_argument("--limit", "-n", type=int, default=20)
    ps.add_argument("--workers", "-w", type=int, default=8,
                    help="Parallel file-scan workers.")
    ps.add_argument("--format", "-f", choices=("text", "json"), default="text")
    add_root(ps)
    ps.set_defaults(func=_cmd_search)

    pr = sub.add_parser("retrieve", help="Dump plain text of one HTML file.")
    pr.add_argument("rel_path", help="Plugin-relative path returned by `search`.")
    add_root(pr)
    pr.set_defaults(func=_cmd_retrieve)

    pw = sub.add_parser("where", help="Print the detected COMSOL doc root and exit.")
    add_root(pw)
    pw.set_defaults(func=_cmd_where)

    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
