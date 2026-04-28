"""Conformance checks every sim plugin's CI should run.

This file is the single source of truth for "does this driver class
implement DriverProtocol correctly enough for sim-cli to use it?". It
catches mistakes that the structural ``isinstance(d, DriverProtocol)``
runtime check misses — things like methods that exist but have the wrong
return type, missing attributes, or a ``detect_installed`` that imports
the SDK at attribute-access time.

Plugin authors call :func:`assert_protocol_conformance` from a single test
function and get the whole battery for free. The check returns structured
failures via :class:`ConformanceFailure` so the test runner shows useful
diagnostics rather than ``AssertionError``.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sim.driver import (
    ConnectionInfo,
    DriverProtocol,
    LintResult,
    RunResult,
    SolverInstall,
)


@dataclass
class ConformanceFailure(AssertionError):
    """Raised when a driver class fails conformance.

    Subclassing AssertionError so pytest renders it nicely without the
    test author needing to wrap calls in ``pytest.raises``. NOT frozen:
    Python's exception machinery mutates ``__traceback__`` on the way up.
    """
    label: str
    message: str

    def __str__(self) -> str:  # pragma: no cover — formatting only
        return f"[{self.label}] {self.message}"


# Required methods on the structural protocol. We check these by name AND
# by inspecting the signature (parameter count, names) so authors who alias
# parameters get a helpful error.
REQUIRED_METHODS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("detect", ("script",)),
    ("lint", ("script",)),
    ("connect", ()),
    ("parse_output", ("stdout",)),
    ("run_file", ("script",)),
    ("detect_installed", ()),
)

# Optional methods — only checked when the driver advertises supports_session.
OPTIONAL_SESSION_METHODS: tuple[str, ...] = ("launch", "run", "disconnect")


def _instantiate(driver_class: type) -> Any:
    """Instantiate the driver class, surfacing the real failure cleanly."""
    try:
        return driver_class()
    except TypeError as e:
        raise ConformanceFailure(
            "instantiation",
            f"{driver_class.__name__}() requires arguments — drivers must "
            f"be no-arg constructible. Original: {e}",
        ) from e
    except Exception as e:  # noqa: BLE001 — surface the original failure verbatim
        raise ConformanceFailure(
            "instantiation",
            f"{driver_class.__name__}() raised at construction: {type(e).__name__}: {e}",
        ) from e


def check_driver(driver_class: type) -> list[ConformanceFailure]:
    """Run every conformance check and return all failures (does not raise).

    Use this when you want to produce a report; use
    :func:`assert_protocol_conformance` when you want a single
    pass/fail in a test.
    """
    failures: list[ConformanceFailure] = []

    # 1. The class can be instantiated without arguments.
    try:
        instance = _instantiate(driver_class)
    except ConformanceFailure as f:
        return [f]

    # 2. ``name`` property exists and is a non-empty string.
    name = getattr(instance, "name", None)
    if not isinstance(name, str) or not name:
        failures.append(ConformanceFailure(
            "name",
            f"driver.name must be a non-empty string, got {name!r}",
        ))

    # 3. Required methods exist with sensible signatures.
    for method_name, expected_params in REQUIRED_METHODS:
        method = getattr(instance, method_name, None)
        if method is None or not callable(method):
            failures.append(ConformanceFailure(
                f"method:{method_name}",
                f"{method_name!r} is missing or not callable",
            ))
            continue
        try:
            sig = inspect.signature(method)
        except (TypeError, ValueError):
            continue  # builtin / C extension methods can't be introspected
        param_names = [p.name for p in sig.parameters.values()
                       if p.kind not in (inspect.Parameter.VAR_KEYWORD,
                                         inspect.Parameter.VAR_POSITIONAL)]
        for expected in expected_params:
            if expected not in param_names:
                failures.append(ConformanceFailure(
                    f"method:{method_name}",
                    f"{method_name}() expected parameter {expected!r}, "
                    f"got params: {param_names}",
                ))

    # 4. ``detect_installed`` returns an iterable of SolverInstall.
    try:
        installs = list(instance.detect_installed())
    except Exception as e:  # noqa: BLE001 — must be safe to call
        failures.append(ConformanceFailure(
            "detect_installed",
            f"raised {type(e).__name__}: {e}. Must be safe to call when "
            f"nothing is installed.",
        ))
    else:
        for inst in installs:
            if not isinstance(inst, SolverInstall):
                failures.append(ConformanceFailure(
                    "detect_installed",
                    f"returned {type(inst).__name__}; must be SolverInstall",
                ))
                break

    # 5. ``connect`` returns a ConnectionInfo (or close-enough duck).
    try:
        ci = instance.connect()
    except Exception as e:  # noqa: BLE001 — driver may legitimately error here
        # We don't fail conformance — connect() is allowed to fail when the
        # solver isn't installed. But the type when it does succeed must be
        # ConnectionInfo. We can only skip in this case.
        ci = None
        if not isinstance(e, (FileNotFoundError, RuntimeError, OSError, ImportError)):
            failures.append(ConformanceFailure(
                "connect",
                f"raised {type(e).__name__}: {e!s}. Failures should produce "
                f"ConnectionInfo(status='not_installed'/'error') instead.",
            ))
    if ci is not None and not isinstance(ci, ConnectionInfo):
        failures.append(ConformanceFailure(
            "connect",
            f"returned {type(ci).__name__}; must be ConnectionInfo",
        ))

    # 6. ``parse_output`` returns a dict.
    try:
        parsed = instance.parse_output("")
    except Exception as e:  # noqa: BLE001
        failures.append(ConformanceFailure(
            "parse_output",
            f"raised on empty input: {type(e).__name__}: {e}. "
            f"Must accept any string and return a dict.",
        ))
    else:
        if not isinstance(parsed, dict):
            failures.append(ConformanceFailure(
                "parse_output",
                f"returned {type(parsed).__name__}; must be dict",
            ))

    # 7. ``lint`` returns a LintResult on a missing path (the driver may
    #    decline to lint missing files, but it must not crash).
    try:
        lr = instance.lint(Path("/nonexistent/script.tmp"))
    except Exception as e:  # noqa: BLE001
        failures.append(ConformanceFailure(
            "lint",
            f"raised on missing-file path: {type(e).__name__}: {e}. "
            f"Should return LintResult(ok=True, diagnostics=[]) or similar.",
        ))
    else:
        if not isinstance(lr, LintResult):
            failures.append(ConformanceFailure(
                "lint",
                f"returned {type(lr).__name__}; must be LintResult",
            ))

    # 8. Session lifecycle (only if advertised).
    supports_session = bool(getattr(instance, "supports_session", False))
    if supports_session:
        for method_name in OPTIONAL_SESSION_METHODS:
            method = getattr(instance, method_name, None)
            if method is None or not callable(method):
                failures.append(ConformanceFailure(
                    f"session:{method_name}",
                    f"supports_session=True but {method_name!r} is missing",
                ))

    # 9. Final structural protocol check.
    if not isinstance(instance, DriverProtocol):
        failures.append(ConformanceFailure(
            "protocol",
            f"{driver_class.__name__} instance does not match DriverProtocol "
            f"structurally. The previous failures usually explain why.",
        ))

    return failures


def assert_protocol_conformance(driver_class: type) -> None:
    """Test-suite friendly wrapper around :func:`check_driver`.

    Plugin authors call this from one pytest function::

        from sim.testing import assert_protocol_conformance
        from sim_plugin_<x> import <X>Driver

        def test_protocol():
            assert_protocol_conformance(<X>Driver)

    Raises ConformanceFailure (an AssertionError subclass) listing every
    failure, which pytest renders as one nicely-grouped failure.
    """
    failures = check_driver(driver_class)
    if not failures:
        return

    lines = [f"{len(failures)} conformance failure(s) in {driver_class.__name__}:"]
    for f in failures:
        lines.append(f"  [{f.label}] {f.message}")
    # Raise the first failure so the test framework's `__cause__` chain points
    # at one root, but include all in the message.
    raise ConformanceFailure(
        label=failures[0].label,
        message="\n".join(lines),
    )


def _ensure_dataclass_imports_for_consumers() -> None:
    """No-op: ensures RunResult is reachable for type-checkers reading this module.

    Plugin authors might also want to assert their driver returns RunResult
    from run_file when given a real script — that test is plugin-specific
    and we don't try to write it here.
    """
    _ = RunResult


__all__ = [
    "ConformanceFailure",
    "assert_protocol_conformance",
    "check_driver",
    "REQUIRED_METHODS",
    "OPTIONAL_SESSION_METHODS",
]
