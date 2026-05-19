"""FloSCRIPT XML — lint (XSD-validated when schema dir provided) and build."""
from __future__ import annotations

from pathlib import Path
from xml.dom import minidom
from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement, tostring

from sim.driver import Diagnostic, LintResult

_FLOSCRIPT_ROOT = "xml_log_file"
_SOLVE_COMMANDS = ("solve_all", "solve_scenario", "start")


def lint_floscript(
    script: Path,
    *,
    schema_dir: Path | None = None,
    require_solve: bool = True,
) -> LintResult:
    """Validate a FloSCRIPT XML file.

    Parameters
    ----------
    script : Path
        Path to the FloSCRIPT .xml file.
    schema_dir : Path, optional
        Directory containing FloSCRIPTSchema.xsd and its includes.
        When provided, full XSD validation is performed via lxml.
        When None, only basic structural checks are done.
    require_solve : bool
        When True (default), emit a warning if no solve/start command
        is found.  Set to False for model-building scripts that
        intentionally omit solve commands.
    """
    diagnostics: list[Diagnostic] = []
    try:
        text = script.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return LintResult(ok=False, diagnostics=[
            Diagnostic(level="error", message=f"Cannot read file: {e}")])
    if not text.strip():
        return LintResult(ok=False, diagnostics=[
            Diagnostic(level="error", message="Script is empty")])
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as e:
        return LintResult(ok=False, diagnostics=[
            Diagnostic(level="error", message=f"XML parse error: {e}")])
    if root.tag != _FLOSCRIPT_ROOT:
        diagnostics.append(Diagnostic(
            level="error",
            message=f"Expected root <xml_log_file>, got <{root.tag}>."))
        return LintResult(ok=False, diagnostics=diagnostics)

    if schema_dir is not None:
        xsd_diagnostics = _validate_xsd(text, schema_dir)
        if xsd_diagnostics:
            diagnostics.extend(xsd_diagnostics)
            has_errors = any(d.level == "error" for d in xsd_diagnostics)
            if has_errors:
                return LintResult(ok=False, diagnostics=diagnostics)

    if require_solve:
        has_solve = False
        for child in root:
            if child.tag in _SOLVE_COMMANDS:
                has_solve = True
                break
            if child.tag == "external_command":
                for gc in child:
                    if gc.tag in _SOLVE_COMMANDS:
                        has_solve = True
                        break
        if not has_solve:
            diagnostics.append(Diagnostic(
                level="warning",
                message="No solve/start command found — "
                        "script may configure but not run a simulation."))
    return LintResult(ok=True, diagnostics=diagnostics)


def _validate_xsd(xml_text: str, schema_dir: Path) -> list[Diagnostic]:
    """Run XSD validation and return diagnostics with line numbers."""
    from lxml import etree

    diagnostics: list[Diagnostic] = []
    schema_path = schema_dir / "FloSCRIPTSchema.xsd"
    if not schema_path.is_file():
        diagnostics.append(Diagnostic(
            level="warning",
            message=f"XSD schema not found at {schema_path} — "
                    "skipping schema validation."))
        return diagnostics
    try:
        schema_doc = etree.parse(str(schema_path))
        schema = etree.XMLSchema(schema_doc)
    except etree.XMLSchemaParseError as e:
        diagnostics.append(Diagnostic(
            level="warning",
            message=f"Failed to load XSD schema: {e} — "
                    "skipping schema validation."))
        return diagnostics
    try:
        doc = etree.fromstring(xml_text.encode("utf-8"))
    except etree.XMLSyntaxError as e:
        diagnostics.append(Diagnostic(
            level="error", message=f"lxml XML parse error: {e}"))
        return diagnostics

    if not schema.validate(doc):
        for error in schema.error_log:
            diagnostics.append(Diagnostic(
                level="error",
                message=f"Line {error.line}: {error.message}"))
    return diagnostics


def _pretty_xml(root: Element) -> str:
    raw = tostring(root, encoding="unicode")
    dom = minidom.parseString(raw)
    return dom.toprettyxml(indent="    ", encoding=None)


def build_solve_and_save(project_name: str) -> str:
    """Build FloSCRIPT: unlock → load → solve → save (Drawing Board syntax)."""
    root = Element("xml_log_file", version="1.0")
    SubElement(root, "project_unlock", project_name=project_name)
    SubElement(root, "project_load", project_name=project_name)
    SubElement(root, "start", start_type="solver")
    return _pretty_xml(root)


def build_project_save() -> str:
    """Build FloSCRIPT to save the current active project."""
    root = Element("xml_log_file", version="1.0")
    SubElement(root, "project_save")
    return _pretty_xml(root)


def build_project_save_as(
    project_name: str,
    *,
    project_title: str | None = None,
    project_notes: str | None = None,
    solution_directory: str | None = None,
    project_category: str | None = None,
    save_with_results: bool | None = None,
) -> str:
    """Build FloSCRIPT to save the active project under a stable name."""
    attrs = {"project_name": project_name}
    if project_title is not None:
        attrs["project_title"] = project_title
    if project_notes is not None:
        attrs["project_notes"] = project_notes
    if solution_directory is not None:
        attrs["solution_directory"] = solution_directory
    if project_category is not None:
        attrs["project_category"] = project_category
    if save_with_results is not None:
        attrs["save_with_results"] = "true" if save_with_results else "false"
    root = Element("xml_log_file", version="1.0")
    SubElement(root, "project_save_as", **attrs)
    return _pretty_xml(root)


def build_start_record_script(file_name: str) -> str:
    """Build FloSCRIPT to start GUI FloSCRIPT recording to ``file_name``."""
    root = Element("xml_log_file", version="1.0")
    SubElement(root, "start_record_script", file_name=file_name)
    return _pretty_xml(root)


def build_stop_record_script() -> str:
    """Build FloSCRIPT to stop GUI FloSCRIPT recording."""
    root = Element("xml_log_file", version="1.0")
    SubElement(root, "stop_record_script")
    return _pretty_xml(root)


def build_solve_scenario(project_name: str, scenario_id: str) -> str:
    """Build FloSCRIPT to solve a specific scenario."""
    root = Element("xml_log_file", version="1.0")
    SubElement(root, "project_unlock", project_name=project_name)
    SubElement(root, "project_load", project_name=project_name)
    ext = SubElement(root, "external_command", process="CommandCentre")
    solve = SubElement(ext, "solve_scenario")
    SubElement(solve, "scenario_id", scenario_id=scenario_id)
    return _pretty_xml(root)


def build_custom(commands: list[dict]) -> str:
    """Build FloSCRIPT from a list of command specs."""
    root = Element("xml_log_file", version="1.0")
    for cmd in commands:
        _add_command(root, cmd)
    return _pretty_xml(root)


def _add_command(parent: Element, spec: dict) -> None:
    process = spec.get("process")
    if process:
        wrapper = SubElement(parent, "external_command", process=process)
        inner_spec = {k: v for k, v in spec.items() if k != "process"}
        _add_command(wrapper, inner_spec)
        return
    attrs = spec.get("attrs", {})
    elem = SubElement(parent, spec["command"], **attrs)
    for child in spec.get("children", []):
        _add_command(elem, child)
