"""Stdlib-only inspection of `.mph` files (COMSOL Multiphysics archives).

A `.mph` file is a ZIP archive — confirmed by magic-byte check
(`50 4b 03 04`) on every COMSOL 6.4 model in `data/`, `demo/builder/`,
and `applications/`. Inside, the model lives as a small handful of
files:

    fileversion              # one line, e.g. "2092:COMSOL 6.4.0.272"
    modelinfo.xml            # authoritative metadata (always present)
    fileids.xml              # binary-resource registry
    model.xml                # XMI root pointer
    dmodel.xml               # full model tree (for compact + solved)
    smodel.json              # alternate JSON model tree (when present)
    guimodel.xml             # last-displayed GUI state
    clusterignore.xml        # entries to skip on cluster runs
    auxiliarydatainfo.json   # auxiliary file references
    usedlicenses.txt         # one line per required COMSOL module
    geometry*.mphbin         # geometry binary
    geommanager*.mphbin      # geometry manager binary
    mesh*.mphbin / xmesh*    # mesh binary
    solution*.mphbin         # solver output (solved nodeType only)
    solutionblock*.mphbin    # solver output blocks
    solutionstatic*.mphbin   # static-solution output
    savepoint*/...           # checkpoints
    modelimage*.png          # thumbnail images
    index.txt                # preview/library index
    preview                  # 0-byte marker for `nodeType="preview"` MPHs

`MphArchive` opens a `.mph`, parses the metadata, categorizes ZIP
entries, extracts user-defined Global Parameters from `dmodel.xml`,
and produces a structured dict via `summary()`. No JVM. No JPype. No
COMSOL install required to run any of this — verified against real
fixtures from a 6.4 install.

This complements `describe.py`, which walks a *live* Java model. The
two together let the agent ask "what's in this model" without choosing
in advance whether the answer comes from disk or from a running
session.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


# ----------------------------------------------------------------------
# Entry classification
# ----------------------------------------------------------------------


_BINARY_BUCKETS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("solution",  re.compile(r"^(solution|solutionblock|solutionstatic)\d*\.mphbin$")),
    ("mesh",      re.compile(r"^x?mesh\d*\.mphbin$")),
    ("geometry",  re.compile(r"^geom(etry|manager)\d*\.mphbin$")),
    ("savepoint", re.compile(r"^savepoint\d*/")),
    ("image",     re.compile(r"^modelimage(_large)?\.png$")),
)


def _classify(name: str) -> str:
    """Bucket a ZIP-entry name into one of: solution, mesh, geometry,
    savepoint, image, data, binary, other.

    `data` covers the human-readable XML/JSON/text manifests. `binary`
    is any other `.mphbin`. `other` is the catch-all (e.g. `preview`).
    """
    for bucket, pat in _BINARY_BUCKETS:
        if pat.match(name):
            return bucket
    if name.endswith((".xml", ".json", ".txt")) or name == "fileversion":
        return "data"
    if name.endswith(".mphbin"):
        return "binary"
    return "other"


@dataclass(frozen=True)
class MphEntry:
    name: str
    size: int
    compressed_size: int
    bucket: str  # solution | mesh | geometry | savepoint | image | data | binary | other


# ----------------------------------------------------------------------
# Static model-info parsing
# ----------------------------------------------------------------------


@dataclass
class ModelInfo:
    """Parsed `modelinfo.xml`. Every field is optional because COMSOL
    omits attributes that don't apply (e.g. `lastComputationTime` is
    blank on unsolved compact models)."""

    title: str = ""
    description: str = ""
    comsol_version: str = ""
    node_type: str = ""           # "compact" | "solved" | "preview"
    model_type: str = ""          # "MODEL" | "APPLICATION" | …
    is_runnable: bool = False
    last_computation_time: str = ""
    last_computation_date: str = ""
    last_computation_version: str = ""
    expected_computation_time: str = ""
    solved_file_size: int | None = None
    compact_file_size: int | None = None
    physics: str = ""
    geometries: list[dict[str, str]] = field(default_factory=list)
    created_in: str = ""
    author: str = ""
    last_modified_by: str = ""
    raw_attrs: dict[str, str] = field(default_factory=dict)


def _parse_int(s: str | None) -> int | None:
    if s is None or s == "":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _parse_bool(s: str | None) -> bool:
    return (s or "").strip().lower() in {"on", "true", "1", "yes"}


def _parse_modelinfo(text: str) -> ModelInfo:
    root = ET.fromstring(text)
    attrs = dict(root.attrib)

    geoms = []
    geom_info = root.find("geometryInfo")
    if geom_info is not None:
        for g in geom_info.findall("geom"):
            geoms.append(dict(g.attrib))

    history = root.find("historyInfo")
    history_attrs = dict(history.attrib) if history is not None else {}

    physics_node = root.find("physicsInfo")
    physics = (physics_node.attrib.get("physics") or "") if physics_node is not None else ""

    return ModelInfo(
        title=attrs.get("title", "") or attrs.get("modelTitle", ""),
        description=attrs.get("description", "") or attrs.get("modelDescription", ""),
        comsol_version=attrs.get("comsolVersion", ""),
        node_type=attrs.get("nodeType", ""),
        model_type=attrs.get("modelType", ""),
        is_runnable=_parse_bool(attrs.get("isRunnable")),
        last_computation_time=attrs.get("lastComputationTime", ""),
        last_computation_date=attrs.get("lastComputationDate", ""),
        last_computation_version=attrs.get("lastComputationVersion", ""),
        expected_computation_time=attrs.get("expectedComputationTime", ""),
        solved_file_size=_parse_int(attrs.get("solvedFileSize")),
        compact_file_size=_parse_int(attrs.get("compactFileSize")),
        physics=physics,
        geometries=geoms,
        created_in=history_attrs.get("createdIn", ""),
        author=history_attrs.get("author", ""),
        last_modified_by=history_attrs.get("lastModifiedBy", ""),
        raw_attrs=attrs,
    )


_FILEVERSION_RE = re.compile(r"^(\d+):COMSOL\s+([\d.]+)")


def _parse_fileversion(text: str) -> tuple[int | None, str]:
    """`fileversion` is one line, e.g. ``2092:COMSOL 6.4.0.272``."""
    line = text.strip().splitlines()[0] if text.strip() else ""
    m = _FILEVERSION_RE.match(line)
    if not m:
        return None, line
    return int(m.group(1)), m.group(2)


# ----------------------------------------------------------------------
# Parameter extraction from dmodel.xml
# ----------------------------------------------------------------------


# COMSOL serializes user-defined Global Parameters as elements with
# T="33" (the type code for parameter triples). The element layout is:
#   <param T="33" param="NAME" value="VAL" reference="OPTIONAL_DOC"/>
# These appear under <ModelParamGroup> nodes (for global parameters)
# and also nested under material/feature nodes (per-feature parameters).
# We only surface the global ones here — the live-model `describe()`
# already covers feature-level properties.
_PARAM_BLOCK_RE = re.compile(
    r"<ModelParam\s+tag=\"param\"[^>]*>(.*?)</ModelParam>",
    re.DOTALL,
)
_PARAM_GROUP_RE = re.compile(
    r"<ModelParamGroup\s+tag=\"default\"[^>]*>(.*?)</ModelParamGroup>",
    re.DOTALL,
)
_PARAM_ELEMENT_RE = re.compile(
    r"<param\s+T=\"33\"\s+"
    r"param=\"(?P<name>[^\"]*)\"\s+"
    r"value=\"(?P<value>[^\"]*)\""
    r"(?:\s+reference=\"(?P<reference>[^\"]*)\")?",
)


def _extract_parameters(dmodel_xml: str) -> dict[str, dict[str, str]]:
    """Return ``{name: {"value": ..., "reference": ...}}`` for every
    user-defined Global Parameter in ``dmodel.xml``.

    Uses regex on raw text rather than `xml.etree` because dmodel.xml
    is large (>100 KB even for trivial models) and mixes namespaces;
    a regex over the relevant nesting is faster and locally reasoned-
    about. The contract is "only T=33 entries directly under the
    default ModelParamGroup", which is narrow enough to keep tight.
    """
    out: dict[str, dict[str, str]] = {}
    for param_block_match in _PARAM_BLOCK_RE.finditer(dmodel_xml):
        block = param_block_match.group(1)
        for group_match in _PARAM_GROUP_RE.finditer(block):
            group_text = group_match.group(1)
            for m in _PARAM_ELEMENT_RE.finditer(group_text):
                name = m.group("name")
                if not name:
                    continue
                out[name] = {
                    "value": m.group("value") or "",
                    "reference": m.group("reference") or "",
                }
    return out


# ----------------------------------------------------------------------
# Tag harvesting from smodel.json / dmodel.xml
# ----------------------------------------------------------------------


def _harvest_tags_from_smodel(smodel: Any, api_class: str) -> list[str]:
    """Walk a parsed `smodel.json` tree and collect every node tag
    whose ``apiClass`` matches.

    `smodel.json` is a recursive ``{nodes: [...]}`` tree where each
    node has ``apiClass`` and (usually) ``tag``. This is the same data
    the live API would return from ``model.physics().tags()`` etc.,
    but readable from disk.
    """
    out: list[str] = []
    stack: list[Any] = [smodel]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        if node.get("apiClass") == api_class and node.get("tag"):
            out.append(str(node["tag"]))
        children = node.get("nodes")
        if isinstance(children, list):
            stack.extend(children)
    return out


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------


class MphArchive:
    """Read-only inspection of a `.mph` file.

    Acts as a context manager — the underlying ZipFile is opened lazily
    on first access and closed by ``close()`` / ``__exit__``. Most
    callers will use it as ``with MphArchive(path) as mph: ...`` or
    just access properties one-shot via ``inspect_mph(path)``.

    Cheap operations (everything except ``parameters()`` and the tag
    walks) read at most ~1 KB from the archive.
    """

    _MAGIC = b"PK\x03\x04"

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        if not self._path.is_file():
            raise FileNotFoundError(f"MPH file not found: {self._path}")
        with self._path.open("rb") as fh:
            head = fh.read(4)
        if head != self._MAGIC:
            raise ValueError(
                f"{self._path} is not a ZIP archive (magic bytes "
                f"{head!r}, expected {self._MAGIC!r}). MPH files are "
                "always ZIP — this likely indicates a truncated or "
                "encrypted file."
            )
        self._zip: zipfile.ZipFile | None = None
        self._cached_modelinfo: ModelInfo | None = None
        self._cached_fileversion: tuple[int | None, str] | None = None

    # -- context manager / lifecycle --------------------------------------
    def __enter__(self) -> "MphArchive":
        self._open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    def _open(self) -> zipfile.ZipFile:
        if self._zip is None:
            self._zip = zipfile.ZipFile(self._path, "r")
        return self._zip

    # -- raw entries ------------------------------------------------------
    @property
    def path(self) -> Path:
        return self._path

    def entries(self) -> list[MphEntry]:
        """Every ZIP entry, classified into a bucket."""
        z = self._open()
        return [
            MphEntry(
                name=info.filename,
                size=info.file_size,
                compressed_size=info.compress_size,
                bucket=_classify(info.filename),
            )
            for info in z.infolist()
        ]

    def has_entry(self, name: str) -> bool:
        z = self._open()
        try:
            z.getinfo(name)
            return True
        except KeyError:
            return False

    def read_text(self, name: str, encoding: str = "utf-8") -> str:
        """Read a manifest entry as text. Raises ``KeyError`` if missing."""
        z = self._open()
        with z.open(name) as fh:
            return fh.read().decode(encoding, errors="replace")

    # -- metadata ---------------------------------------------------------
    @property
    def file_size(self) -> int:
        return self._path.stat().st_size

    @property
    def schema_version(self) -> int | None:
        """Integer schema version from ``fileversion`` (e.g. 2092 for 6.4)."""
        return self._fileversion()[0]

    @property
    def saved_in_version(self) -> str:
        """Human-readable version from ``fileversion`` (e.g. ``6.4.0.272``)."""
        return self._fileversion()[1]

    def _fileversion(self) -> tuple[int | None, str]:
        if self._cached_fileversion is None:
            try:
                text = self.read_text("fileversion")
            except KeyError:
                self._cached_fileversion = (None, "")
            else:
                self._cached_fileversion = _parse_fileversion(text)
        return self._cached_fileversion

    def model_info(self) -> ModelInfo:
        """Parsed ``modelinfo.xml``. Cached after first call."""
        if self._cached_modelinfo is None:
            try:
                text = self.read_text("modelinfo.xml")
            except KeyError:
                self._cached_modelinfo = ModelInfo()
            else:
                self._cached_modelinfo = _parse_modelinfo(text)
        return self._cached_modelinfo

    @property
    def title(self) -> str:
        return self.model_info().title

    @property
    def description(self) -> str:
        return self.model_info().description

    @property
    def node_type(self) -> str:
        """``"compact"`` | ``"solved"`` | ``"preview"`` | ``""``."""
        return self.model_info().node_type

    @property
    def is_compact(self) -> bool:
        return self.node_type == "compact"

    @property
    def is_solved(self) -> bool:
        return self.node_type == "solved"

    @property
    def is_preview(self) -> bool:
        """Preview nodeType — Application Library placeholder; only
        thumbnail + metadata, no model tree."""
        return self.node_type == "preview"

    @property
    def is_runnable(self) -> bool:
        return self.model_info().is_runnable

    def used_licenses(self) -> list[str]:
        """One line per required COMSOL module (e.g. ``["COMSOL"]``,
        or ``["COMSOL", "BatteryDesign"]`` for a battery module)."""
        try:
            text = self.read_text("usedlicenses.txt")
        except KeyError:
            return []
        return [line.strip() for line in text.splitlines() if line.strip()]

    # -- model contents ---------------------------------------------------
    def parameters(self) -> dict[str, dict[str, str]]:
        """User-defined Global Parameters: ``{name: {"value", "reference"}}``.

        Empty for ``preview``-type MPHs (no `dmodel.xml`) and for models
        that simply have no parameters defined.
        """
        try:
            dmodel = self.read_text("dmodel.xml")
        except KeyError:
            return {}
        return _extract_parameters(dmodel)

    def smodel(self) -> dict[str, Any] | None:
        """Parsed ``smodel.json`` if present, else ``None``.

        Many models include this as a JSON mirror of the model tree —
        easier to walk than `dmodel.xml`. Application Library models
        and most user-saved models include it; some hand-rolled or
        pre-6.x re-saves don't.
        """
        try:
            text = self.read_text("smodel.json")
        except KeyError:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def physics_tags(self) -> list[str]:
        s = self.smodel()
        return _harvest_tags_from_smodel(s, "Physics") if s else []

    def study_tags(self) -> list[str]:
        s = self.smodel()
        return _harvest_tags_from_smodel(s, "Study") if s else []

    def material_tags(self) -> list[str]:
        s = self.smodel()
        return _harvest_tags_from_smodel(s, "Material") if s else []

    def solution_tags(self) -> list[str]:
        s = self.smodel()
        return _harvest_tags_from_smodel(s, "Solution") if s else []

    # -- aggregated outputs ----------------------------------------------
    def size_breakdown(self) -> dict[str, int]:
        """Total uncompressed bytes per entry bucket."""
        out: dict[str, int] = {}
        for entry in self.entries():
            out[entry.bucket] = out.get(entry.bucket, 0) + entry.size
        return out

    def summary(self) -> dict[str, Any]:
        """One-shot dict summary — what an agent gets from "describe
        this MPH file" without spinning up a JVM.

        Cheap to compute (sub-second for typical models). Suitable for
        pre-flight before `comsolbatch`, post-mortem after a solve, or
        diff input.
        """
        info = self.model_info()
        sizes = self.size_breakdown()
        params = self.parameters()
        smodel = self.smodel()
        physics_list: list[str] = []
        study_list: list[str] = []
        material_list: list[str] = []
        solution_list: list[str] = []
        if smodel is not None:
            physics_list = _harvest_tags_from_smodel(smodel, "Physics")
            study_list = _harvest_tags_from_smodel(smodel, "Study")
            material_list = _harvest_tags_from_smodel(smodel, "Material")
            solution_list = _harvest_tags_from_smodel(smodel, "Solution")
        return {
            "path": str(self._path),
            "file_size": self.file_size,
            "schema_version": self.schema_version,
            "saved_in_version": self.saved_in_version,
            "title": info.title,
            "description": info.description,
            "comsol_version": info.comsol_version,
            "node_type": info.node_type,
            "model_type": info.model_type,
            "is_runnable": info.is_runnable,
            "last_computation_time": info.last_computation_time,
            "last_computation_date": info.last_computation_date,
            "expected_computation_time": info.expected_computation_time,
            "solved_file_size": info.solved_file_size,
            "compact_file_size": info.compact_file_size,
            "physics_info": info.physics,
            "geometries": info.geometries,
            "created_in": info.created_in,
            "author": info.author,
            "used_licenses": self.used_licenses(),
            "size_breakdown": sizes,
            "parameters": params,
            "physics_tags": physics_list,
            "study_tags": study_list,
            "material_tags": material_list,
            "solution_tags": solution_list,
        }


def inspect_mph(path: str | Path) -> dict[str, Any]:
    """Open a `.mph`, return its full ``summary()`` dict, close it.

    Convenience wrapper for the one-shot use case ("just tell me what's
    in this file"). For repeated reads against the same archive, use
    ``MphArchive(path)`` as a context manager.
    """
    with MphArchive(path) as mph:
        return mph.summary()


# ----------------------------------------------------------------------
# Diffing
# ----------------------------------------------------------------------


def mph_diff(a: str | Path, b: str | Path) -> dict[str, Any]:
    """Compare two `.mph` files at the metadata + entry-set + parameter
    level. Returns a dict with the differences only — same fields in
    the inputs are omitted from the output.

    Useful for "what changed between this run and the last"
    monitoring without spinning up a JVM.
    """
    with MphArchive(a) as ma, MphArchive(b) as mb:
        sa = ma.summary()
        sb = mb.summary()

        scalar_fields = (
            "title", "description", "comsol_version", "node_type",
            "model_type", "is_runnable", "schema_version",
            "saved_in_version", "last_computation_time",
            "last_computation_date", "physics_info", "author",
            "created_in", "file_size",
        )
        scalar_changed = {
            k: {"a": sa.get(k), "b": sb.get(k)}
            for k in scalar_fields
            if sa.get(k) != sb.get(k)
        }

        params_a = sa["parameters"]
        params_b = sb["parameters"]
        param_added = sorted(set(params_b) - set(params_a))
        param_removed = sorted(set(params_a) - set(params_b))
        param_changed: dict[str, dict[str, dict[str, str]]] = {}
        for name in sorted(set(params_a) & set(params_b)):
            if params_a[name] != params_b[name]:
                param_changed[name] = {"a": params_a[name], "b": params_b[name]}

        entries_a = {e.name: e for e in ma.entries()}
        entries_b = {e.name: e for e in mb.entries()}
        entry_added = sorted(set(entries_b) - set(entries_a))
        entry_removed = sorted(set(entries_a) - set(entries_b))
        entry_resized: dict[str, dict[str, int]] = {}
        for name in sorted(set(entries_a) & set(entries_b)):
            if entries_a[name].size != entries_b[name].size:
                entry_resized[name] = {
                    "a": entries_a[name].size,
                    "b": entries_b[name].size,
                }

        # Tag deltas — same shape on both sides, just diff the lists.
        def _tag_delta(name: str) -> dict[str, list[str]] | None:
            la = sa.get(name) or []
            lb = sb.get(name) or []
            if la == lb:
                return None
            added = sorted(set(lb) - set(la))
            removed = sorted(set(la) - set(lb))
            return {"added": added, "removed": removed}

        tag_changes: dict[str, dict[str, list[str]]] = {}
        for k in ("physics_tags", "study_tags", "material_tags", "solution_tags"):
            d = _tag_delta(k)
            if d is not None:
                tag_changes[k] = d

        return {
            "a": str(ma.path),
            "b": str(mb.path),
            "scalar_changes": scalar_changed,
            "parameters": {
                "added": param_added,
                "removed": param_removed,
                "changed": param_changed,
            },
            "entries": {
                "added": entry_added,
                "removed": entry_removed,
                "resized": entry_resized,
            },
            "tags": tag_changes,
        }


# ----------------------------------------------------------------------
# Text rendering
# ----------------------------------------------------------------------


def format_summary(summary: dict[str, Any]) -> str:
    """Render an ``inspect_mph()`` dict as a compact human-readable
    block. Mirrors `describe.format_text()` in tone.
    """
    lines: list[str] = []
    title = summary.get("title") or "(untitled)"
    lines.append(f'MPH: {summary["path"]}')
    lines.append(f'  title:        "{title}"')
    desc = summary.get("description")
    if desc:
        short = desc.replace("\n", " ").strip()
        if len(short) > 80:
            short = short[:77] + "..."
        lines.append(f'  description:  "{short}"')
    lines.append(
        f'  version:      {summary.get("comsol_version", "?")} '
        f'(schema {summary.get("schema_version", "?")})'
    )
    node_type = summary.get("node_type") or "?"
    runnable = "runnable" if summary.get("is_runnable") else "not runnable"
    lines.append(f'  node_type:    {node_type} ({runnable})')

    fs = summary.get("file_size") or 0
    lines.append(f'  file_size:    {fs:,} bytes')

    sizes = summary.get("size_breakdown") or {}
    if sizes:
        order = ("solution", "mesh", "geometry", "savepoint", "image", "data", "binary", "other")
        parts = [f"{k}={sizes[k]:,}" for k in order if sizes.get(k)]
        if parts:
            lines.append(f'  by_bucket:    {", ".join(parts)}')

    last = summary.get("last_computation_time")
    if last:
        lines.append(f'  last_solve:   {last} (on {summary.get("last_computation_date", "?")})')

    licenses = summary.get("used_licenses") or []
    if licenses:
        lines.append(f'  licenses:     {", ".join(licenses)}')

    physics = summary.get("physics_tags") or []
    if physics:
        lines.append(f'  physics:      {", ".join(physics)}')
    studies = summary.get("study_tags") or []
    if studies:
        lines.append(f'  studies:      {", ".join(studies)}')

    params = summary.get("parameters") or {}
    if params:
        lines.append(f'  parameters ({len(params)}):')
        for name, body in params.items():
            ref = f' — {body["reference"]}' if body.get("reference") else ""
            lines.append(f'    {name} = {body.get("value", "")}{ref}')

    return "\n".join(lines)


# ----------------------------------------------------------------------
# Inspect-pipeline probe
# ----------------------------------------------------------------------


class MphFileProbe:
    """Inspect-pipeline probe — describe `.mph` files in the workdir.

    Scans ``ctx.workdir`` for `.mph` files, opens each via the stdlib
    ZIP path (no JVM, no JPype), and emits one info Diagnostic per
    file with the headline metadata (title, node_type, schema version,
    last computation time, parameter count).

    With ``only_new=True`` (the default) it filters to files that
    weren't in ``ctx.workdir_before`` — i.e. produced by the run that
    just finished. With ``only_new=False`` it describes every `.mph`
    in the workdir, useful when the agent wants a one-shot snapshot.

    A failed parse becomes a single warning Diagnostic per file (code
    ``sim.comsol.mph_parse_failed``); the probe never crashes the
    pipeline.
    """

    name = "mph-file"

    def __init__(
        self,
        workdir_getter: Any = None,
        only_new: bool = True,
        max_files: int = 5,
        source: str = "comsol.mph",
        code_prefix: str = "comsol.mph",
    ) -> None:
        self.workdir_getter = workdir_getter or (lambda ctx: ctx.workdir)
        self.only_new = only_new
        self.max_files = max_files
        self.source = source
        self.code_prefix = code_prefix

    def applies(self, ctx: Any) -> bool:
        try:
            if not Path(self.workdir_getter(ctx)).is_dir():
                return False
        except Exception:
            return False
        # only_new mode requires a baseline; without one we'd silently
        # describe every .mph in the workdir (matching WorkdirDiffProbe's
        # contract). Skip rather than surprise the caller.
        if self.only_new and getattr(ctx, "workdir_before", None) is None:
            return False
        return True

    def probe(self, ctx: Any) -> Any:
        # Import locally so the probe class can live next to the parser
        # without forcing every consumer of `mph_inspect` to import the
        # full inspect-pipeline machinery.
        from sim.inspect import Diagnostic, ProbeResult  # noqa: PLC0415

        workdir = Path(self.workdir_getter(ctx))
        before: set[str] = set()
        if self.only_new and getattr(ctx, "workdir_before", None) is not None:
            before = set(ctx.workdir_before)

        try:
            mph_paths = sorted(p for p in workdir.rglob("*.mph") if p.is_file())
        except Exception as exc:
            return ProbeResult(diagnostics=[Diagnostic(
                severity="warning",
                source=self.source,
                code=f"{self.code_prefix}.scan_failed",
                message=f"{type(exc).__name__}: {exc}",
            )])

        # Filter to "new since baseline" if requested.
        if self.only_new and before:
            kept: list[Path] = []
            for p in mph_paths:
                try:
                    rel = str(p.relative_to(workdir)).replace("\\", "/")
                except ValueError:
                    rel = str(p)
                if rel not in before:
                    kept.append(p)
            mph_paths = kept

        diags = []
        for p in mph_paths[: self.max_files]:
            try:
                with MphArchive(p) as mph:
                    info = mph.model_info()
                    params = mph.parameters()
                    sizes = mph.size_breakdown()
                    payload = {
                        "path": str(p),
                        "title": info.title,
                        "node_type": info.node_type,
                        "is_runnable": info.is_runnable,
                        "saved_in_version": mph.saved_in_version,
                        "schema_version": mph.schema_version,
                        "last_computation_time": info.last_computation_time,
                        "physics_info": info.physics,
                        "parameter_count": len(params),
                        "size_breakdown": sizes,
                    }
            except Exception as exc:
                diags.append(Diagnostic(
                    severity="warning",
                    source=self.source,
                    code=f"{self.code_prefix}.parse_failed",
                    message=f"{p.name}: {type(exc).__name__}: {exc}",
                    extra={"path": str(p)},
                ))
                continue

            title = payload["title"] or "(untitled)"
            last = payload["last_computation_time"] or "—"
            msg = (
                f'{p.name}: {payload["node_type"] or "?"} model "{title}" '
                f'({payload["parameter_count"]} params, last solve: {last})'
            )
            diags.append(Diagnostic(
                severity="info",
                source=self.source,
                code=f"{self.code_prefix}.summary",
                message=msg,
                extra=payload,
            ))

        return ProbeResult(diagnostics=diags)


__all__ = [
    "MphArchive",
    "MphEntry",
    "ModelInfo",
    "MphFileProbe",
    "inspect_mph",
    "mph_diff",
    "format_summary",
]


# Suppress flake8/mypy "unused" if Iterable is not referenced; kept for
# type-checker clarity in future extensions.
_ = Iterable
