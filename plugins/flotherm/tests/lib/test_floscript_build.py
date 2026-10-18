"""FloSCRIPT XML generation — verify it produces well-formed, expected XML."""
from __future__ import annotations

from xml.etree import ElementTree

from sim_plugin_flotherm.lib.floscript import (
    build_custom,
    build_project_save,
    build_project_save_as,
    build_solve_and_save,
    build_solve_scenario,
    build_start_record_script,
    build_stop_record_script,
)


def test_build_solve_and_save_produces_valid_xml():
    xml = build_solve_and_save("MyProject")
    root = ElementTree.fromstring(xml)
    assert root.tag == "xml_log_file"
    tags = [c.tag for c in root]
    assert "project_unlock" in tags
    assert "project_load" in tags
    assert "start" in tags


def test_build_solve_scenario_wraps_in_external_command():
    xml = build_solve_scenario("MyProject", "S1")
    root = ElementTree.fromstring(xml)
    ext = root.find("external_command")
    assert ext is not None
    assert ext.attrib.get("process") == "CommandCentre"
    solve = ext.find("solve_scenario")
    assert solve is not None
    sid = solve.find("scenario_id")
    assert sid is not None
    assert sid.attrib.get("scenario_id") == "S1"


def test_build_project_save_produces_project_save_command():
    xml = build_project_save()
    root = ElementTree.fromstring(xml)
    assert root.find("project_save") is not None


def test_build_project_save_as_sets_project_name_and_title():
    xml = build_project_save_as("NamedProject", project_title="Named title")
    root = ElementTree.fromstring(xml)
    cmd = root.find("project_save_as")
    assert cmd is not None
    assert cmd.attrib["project_name"] == "NamedProject"
    assert cmd.attrib["project_title"] == "Named title"


def test_build_record_controls_use_schema_attribute_names():
    start_xml = build_start_record_script(r"C:\tmp\record.xml")
    start_root = ElementTree.fromstring(start_xml)
    start = start_root.find("start_record_script")
    assert start is not None
    assert start.attrib["file_name"] == r"C:\tmp\record.xml"

    stop_xml = build_stop_record_script()
    stop_root = ElementTree.fromstring(stop_xml)
    assert stop_root.find("stop_record_script") is not None


def test_build_custom_handles_nested_children():
    xml = build_custom([
        {
            "command": "csv_export_attribute",
            "attrs": {"filename": "out.csv"},
            "children": [
                {"command": "attribute_name", "attrs": {}},
            ],
        },
    ])
    root = ElementTree.fromstring(xml)
    cmd = root.find("csv_export_attribute")
    assert cmd is not None
    assert cmd.attrib.get("filename") == "out.csv"
    assert cmd.find("attribute_name") is not None
