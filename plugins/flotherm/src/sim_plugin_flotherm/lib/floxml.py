"""FloXML authoring format — `<xml_case>` / `<sm_xml_case>` lint."""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from sim.driver import Diagnostic, LintResult

_FLOXML_ROOTS = ("xml_case", "sm_xml_case")


def lint_floxml(script: Path) -> LintResult:
    """Validate a Flotherm FloXML authoring file.

    FloXML is the vendor-blessed model-exchange format. Unlike FloSCRIPT,
    sim-skills does not yet ship a public XSD for FloXML, so this lint is
    structural-only: well-formed XML + a recognized root tag. When/if an
    XSD becomes available it can hook in via the same path as FloSCRIPT.
    """
    diagnostics: list[Diagnostic] = []
    try:
        text = script.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return LintResult(ok=False, diagnostics=[
            Diagnostic(level="error", message=f"Cannot read file: {e}")])
    if not text.strip():
        return LintResult(ok=False, diagnostics=[
            Diagnostic(level="error", message="FloXML file is empty")])
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as e:
        return LintResult(ok=False, diagnostics=[
            Diagnostic(level="error", message=f"XML parse error: {e}")])
    if root.tag not in _FLOXML_ROOTS:
        return LintResult(ok=False, diagnostics=[Diagnostic(
            level="error",
            message=f"Expected FloXML root <xml_case> or <sm_xml_case>, got <{root.tag}>.")])
    return LintResult(ok=True, diagnostics=diagnostics)
