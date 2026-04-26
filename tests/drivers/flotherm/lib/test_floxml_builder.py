"""FloXML builder tests — verify the emitted XML is well-formed and lint-clean."""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from sim.drivers.flotherm.lib.floxml import lint_floxml
from sim.drivers.flotherm.lib.floxml_builder import (
    Ambient,
    Cuboid,
    FixedTemperature,
    Fluid,
    HeatSource,
    IsotropicMaterial,
    Project,
    SolutionDomain,
)


def _minimal_project(name: str = "test") -> Project:
    p = Project(name=name)
    p.materials.append(IsotropicMaterial("Silicon", 148, 2330, 700))
    p.thermals.append(FixedTemperature("HotFace", 60.0))
    p.cuboids.append(Cuboid(
        "HotPlate",
        position=(0.0, 0.0, 0.0),
        size=(5e-3, 1e-3, 1.1e-2),
        material="Silicon",
        thermal="HotFace",
    ))
    p.solution_domain = SolutionDomain(
        position=(-1e-3, -1e-3, -1e-3),
        size=(7e-3, 5e-3, 1.3e-2),
    )
    return p


def test_minimal_project_emits_valid_xml():
    p = _minimal_project()
    xml = p.to_xml()
    root = ET.fromstring(xml)
    assert root.tag == "xml_case"
    assert root.find("name").text == "test"


def test_minimal_project_passes_lint(tmp_path: Path):
    p = _minimal_project()
    out = tmp_path / "case.xml"
    out.write_text(p.to_xml(), encoding="utf-8")
    result = lint_floxml(out)
    assert result.ok, [d.message for d in result.diagnostics]


def test_required_top_level_sections_present():
    p = _minimal_project()
    xml = p.to_xml()
    root = ET.fromstring(xml)
    for tag in ("model", "solve", "grid", "attributes", "geometry",
                "solution_domain"):
        assert root.find(tag) is not None, f"missing <{tag}>"


def test_to_xml_requires_solution_domain():
    p = Project(name="t")
    p.cuboids.append(Cuboid("c", (0, 0, 0), (1e-3, 1e-3, 1e-3)))
    with pytest.raises(ValueError, match="solution_domain"):
        p.to_xml()


def test_to_xml_requires_at_least_one_cuboid():
    p = Project(name="t")
    p.solution_domain = SolutionDomain(position=(0, 0, 0), size=(1, 1, 1))
    with pytest.raises(ValueError, match="cuboid"):
        p.to_xml()


def test_isotropic_material_emitted():
    p = _minimal_project()
    root = ET.fromstring(p.to_xml())
    mat = root.find("./attributes/materials/isotropic_material_att")
    assert mat is not None
    assert mat.find("name").text == "Silicon"
    assert mat.find("conductivity").text == "148"


def test_fixed_temperature_thermal_emitted():
    p = _minimal_project()
    root = ET.fromstring(p.to_xml())
    therm = root.find("./attributes/thermals/thermal_att")
    assert therm is not None
    assert therm.find("name").text == "HotFace"
    assert therm.find("thermal_model").text == "fixed_temperature"
    assert therm.find("fixed_temperature").text == "60.0"


def test_cuboid_position_and_size():
    p = _minimal_project()
    root = ET.fromstring(p.to_xml())
    cub = root.find("./geometry/cuboid")
    assert cub is not None
    assert cub.find("name").text == "HotPlate"
    pos = cub.find("position")
    assert pos.find("x").text == "0.0"
    sz = cub.find("size")
    assert sz.find("x").text == "0.005"


def test_cuboid_references_material_and_thermal():
    p = _minimal_project()
    root = ET.fromstring(p.to_xml())
    cub = root.find("./geometry/cuboid")
    assert cub.find("material").text == "Silicon"
    assert cub.find("thermal").text == "HotFace"


def test_heat_source_emitted_only_when_present():
    p = _minimal_project()
    root_no_src = ET.fromstring(p.to_xml())
    assert root_no_src.find("./attributes/sources") is None

    p.sources.append(HeatSource("Source_3W", power_w=3.0))
    p.cuboids[0].source = "Source_3W"
    root = ET.fromstring(p.to_xml())
    src = root.find("./attributes/sources/source_att")
    assert src is not None
    assert src.find("name").text == "Source_3W"
    opt = src.find("./source_options/option")
    assert opt.find("power").text == "3.0"


def test_solution_domain_default_ambient_faces():
    p = _minimal_project()
    root = ET.fromstring(p.to_xml())
    sd = root.find("solution_domain")
    for face in ("x_low_ambient", "x_high_ambient", "y_low_ambient",
                 "y_high_ambient", "z_low_ambient", "z_high_ambient"):
        elem = sd.find(face)
        assert elem is not None
        assert elem.text == "Ambient"


def test_solution_domain_symmetry_face_uses_boundary_tag():
    p = _minimal_project()
    p.solution_domain.y_low = "symmetry"
    root = ET.fromstring(p.to_xml())
    sd = root.find("solution_domain")
    # symmetry face uses *_boundary not *_ambient
    assert sd.find("y_low_boundary") is not None
    assert sd.find("y_low_boundary").text == "symmetry"
    assert sd.find("y_low_ambient") is None


def test_default_ambient_and_fluid_added():
    p = Project(name="t")
    assert any(a.name == "Ambient" for a in p.ambients)
    assert any(f.name == "Air" for f in p.fluids)


def test_fluid_constant_property_emission():
    p = _minimal_project()
    root = ET.fromstring(p.to_xml())
    fluid = root.find("./attributes/fluids/fluid_att")
    assert fluid.find("conductivity_type").text == "constant"
    assert fluid.find("density_type").text == "constant"


def test_grid_uses_configured_min_max():
    p = _minimal_project()
    p.grid_max_size = 1e-3
    p.grid_min_size = 1e-4
    root = ET.fromstring(p.to_xml())
    x_grid = root.find("./grid/system_grid/x_grid")
    assert x_grid.find("max_size").text == "0.001"
    assert x_grid.find("min_size").text == "0.0001"


def test_full_round_trip_re_lints_clean(tmp_path: Path):
    """Build, write, parse, re-write — should remain lint-clean."""
    p = _minimal_project("round_trip")
    p.sources.append(HeatSource("Src", power_w=2.5))
    p.cuboids[0].source = "Src"
    out = tmp_path / "case.xml"
    out.write_text(p.to_xml(), encoding="utf-8")
    assert lint_floxml(out).ok

    # Re-parse and re-serialize — must still be well-formed
    root = ET.fromstring(out.read_text())
    out2 = tmp_path / "case2.xml"
    out2.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    assert lint_floxml(out2).ok
