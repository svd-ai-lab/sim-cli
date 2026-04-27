"""Grep-style search over the COMSOL help-plugin tree, no index."""

from __future__ import annotations

import re
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


_TITLE_RE = re.compile(rb"<title>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(rb"<[^>]+>")
_WS_RE = re.compile(rb"\s+")


@dataclass
class SearchHit:
    plugin: str
    rel_path: str
    title: str
    snippet: str
    match_count: int


def _scan_one(
    path: Path,
    doc_root: Path,
    pattern: re.Pattern[bytes],
    snippet_ctx: int,
) -> SearchHit | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    matches = pattern.findall(raw)
    if not matches:
        return None

    first = pattern.search(raw)
    assert first is not None
    start = max(0, first.start() - snippet_ctx)
    end = min(len(raw), first.end() + snippet_ctx)
    window = raw[start:end]
    plain = _WS_RE.sub(b" ", _TAG_RE.sub(b" ", window)).decode("utf-8", "replace").strip()

    title_match = _TITLE_RE.search(raw)
    if title_match:
        title = title_match.group(1).decode("utf-8", "replace").strip()
    else:
        title = path.stem

    rel_path = str(path.relative_to(doc_root)).replace("\\", "/")
    plugin = rel_path.split("/", 1)[0]
    return SearchHit(
        plugin=plugin,
        rel_path=rel_path,
        title=title,
        snippet=plain,
        match_count=len(matches),
    )


def _collect_html_paths(doc_root: Path, module: str | None) -> list[Path]:
    if module:
        pattern = f"com.comsol.help.*{module}*"
    else:
        pattern = "com.comsol.help.*"
    plugins = [p for p in doc_root.glob(pattern) if p.is_dir()]
    return [f for p in plugins for f in p.rglob("*.html")]


def search(
    doc_root: Path,
    term: str,
    module: str | None = None,
    limit: int = 20,
    snippet_ctx: int = 120,
    workers: int = 8,
) -> list[SearchHit]:
    """Scan every HTML file under matching plugins, return ranked hits.

    Ranking: files with more matches rank higher.
    """
    pattern = re.compile(re.escape(term).encode("utf-8"), re.IGNORECASE)
    files = _collect_html_paths(doc_root, module)
    if not files:
        return []

    hits: list[SearchHit] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for hit in pool.map(
            lambda f: _scan_one(f, doc_root, pattern, snippet_ctx),
            files,
            chunksize=50,
        ):
            if hit is not None:
                hits.append(hit)

    hits.sort(key=lambda h: (-h.match_count, h.rel_path))
    return hits[:limit]


def retrieve(doc_root: Path, rel_path: str) -> str:
    """Read one HTML file under `doc_root` and return its extracted text."""
    target = (doc_root / rel_path).resolve()
    try:
        target.relative_to(doc_root.resolve())
    except ValueError as e:
        raise ValueError(f"Path escapes doc root: {rel_path}") from e
    if not target.is_file():
        raise FileNotFoundError(target)

    soup = BeautifulSoup(target.read_bytes(), "lxml")
    body = soup.body or soup
    return body.get_text("\n", strip=True)
