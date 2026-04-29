"""Inspect probe framework + core probes.

═══════════════════════════════════════════════════════════════════════════
Why this module exists (read this before touching a probe)
═══════════════════════════════════════════════════════════════════════════

The inspect layer is the **agent decision-support layer**. It does NOT act;
acting is the job of `run` / `exec` / external automation scripts. What it
does is answer two questions after every `run / connect / exec`:

  1. "Did what I just do achieve my goal?" → yes → next step; no → question 2
  2. "Where should I look to find out why?" → the channels, in cost order

Channels are structured so an agent queries them cheap-first:

    cheapest ────────────────────────────────────────────────► most expensive
    #1 Process meta        pure stdlib, always on
    #3 StdoutJsonTail      parse a JSON line — free
    #3+ PythonTraceback    read traceback string — free
    #4 SdkAttribute        read session.attr — cheap unless SDK is slow
    #5 DomainExceptionMap  regex post-processor — free
    #2 stderr regex        read text stream — cheap
    #6 TUI echo            ditto, driver-specific
    #7 Log file            open a file — cheap
    #9 WorkdirDiff         os.walk + stat — I/O but fast
    #8a GUI dialog enum    pywinauto UIA walk — seconds
    #8b Screenshot         PIL bbox capture — seconds + disk

Constraints this design places on every probe implementation:

  • `Diagnostic.code` MUST be machine-switchable (e.g.
    "fluent.sdk.attr_not_found", "python.NameError", "sim.runtime.snippet_timeout")
    — never free-form text. Agents switch on it without NLP.
  • `Diagnostic.severity` IS the agent threshold signal:
    info = "I noticed it, don't panic"
    warning = "look if you care"
    error = "you must act"
    A modal dialog that blocks agent progress MUST be severity=error,
    not info — otherwise the decision tree in the agent skips it.
  • A probe NEVER acts. If you want to dismiss a dialog, automate a key
    press, or re-start a crashed session, that's `run`/`exec`/`driver.launch`
    territory (see e.g. dialog-watcher pattern in comsol driver launch),
    not a probe.
  • Driver-side probe lists are declarative: driver says "I need these
    channels with these rule tables / these reader closures" — probe
    classes themselves stay driver-agnostic.

See `sim-proj/inspect-probes-PLAN.md §二·六` and
    `sim-proj/inspect-probes-PLAN-phase2.md "Raison d'être"` for the full
    rationale and the agent decision tree.

═══════════════════════════════════════════════════════════════════════════
Implementation notes
═══════════════════════════════════════════════════════════════════════════

Implements §三 (根本思路) "第 1 档 通用观察契约":
    ok / wall_time_s / started_at / diagnostics[{severity, message, source, code}]
                                  / artifacts[{path, size, mtime, role}]

Single-file Phase 1-2 design. Expand into a package only when we cross any of:
- file > ~500 lines
- add a platform-specific probe that needs its own helper files
- we hit real maintenance friction from co-location

Two `Diagnostic` classes coexist and should NEVER be merged:
- `sim.driver.Diagnostic`  — lint-time ({level, message, line}), pre-existing
- `sim.inspect.Diagnostic` — run-time ({severity, message, source, code, extra})
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable


# ── schema dataclasses ─────────────────────────────────────────────────────────


@dataclass
class Diagnostic:
    """Run-time observation diagnostic. Fields align with 根本思路.md §三.

    - severity: "error" | "warning" | "info"
    - message:  human-readable text
    - source:   channel identifier, e.g. "stderr" / "stdout" / "log:<path>"
                / "sdk:<ExcClass>" / "gui:<dialog-title>" / "process" / "traceback"
    - code:     opaque, driver-specific machine identifier (e.g.
                "openfoam.bc.missing", "fluent.rpc.timeout", "python.NameError")
    - extra:    escape hatch for per-channel metadata (line numbers, window
                handles, exception type, etc.) — never auto-promoted to top level
    """

    severity: str
    message: str
    source: str
    code: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "message": self.message,
            "source": self.source,
            "code": self.code,
            "extra": dict(self.extra),
        }


@dataclass
class Artifact:
    """Run-time output artifact. Fields align with 根本思路.md §三."""

    path: str
    size: int | None = None
    mtime: str | None = None          # ISO 8601 UTC string
    role: str = ""                     # e.g. "solver-log" / "case" / "data" / "screenshot"

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "size": self.size,
            "mtime": self.mtime,
            "role": self.role,
        }


@dataclass
class ProbeResult:
    """What a single probe returns."""

    diagnostics: list[Diagnostic] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class InspectCtx:
    """Input bundle handed to every probe.

    Contains every observable the runner/session has collected. Probes MUST
    NOT mutate it.
    """

    stdout: str
    stderr: str
    workdir: str
    wall_time_s: float
    exit_code: int
    driver_name: str
    session_ns: dict[str, Any]          # live session namespace; {} for one-shot
    workdir_before: list[str] | None = None
    extras: dict[str, Any] = field(default_factory=dict)


# ── Protocol + collect loop ────────────────────────────────────────────────────


@runtime_checkable
class InspectProbe(Protocol):
    """Structural type for anything the probe pipeline will call."""

    name: str

    def applies(self, ctx: InspectCtx) -> bool: ...

    def probe(self, ctx: InspectCtx) -> ProbeResult: ...


def collect_diagnostics(
    probes: list[InspectProbe], ctx: InspectCtx
) -> tuple[list[Diagnostic], list[Artifact]]:
    """Run every probe, concatenate results, isolate per-probe exceptions.

    Before each probe runs, `ctx.extras["prior_diagnostics"]` is populated
    with the accumulated diagnostics collected so far. Post-processor probes
    like `DomainExceptionMapProbe` use this to upgrade/augment earlier
    outputs without mutating them.

    A crashing probe emits a synthetic `Diagnostic(severity="warning",
    code="sim.inspect.probe_crashed", ...)` so the pipeline never becomes
    load-bearing on probe correctness.
    """
    diagnostics: list[Diagnostic] = []
    artifacts: list[Artifact] = []
    for p in probes:
        # Make already-collected diagnostics visible to this probe
        if ctx.extras is None:
            ctx.extras = {}
        ctx.extras["prior_diagnostics"] = list(diagnostics)
        try:
            if not p.applies(ctx):
                continue
            result = p.probe(ctx)
        except Exception as exc:
            diagnostics.append(Diagnostic(
                severity="warning",
                message=f"probe {p.name!r} crashed: {type(exc).__name__}: {exc}",
                source=f"sim.inspect:{p.name}",
                code="sim.inspect.probe_crashed",
            ))
            continue
        diagnostics.extend(result.diagnostics)
        artifacts.extend(result.artifacts)
    return diagnostics, artifacts


# ── probes ─────────────────────────────────────────────────────────────────────


class ProcessMetaProbe:
    """Channel #1 — process meta. Turns exit_code + wall_time into one Diagnostic.

    Always applies. Info-level when exit_code == 0; error when non-zero.
    """

    name = "process-meta"

    def applies(self, ctx: InspectCtx) -> bool:
        return True

    def probe(self, ctx: InspectCtx) -> ProbeResult:
        if ctx.exit_code == 0:
            diag = Diagnostic(
                severity="info",
                message=f"exit 0 in {ctx.wall_time_s:.2f}s",
                source="process",
                code="sim.process.exit_zero",
                extra={"exit_code": 0, "wall_time_s": ctx.wall_time_s},
            )
        else:
            diag = Diagnostic(
                severity="error",
                message=f"exit {ctx.exit_code} after {ctx.wall_time_s:.2f}s",
                source="process",
                code="sim.process.exit_nonzero",
                extra={"exit_code": ctx.exit_code, "wall_time_s": ctx.wall_time_s},
            )
        return ProbeResult(diagnostics=[diag])


class TextStreamRulesProbe:
    """Channel #2 / #7 — regex rules over any text stream.

    One probe class, many instances. Driver declares `source` (channel id
    like "stderr" / "log:log.simpleFoam") + `text_selector` (closure over
    InspectCtx that returns the text to scan) + `rules` (list of
    {pattern, severity, code, message_template?}).

    Each rule match emits one Diagnostic. `extra.line` = 1-based line
    number of the match; `extra.match` = first matching group if any.
    `message_template` substitution: `{match}` / `{group1}` / `{group2}` / ...
    If no template given, use the matched line (trimmed).
    """

    name = "text-stream-rules"

    def __init__(
        self,
        source: str,
        text_selector: Callable[[InspectCtx], str],
        rules: list[dict],
    ):
        self.source = source
        self.text_selector = text_selector
        self.rules = rules
        # Pre-compile for perf + fail-fast on bad regex
        self._compiled = [(re.compile(r["pattern"]), r) for r in rules]

    def applies(self, ctx: InspectCtx) -> bool:
        try:
            text = self.text_selector(ctx)
        except Exception:
            return False
        return bool(text and text.strip())

    def probe(self, ctx: InspectCtx) -> ProbeResult:
        text = self.text_selector(ctx)
        diags: list[Diagnostic] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            for regex, rule in self._compiled:
                m = regex.search(line)
                if not m:
                    continue
                template = rule.get("message_template")
                if template:
                    subs: dict[str, str] = {"match": m.group(0)}
                    for i, g in enumerate(m.groups(), start=1):
                        subs[f"group{i}"] = g or ""
                    try:
                        message = template.format(**subs)
                    except (KeyError, IndexError):
                        message = template
                else:
                    message = line.strip()
                diags.append(Diagnostic(
                    severity=rule["severity"],
                    message=message,
                    source=self.source,
                    code=rule["code"],
                    extra={"line": lineno, "match": m.group(0)},
                ))
        return ProbeResult(diagnostics=diags)


_TRACEBACK_HEADER = "Traceback (most recent call last):"
# Match final "ExcClass: message" line after a traceback block
_EXC_LINE_RE = re.compile(r"^(\w+(?:\.\w+)*):\s*(.*)$")


class PythonTracebackProbe:
    """Channel #3 extension — detect + parse Python tracebacks.

    Looks at `ctx.stderr` first, then `ctx.session_ns.get("_session_error")`
    (convention used by session runtimes that capture exc via
    `traceback.format_exc()`).

    Emits one Diagnostic per distinct traceback found, with
    `code = "python.<ExcClass>"`, `source = "traceback"`, `message` = the
    final exception line (e.g. "name 'x' is not defined").
    """

    name = "python-traceback"

    def applies(self, ctx: InspectCtx) -> bool:
        sources = (
            ctx.stderr or "",
            ctx.session_ns.get("_session_error", "") if ctx.session_ns else "",
        )
        return any(_TRACEBACK_HEADER in s for s in sources)

    def probe(self, ctx: InspectCtx) -> ProbeResult:
        diags: list[Diagnostic] = []
        seen: set[tuple[str, str]] = set()
        for text in (
            ctx.stderr or "",
            ctx.session_ns.get("_session_error", "") if ctx.session_ns else "",
        ):
            for d in self._parse_tracebacks(text):
                key = (d.code, d.message)
                if key in seen:
                    continue
                seen.add(key)
                diags.append(d)
        return ProbeResult(diagnostics=diags)

    def _parse_tracebacks(self, text: str) -> list[Diagnostic]:
        if not text or _TRACEBACK_HEADER not in text:
            return []
        out: list[Diagnostic] = []
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            if lines[i].strip() == _TRACEBACK_HEADER:
                # Scan down for the final "ExcClass: message" line
                j = i + 1
                exc_class = None
                exc_msg = ""
                last_file_line = None
                while j < len(lines):
                    stripped = lines[j].strip()
                    if not stripped:
                        j += 1
                        continue
                    if stripped.startswith("File "):
                        last_file_line = stripped
                        j += 1
                        continue
                    if stripped.startswith(_TRACEBACK_HEADER):
                        # another traceback begins — stop
                        break
                    if lines[j].startswith(" "):
                        # indented continuation (code line or caret)
                        j += 1
                        continue
                    m = _EXC_LINE_RE.match(stripped)
                    if m:
                        exc_class, exc_msg = m.group(1), m.group(2)
                        j += 1
                        break
                    j += 1
                if exc_class:
                    extra: dict = {}
                    if last_file_line:
                        extra["last_frame"] = last_file_line
                    out.append(Diagnostic(
                        severity="error",
                        message=exc_msg or exc_class,
                        source="traceback",
                        code=f"python.{exc_class}",
                        extra=extra,
                    ))
                i = j
            else:
                i += 1
        return out


class RuntimeTimeoutProbe:
    """Synthetic — emits a structured diagnostic when a session exec was
    interrupted by per-snippet timeout.

    Looks at `ctx.extras["timeout_hit"]` (bool) + `ctx.extras["timeout_s"]`
    (float) populated by the driver's `run()` when `call_with_timeout` came
    back with `hung=True`.

    Without this, a timeout would only show up as a free-text
    `record.error` string — nothing to switch on.
    """

    name = "runtime-timeout"

    def applies(self, ctx: InspectCtx) -> bool:
        return bool((ctx.extras or {}).get("timeout_hit"))

    def probe(self, ctx: InspectCtx) -> ProbeResult:
        extras = ctx.extras or {}
        t = extras.get("timeout_s", 0.0)
        elapsed = extras.get("timeout_elapsed_s", t)
        return ProbeResult(diagnostics=[Diagnostic(
            severity="error",
            source="sim.runtime",
            code="sim.runtime.snippet_timeout",
            message=(f"snippet exceeded timeout_s={t} (elapsed {elapsed:.1f}s); "
                     f"session is likely unusable — disconnect + re-launch"),
            extra={"timeout_s": t, "elapsed_s": elapsed},
        )])


class StdoutJsonTailProbe:
    """Channel #3 — stdout JSON-tail convention.

    Scans stdout in reverse for the last line that parses as a JSON object,
    and emits one info Diagnostic with source="stdout:json" and the parsed
    dict in `extra.value`. Also falls back to `session_ns.get("_result")`
    if that is a dict/list and no stdout JSON line is found.

    This makes the existing "print(json.dumps(...))" pattern — used by ~30
    of our drivers' parse_output() — inspectable from the probe layer too,
    without each driver having to duplicate the scan.
    """

    name = "stdout-json-tail"

    def applies(self, ctx: InspectCtx) -> bool:
        if ctx.stdout and ctx.stdout.strip():
            return True
        res = (ctx.session_ns or {}).get("_result")
        return isinstance(res, (dict, list))

    def probe(self, ctx: InspectCtx) -> ProbeResult:
        import json  # noqa: PLC0415

        parsed: Any = None
        found_from = None
        line_no = None
        for candidate in reversed((ctx.stdout or "").splitlines()):
            s = candidate.strip()
            if not s or s[:1] not in "{[":
                continue
            try:
                parsed = json.loads(s)
                found_from = "stdout"
                line_no = len((ctx.stdout or "").splitlines()) - list(
                    reversed((ctx.stdout or "").splitlines())
                ).index(candidate)
                break
            except json.JSONDecodeError:
                continue

        if parsed is None:
            res = (ctx.session_ns or {}).get("_result")
            if isinstance(res, (dict, list)):
                parsed = res
                found_from = "session_result"

        if parsed is None:
            return ProbeResult()

        try:
            preview = json.dumps(parsed, ensure_ascii=False, default=str)
        except Exception:
            preview = repr(parsed)
        if len(preview) > 300:
            preview = preview[:297] + "..."

        return ProbeResult(diagnostics=[Diagnostic(
            severity="info",
            message=f"parsed {found_from}: {preview}",
            source=f"stdout:json",
            code="sim.stdout.json_tail",
            extra={
                "source_kind": found_from,
                "line": line_no,
                "value": parsed,
            },
        )])


class SdkAttributeProbe:
    """Channel #4 — SDK object attribute reader.

    Two construction modes (mutually exclusive):

    1. `attr_paths=["setup.models.viscous.model", ...]` — walks `getattr` chain
       on `ctx.session_ns["session"]`; if the final attribute is callable
       (pyfluent wraps many properties as SettingsObject() callables), calls
       it with no args. Used by Phase 1 Fluent driver.

    2. `readers=[(label, callable(session) -> value), ...]` — the caller
       provides arbitrary extractors. Used by COMSOL driver, whose Java API
       (`model.feature('stat1').getString('type')`) does not fit a
       getattr-chain. Label appears in `source=<prefix>:<label>` and
       `code=<code_prefix>.<label>`.

    Successful read → info Diagnostic. Raised exception → warning
    Diagnostic with `code="sim.sdk.attr_read_failed"`, probe continues
    past it to the next path/reader.
    """

    name = "sdk-attribute"

    def __init__(
        self,
        attr_paths: list[str] | None = None,
        readers: list[tuple[str, Callable[[Any], Any]]] | None = None,
        call_callables: bool = True,
        source_prefix: str = "sdk:attr",
        code_prefix: str = "fluent.sdk.attr",
    ):
        if attr_paths is not None and readers is not None:
            raise ValueError(
                "SdkAttributeProbe: pass EITHER attr_paths OR readers, not both"
            )
        if attr_paths is None and readers is None:
            raise ValueError(
                "SdkAttributeProbe: must pass attr_paths or readers"
            )
        self.call_callables = call_callables
        self.source_prefix = source_prefix
        self.code_prefix = code_prefix
        if readers is not None:
            # Readers mode: caller supplies (label, callable) pairs
            self._readers: list[tuple[str, Callable[[Any], Any]]] = list(readers)
        else:
            # attr_paths mode: synthesize readers from getattr chains
            self._readers = [
                (path, self._make_getattr_reader(path))
                for path in attr_paths
            ]

    def _make_getattr_reader(self, path: str) -> Callable[[Any], Any]:
        parts = path.split(".")

        def _reader(root):
            obj = root
            for part in parts:
                obj = getattr(obj, part)
            if self.call_callables and callable(obj):
                try:
                    return obj()
                except TypeError:
                    return obj
            return obj

        return _reader

    def applies(self, ctx: InspectCtx) -> bool:
        return bool((ctx.session_ns or {}).get("session"))

    def probe(self, ctx: InspectCtx) -> ProbeResult:
        session = (ctx.session_ns or {}).get("session")
        diags: list[Diagnostic] = []
        for label, reader in self._readers:
            source = f"{self.source_prefix}:{label}"
            code = f"{self.code_prefix}.{label}"
            try:
                value = reader(session)
            except Exception as exc:
                diags.append(Diagnostic(
                    severity="warning",
                    source=source,
                    code="sim.sdk.attr_read_failed",
                    message=f"{label}: {type(exc).__name__}: {exc}",
                    extra={"label": label, "exception": type(exc).__name__},
                ))
                continue
            try:
                value_repr = repr(value)
            except Exception:
                value_repr = f"<unreprable {type(value).__name__}>"
            if len(value_repr) > 300:
                value_repr = value_repr[:297] + "..."
            diags.append(Diagnostic(
                severity="info",
                source=source,
                code=code,
                message=f"{label} = {value_repr}",
                extra={"label": label, "value_repr": value_repr},
            ))
        return ProbeResult(diagnostics=diags)


# Default exception-map rules for DomainExceptionMapProbe.
#
# Deliberately empty — solver-specific exception→domain-code mapping is a
# semantic judgement ("this Python exception means a Fluent RPC timeout")
# and that belongs to the agent / sim-skills layer, not the driver layer.
# The class remains available so a skill or agent can pass its own rules
# explicitly via DomainExceptionMapProbe(rules=[...]).
_EXC_MAP_RULES: list[dict] = []


class DomainExceptionMapProbe:
    """Channel #5 — Fluent-specific exception → domain code upgrader.

    Post-processor. Reads `ctx.extras["prior_diagnostics"]` (populated by
    `collect_diagnostics` between probe invocations) and, for each prior
    diag whose code matches a python.* pattern AND message matches a domain
    signature, emits a NEW diag with an upgraded `fluent.*` code. The
    original python.* diag is preserved (never mutated); agents see both
    and can prefer the domain code when available.
    """

    name = "domain-exception-map"

    def __init__(self, rules: list[dict] | None = None):
        self.rules = rules or _EXC_MAP_RULES
        self._compiled = [(re.compile(r["regex"]), r) for r in self.rules]

    def applies(self, ctx: InspectCtx) -> bool:
        priors = (ctx.extras or {}).get("prior_diagnostics") or []
        return bool(priors)

    def probe(self, ctx: InspectCtx) -> ProbeResult:
        priors = (ctx.extras or {}).get("prior_diagnostics") or []
        diags: list[Diagnostic] = []
        for prior in priors:
            # prior is a Diagnostic instance
            code_in = getattr(prior, "code", "") or ""
            msg_in = getattr(prior, "message", "") or ""
            for regex, rule in self._compiled:
                if rule["code_in"] and code_in not in rule["code_in"]:
                    continue
                m = regex.search(msg_in)
                if not m:
                    continue
                # Build the new message
                subs: dict[str, str] = {"match": m.group(0), "orig": msg_in}
                for i, g in enumerate(m.groups(), start=1):
                    subs[f"group{i}"] = g or ""
                try:
                    new_msg = rule["message_template"].format(**subs)
                except (KeyError, IndexError):
                    new_msg = rule["message_template"]
                # If the original had a helpful hint, preserve a ref to it
                if "most similar names are" in msg_in:
                    new_msg = new_msg + " | pyfluent hint: " + msg_in.split(
                        "most similar names are", 1)[1].strip()
                diags.append(Diagnostic(
                    severity="error",
                    source=getattr(prior, "source", "traceback"),
                    code=rule["upgrade_code"],
                    message=new_msg,
                    extra={
                        "upgraded_from": code_in,
                        "original_message": msg_in[:500],
                        "match": m.group(0),
                    },
                ))
                break
        return ProbeResult(diagnostics=diags)


_WORKDIR_ROLE_RULES: list[tuple[str, str]] = [
    # Fluent
    (".cas.h5", "case"),
    (".cas", "case"),
    (".dat.h5", "data"),
    (".dat", "data"),
    (".msh.h5", "mesh"),
    (".msh", "mesh"),
    (".trn", "transcript"),
    # COMSOL (Phase 2)
    (".mph", "comsol-model"),
    (".class", "jvm-class"),
    (".java", "java-source"),
    # Generic solver output
    (".out", "solver-log"),
    (".log", "solver-log"),
    (".png", "screenshot"),
    (".jpg", "image"),
    (".csv", "result-csv"),
]


def _pick_role(filename: str) -> str:
    low = filename.lower()
    for ext, role in _WORKDIR_ROLE_RULES:
        if low.endswith(ext):
            return role
    return "output"


class WorkdirDiffProbe:
    """Channel #9 — workdir before/after diff → Artifact list.

    Needs `ctx.workdir_before` (list of relative paths) populated by the
    driver/runner BEFORE exec. Probes the workdir after exec, emits one
    Artifact per newly-introduced file, with role inferred from extension.

    For persistent sessions, the 'before' list is the driver's
    responsibility (take a snapshot inside `run()`). For one-shot
    `execute_script`, Phase 2 will wire this in similarly.
    """

    name = "workdir-diff"

    def __init__(self, workdir_getter=None):
        self.workdir_getter = workdir_getter or (lambda ctx: ctx.workdir)

    def applies(self, ctx: InspectCtx) -> bool:
        return ctx.workdir_before is not None

    def probe(self, ctx: InspectCtx) -> ProbeResult:
        import time as _time  # noqa: PLC0415
        from pathlib import Path as _Path  # noqa: PLC0415

        workdir = _Path(self.workdir_getter(ctx))
        if not workdir.is_dir():
            return ProbeResult(diagnostics=[Diagnostic(
                severity="warning",
                source="workdir",
                code="sim.workdir.missing",
                message=f"workdir not accessible: {workdir}",
            )])
        before = set(ctx.workdir_before or [])
        arts: list[Artifact] = []
        try:
            now_files = [p for p in workdir.rglob("*") if p.is_file()]
        except Exception as exc:
            return ProbeResult(diagnostics=[Diagnostic(
                severity="warning", source="workdir",
                code="sim.workdir.scan_failed",
                message=f"{type(exc).__name__}: {exc}",
            )])
        for p in sorted(now_files):
            try:
                rel = str(p.relative_to(workdir)).replace("\\", "/")
            except Exception:
                rel = str(p)
            if rel in before:
                continue
            try:
                st = p.stat()
                size = st.st_size
                mtime = _time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", _time.gmtime(st.st_mtime))
            except Exception:
                size, mtime = None, None
            role = _pick_role(p.name)
            arts.append(Artifact(
                path=str(p), size=size, mtime=mtime, role=role,
            ))
        return ProbeResult(artifacts=arts)


def generic_probes() -> list:
    """任何 session driver 都可以免费使用的 5 个通用 probe。

    #1  ProcessMetaProbe      exit_code + wall_time
    #1+ RuntimeTimeoutProbe   hung-snippet 检测
    #3  StdoutJsonTailProbe   最后一行 JSON / _result fallback
    #3+ PythonTracebackProbe  结构化 traceback 解析
    #9  WorkdirDiffProbe      新增文件 → Artifacts

    需要 SDK 状态查询(#4)、日志扫描(#6/#7)、GUI 观察(#8a/#8b)的 driver
    在此基础上追加 solver 专用 probe。
    """
    return [
        ProcessMetaProbe(),
        RuntimeTimeoutProbe(),
        StdoutJsonTailProbe(),
        PythonTracebackProbe(),
        WorkdirDiffProbe(),
    ]


def _find_matching_windows(
    process_name_substrings: tuple[str, ...],
    target_pid: int | None = None,
) -> tuple[list[dict], int, list[str]]:
    """Shared helper: enumerate top-level windows for a target process.

    Two filtering modes:
      * ``target_pid`` is provided → return only windows whose owning process
        ID matches ``target_pid``. The substring list is ignored. Use this
        when the caller knows the exact process (e.g. a driver that just
        spawned the target solver) — it eliminates foreground races where
        another window with a generically-matching name happens to be top.
      * ``target_pid`` is ``None`` → fall back to substring matching against
        the owning process's name. This is the legacy default for callers
        that can only describe the target by class.

    Returns (matches, total_scanned, errors). Each match dict:
    ``{window, pid, proc_name, title, rect}``. ``rect`` is
    ``(left, top, right, bottom)`` int tuple, or ``None`` if rect-fetch
    failed. ``window`` is the raw pywinauto wrapper (use it for capture).

    Lazy-imports pywinauto + psutil so this module stays importable on Linux
    / in headless environments.
    """
    errors: list[str] = []
    try:
        from pywinauto import Desktop  # noqa: PLC0415
        import psutil  # noqa: PLC0415
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        return [], 0, errors

    try:
        windows = Desktop(backend="uia").windows()
    except Exception as exc:
        errors.append(f"Desktop enumeration: {type(exc).__name__}: {exc}")
        return [], 0, errors

    subs = tuple(s.lower() for s in process_name_substrings)
    matches: list[dict] = []
    total = 0
    for w in windows:
        total += 1
        try:
            pid = w.process_id()
            try:
                proc_name = psutil.Process(pid).name().lower()
            except Exception:
                proc_name = ""
            if target_pid is not None:
                if pid != target_pid:
                    continue
            else:
                if not any(sub in proc_name for sub in subs):
                    continue
            title = w.window_text() or ""
            try:
                r = w.rectangle()
                rect = (int(r.left), int(r.top), int(r.right), int(r.bottom))
            except Exception:
                rect = None
            matches.append({
                "window": w, "pid": pid, "proc_name": proc_name,
                "title": title, "rect": rect,
            })
        except Exception:
            continue
    return matches, total, errors


class GuiDialogProbe:
    """Channel #8a — GUI dialog enumeration via pywinauto (Windows only).

    Walks top-level windows belonging to the matched process(es) and emits
    one Diagnostic per window. If the title contains a dialog-hint keyword
    ("Error" / "Warning" / "Confirm" / ...) severity is escalated to
    "error" with `code=fluent.gui.dialog_detected`.

    Always emits a final `sim.inspect.gui_scan_summary` info diag so probe
    activity is observable even when nothing matches.

    `process_name_substrings` default matches Fluent's frontend: `cx####.exe`
    (Cortex for Fluent 2024 R1 = cx2410.exe, 2025 R1 = cx2510.exe, ...)
    plus `fluent` / `ansys` for completeness.

    Lazy-imports pywinauto so sim-cli stays importable on Linux.
    """

    name = "gui-dialog"
    # ── Severity-classification hints (Plan C, 2026-04-22) ─────────────────
    #
    # Boss's first-principles challenge: "agent 自己能读懂各种语言，为啥还要
    # probe 做文字匹配？" — correct. Maintaining a multilingual keyword table
    # is a hopeless arms race and delegates work the agent does cheaply with
    # its LLM. Plan C: we ONLY pre-escalate on **English strong-signal** words
    # that are de-facto programming convention for "hard failure" — these
    # appear in 95%+ of CAE dialogs regardless of the UI's primary language
    # (because developers write error messages in English first). Anything
    # else stays severity=info with the full title + screenshot — the agent's
    # LLM reads Chinese/French/Japanese/... natively and decides for itself.
    #
    # Rationale lives in sim-proj/inspect-probes-PLAN.md §二·六.
    _ERROR_SIGNAL_HINTS = (
        "error", "fatal", "abort", "failed", "crash", "exception",
    )
    _WARNING_SIGNAL_HINTS = ("warning",)

    def __init__(
        self,
        process_name_substrings: tuple[str, ...] = ("fluent", "ansys", "cx", "cortex"),
        code_prefix: str = "fluent.gui",
        target_pid: int | None = None,
    ):
        self.process_name_substrings = tuple(s.lower() for s in process_name_substrings)
        self.code_prefix = code_prefix
        self.target_pid = target_pid

    def applies(self, ctx: InspectCtx) -> bool:
        try:
            import pywinauto  # noqa: F401, PLC0415
            return True
        except Exception:
            return False

    def probe(self, ctx: InspectCtx) -> ProbeResult:
        matches, total, errors = _find_matching_windows(
            self.process_name_substrings, target_pid=self.target_pid,
        )
        diags: list[Diagnostic] = []
        if errors:
            for msg in errors:
                diags.append(Diagnostic(
                    severity="warning",
                    message=msg,
                    source="gui:dialog",
                    code="sim.inspect.gui_enum_failed",
                ))
            return ProbeResult(diagnostics=diags)

        for m in matches:
            proc_name, pid, title = m["proc_name"], m["pid"], m["title"]
            if not title.strip():
                diags.append(Diagnostic(
                    severity="info",
                    message=f"(untitled window on {proc_name}, pid={pid})",
                    source=f"gui:dialog:{proc_name}",
                    code=f"{self.code_prefix}.window_observed_untitled",
                    extra={"pid": pid, "process": proc_name, "rect": m["rect"]},
                ))
                continue
            low = title.lower()
            if any(h in low for h in self._ERROR_SIGNAL_HINTS):
                severity = "error"
                code = f"{self.code_prefix}.dialog_with_error_signal"
            elif any(h in low for h in self._WARNING_SIGNAL_HINTS):
                severity = "warning"
                code = f"{self.code_prefix}.dialog_with_warning_signal"
            else:
                # Plan C: every other observed window is neutral info.
                # Agent reads the title (+ any paired screenshot artifact
                # via #8b) and decides with its LLM whether this is a
                # blocker. Probe intentionally does NOT guess based on
                # localized keywords — that's the agent's job.
                severity = "info"
                code = f"{self.code_prefix}.window_observed"
            diags.append(Diagnostic(
                severity=severity,
                message=title[:300],
                source=f"gui:dialog:{proc_name}",
                code=code,
                extra={"pid": pid, "process": proc_name, "title": title,
                       "rect": m["rect"]},
            ))
        matched_procs = sorted({m["proc_name"] for m in matches})
        diags.append(Diagnostic(
            severity="info",
            message=(f"scanned {total} top-level windows; matched {len(matches)} "
                     f"on processes: {matched_procs or 'none'}"),
            source="gui:dialog",
            code="sim.inspect.gui_scan_summary",
            extra={"total_windows": total,
                   "matched_processes": matched_procs,
                   "match_count": len(matches)},
        ))
        return ProbeResult(diagnostics=diags)


class ScreenshotProbe:
    """Channel #8b — per-window screenshot capture via PIL.ImageGrab bbox.

    IMPORTANT: this probe captures ONLY the bounding box of each matched
    target window, NOT the whole desktop. If no matching window is found,
    emits a single warning diag and nothing else — we never fall back to
    full-screen capture (that creates noisy / PII-risky artifacts).

    Two ways to identify the target:
      * ``target_pid`` (preferred when known): bind to the exact process
        the caller spawned. Eliminates foreground races where another
        window whose process name happens to substring-match the legacy
        list wins z-order at probe time.
      * ``process_name_substrings`` (default): match any process whose
        name contains one of the given substrings. Used when the caller
        can only describe the target by class.

    Every matched window produces:
      - one Artifact  (role="screenshot", path=<png>)
      - one info Diag (source=gui:screenshot, code=sim.screenshot.captured)

    PNGs land in `ctx.workdir/screenshots/<prefix>_<pid>_<ts>.png`.
    """

    name = "screenshot"

    def __init__(
        self,
        filename_prefix: str = "shot",
        process_name_substrings: tuple[str, ...] = ("fluent", "ansys", "cx", "cortex"),
        target_pid: int | None = None,
    ):
        self.filename_prefix = filename_prefix
        self.process_name_substrings = tuple(s.lower() for s in process_name_substrings)
        self.target_pid = target_pid

    def applies(self, ctx: InspectCtx) -> bool:
        try:
            from PIL import ImageGrab  # noqa: F401, PLC0415
            import pywinauto  # noqa: F401, PLC0415
            return True
        except Exception:
            return False

    def probe(self, ctx: InspectCtx) -> ProbeResult:
        import time as _time  # noqa: PLC0415
        from pathlib import Path as _Path  # noqa: PLC0415

        try:
            from PIL import ImageGrab  # noqa: PLC0415
        except Exception as exc:
            return ProbeResult(diagnostics=[Diagnostic(
                severity="warning", source="gui:screenshot",
                code="sim.inspect.screenshot_unavailable",
                message=f"PIL.ImageGrab unavailable: {exc}",
            )])

        matches, _, errors = _find_matching_windows(
            self.process_name_substrings, target_pid=self.target_pid,
        )
        if errors:
            return ProbeResult(diagnostics=[Diagnostic(
                severity="warning", source="gui:screenshot",
                code="sim.inspect.screenshot_enum_failed",
                message="; ".join(errors),
            )])

        if not matches:
            target_desc = (
                f"pid={self.target_pid}" if self.target_pid is not None
                else f"{self.process_name_substrings}"
            )
            return ProbeResult(diagnostics=[Diagnostic(
                severity="info", source="gui:screenshot",
                code="sim.screenshot.no_window",
                message=(f"no window matched {target_desc}; "
                         f"no screenshot taken (full-screen fallback disabled)"),
            )])

        try:
            shots_dir = _Path(ctx.workdir) / "screenshots"
            shots_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return ProbeResult(diagnostics=[Diagnostic(
                severity="warning", source="gui:screenshot",
                code="sim.inspect.screenshot_workdir_failed",
                message=f"{type(exc).__name__}: {exc}",
            )])

        diags: list[Diagnostic] = []
        arts: list[Artifact] = []
        ts = int(_time.time() * 1000)
        for m in matches:
            rect = m["rect"]
            pid = m["pid"]
            title = m["title"] or "(untitled)"
            if rect is None or rect[2] <= rect[0] or rect[3] <= rect[1]:
                diags.append(Diagnostic(
                    severity="warning", source="gui:screenshot",
                    code="sim.inspect.screenshot_bad_rect",
                    message=f"skipped pid={pid} ({m['proc_name']}): invalid rect {rect}",
                    extra={"pid": pid, "process": m["proc_name"], "rect": rect},
                ))
                continue
            # Windows places minimized windows far offscreen (~(-32000,-32000)).
            # Capturing would produce a black PNG — skip with an info diag so
            # the agent / human understands why there's no screenshot.
            if rect[0] < -10000 or rect[1] < -10000:
                diags.append(Diagnostic(
                    severity="info", source="gui:screenshot",
                    code="sim.screenshot.window_minimized",
                    message=(f"skipped pid={pid} ({m['proc_name']}): "
                             f"window is minimized (rect={rect})"),
                    extra={"pid": pid, "process": m["proc_name"], "rect": rect,
                           "title": title},
                ))
                continue
            out_path = shots_dir / f"{self.filename_prefix}_{pid}_{ts}.png"
            try:
                img = ImageGrab.grab(bbox=rect, all_screens=True)
                img.save(out_path, "PNG")
            except Exception as exc:
                diags.append(Diagnostic(
                    severity="warning", source="gui:screenshot",
                    code="sim.inspect.screenshot_failed",
                    message=f"{type(exc).__name__}: {exc}",
                    extra={"pid": pid, "rect": rect},
                ))
                continue
            try:
                st = out_path.stat()
                arts.append(Artifact(
                    path=str(out_path), size=st.st_size,
                    mtime=_time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                         _time.gmtime(st.st_mtime)),
                    role="screenshot",
                ))
            except Exception:
                arts.append(Artifact(path=str(out_path), role="screenshot"))
            diags.append(Diagnostic(
                severity="info", source="gui:screenshot",
                code="sim.screenshot.captured",
                message=(f"captured {m['proc_name']} pid={pid} "
                         f"{(rect[2]-rect[0])}x{(rect[3]-rect[1])} → "
                         f"{out_path.name}"),
                extra={"path": str(out_path), "pid": pid,
                       "process": m["proc_name"], "rect": rect,
                       "title": title},
            ))
        return ProbeResult(diagnostics=diags, artifacts=arts)
