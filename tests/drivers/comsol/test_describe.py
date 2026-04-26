"""Unit tests for `sim.drivers.comsol.lib.describe`.

These tests build a hand-rolled stand-in for a COMSOL Java model — a
plain Python object that responds to the read-side API observed during
the win1 probe (see PR description). Acceptance against a real COMSOL
session is covered by `tests/inspect/probe_describe_physics.py`.

The fixture data mirrors the real `block_with_hole` solve verbatim
where it matters (feature tags, types, T0 values, selection entities,
the full set of auto-created defaults). That way the formatter is
exercised against real-shaped data without needing JPype on the test
host.
"""
from __future__ import annotations

import pytest

from sim.drivers.comsol.lib import describe, format_text
from sim.drivers.comsol.lib.describe import _format_feature_line


# ----------------------------------------------------------------------
# Stand-in for the COMSOL Java model — duck-typed against the read API.
# ----------------------------------------------------------------------


class _Selection:
    def __init__(self, entities: list[int], named: str = ""):
        self._entities = entities
        self._named = named

    def entities(self):
        return list(self._entities)

    def named(self):
        return self._named


class _Feature:
    def __init__(
        self,
        tag: str,
        ftype: str,
        name: str,
        entities: list[int],
        properties: dict[str, str] | None = None,
        named: str = "",
    ):
        self.tag = tag
        self._ftype = ftype
        self._name = name
        self._sel = _Selection(entities, named=named)
        self._props = dict(properties or {})

    def getType(self):
        return self._ftype

    def name(self):
        return self._name

    def selection(self):
        return self._sel

    def properties(self):
        return list(self._props.keys())

    def getString(self, name: str):
        if name not in self._props:
            raise KeyError(name)
        return self._props[name]


class _PhysicsFeatureSet:
    def __init__(self, features: list[_Feature]):
        self._features = {f.tag: f for f in features}

    def tags(self):
        return list(self._features.keys())

    def __call__(self, tag: str | None = None):
        # phy.feature() with no args → set; phy.feature(tag) → feature
        if tag is None:
            return self
        return self._features[tag]


class _Physics:
    def __init__(self, tag: str, ptype: str, name: str, features: list[_Feature]):
        self.tag = tag
        self._ptype = ptype
        self._name = name
        self._fset = _PhysicsFeatureSet(features)

    def getType(self):
        return self._ptype

    def name(self):
        return self._name

    def feature(self, tag: str | None = None):
        if tag is None:
            return self._fset
        return self._fset(tag)


class _PhysicsSet:
    def __init__(self, interfaces: list[_Physics]):
        self._physics = {p.tag: p for p in interfaces}

    def tags(self):
        return list(self._physics.keys())

    def __call__(self, tag: str | None = None):
        if tag is None:
            return self
        return self._physics[tag]


class _Model:
    """Quacks like the live COMSOL Java model for `describe()` purposes."""

    def __init__(self, interfaces: list[_Physics]):
        self._pset = _PhysicsSet(interfaces)

    def physics(self, tag: str | None = None):
        if tag is None:
            return self._pset
        return self._pset(tag)


# ----------------------------------------------------------------------
# Block-with-hole physics tree — verbatim from the win1 probe.
# ----------------------------------------------------------------------


def _block_with_hole_model() -> _Model:
    """Heat Transfer in Solids with 3 user BCs and 8 default features.

    Entity ids and T0 values match the win1 probe output exactly so the
    formatter is exercised against real shapes.
    """
    ht = _Physics(
        tag="ht",
        ptype="HeatTransfer",
        name="Heat Transfer in Solids",
        features=[
            _Feature("solid1", "SolidHeatTransferModel", "Solid 1", [1],
                     properties={"Solid_material": "dommat", "k": "0",
                                 "rho_mat": "from_mat"}),
            _Feature("init1", "init", "Initial Values 1", [1],
                     properties={"Tinit": "293.15[K]", "Tinit_src": "userdef"}),
            _Feature("ins1", "ThermalInsulation", "Thermal Insulation 1",
                     [2, 3, 4, 5, 10]),
            _Feature("idi1", "IsothermalDomainInterface",
                     "Isothermal Domain Interface 1", []),
            _Feature("ltneb1", "LocalThermalNonequilibriumBoundary",
                     "Local Thermal Nonequilibrium Boundary 1", []),
            _Feature("os1", "OpaqueSurface", "Opaque Surface 1", []),
            _Feature("cib1", "ContinuityOnInteriorBoundary",
                     "Continuity on Interior Boundary 1", []),
            _Feature("dcont1", "Continuity", "Continuity 1", []),
            _Feature("temp1", "TemperatureBoundary", "Temperature 1", [1],
                     properties={"T0": "373[K]", "T0_src": "userdef"}),
            _Feature("temp2", "TemperatureBoundary", "Temperature 2", [6],
                     properties={"T0": "293[K]", "T0_src": "userdef"}),
            _Feature("hf1", "HeatFluxBoundary", "Heat Flux 1", [7, 8, 9],
                     properties={"HeatFluxType": "ConvectiveHeatFlux",
                                 "h": "50[W/(m^2*K)]", "Text": "293[K]",
                                 "q0_input": "0"}),
        ],
    )
    return _Model([ht])


# ----------------------------------------------------------------------
# describe() shape
# ----------------------------------------------------------------------


class TestDescribePhysics:
    def test_returns_one_interface_for_block_with_hole(self):
        summary = describe(_block_with_hole_model())
        assert summary["what"] == "physics"
        assert len(summary["physics"]) == 1

    def test_interface_top_level_fields(self):
        ifc = describe(_block_with_hole_model())["physics"][0]
        assert ifc["tag"] == "ht"
        assert ifc["type"] == "HeatTransfer"
        assert ifc["name"] == "Heat Transfer in Solids"

    def test_walks_all_features_user_and_default(self):
        ifc = describe(_block_with_hole_model())["physics"][0]
        tags = [f["tag"] for f in ifc["features"]]
        # 3 user-created BCs + 8 auto-created defaults
        assert tags == [
            "solid1", "init1", "ins1", "idi1", "ltneb1", "os1", "cib1",
            "dcont1", "temp1", "temp2", "hf1",
        ]

    def test_temperature_boundary_carries_T0(self):
        ifc = describe(_block_with_hole_model())["physics"][0]
        temp1 = next(f for f in ifc["features"] if f["tag"] == "temp1")
        assert temp1["type"] == "TemperatureBoundary"
        assert temp1["selection_entities"] == [1]
        assert temp1["properties"]["T0"] == "373[K]"

    def test_heat_flux_boundary_carries_h(self):
        ifc = describe(_block_with_hole_model())["physics"][0]
        hf = next(f for f in ifc["features"] if f["tag"] == "hf1")
        assert hf["type"] == "HeatFluxBoundary"
        assert hf["selection_entities"] == [7, 8, 9]
        assert hf["properties"]["h"] == "50[W/(m^2*K)]"

    def test_default_features_have_empty_or_present_selections(self):
        """Auto-created features may have empty selection lists; no exceptions."""
        ifc = describe(_block_with_hole_model())["physics"][0]
        for tag in ("idi1", "ltneb1", "os1", "cib1", "dcont1"):
            f = next(x for x in ifc["features"] if x["tag"] == tag)
            assert f["selection_entities"] == []

    def test_named_selection_default_is_none(self):
        ifc = describe(_block_with_hole_model())["physics"][0]
        for f in ifc["features"]:
            assert f["selection_named"] is None

    def test_unsupported_what_raises(self):
        with pytest.raises(ValueError, match="only what='physics' is implemented"):
            describe(_block_with_hole_model(), what="materials")


# ----------------------------------------------------------------------
# Exception robustness — describe() must not crash on misbehaved fields.
# ----------------------------------------------------------------------


class TestDescribeRobustness:
    def test_property_read_failure_is_dropped(self):
        class BrokenFeat(_Feature):
            def getString(self, name):
                if name == "T0":
                    raise RuntimeError("Java exploded")
                return super().getString(name)

        feat = BrokenFeat(
            "temp_x", "TemperatureBoundary", "Temperature X", [1],
            properties={"T0": "373[K]", "T0_src": "userdef"},
        )
        ifc = _Physics("ht", "HeatTransfer", "Heat Transfer in Solids", [feat])
        summary = describe(_Model([ifc]))
        props = summary["physics"][0]["features"][0]["properties"]
        # Broken key dropped, other keys survive
        assert "T0" not in props
        assert props["T0_src"] == "userdef"

    def test_selection_entities_failure_yields_empty_list(self):
        class BrokenSel(_Selection):
            def entities(self):
                raise RuntimeError("kaboom")

        class BrokenFeat(_Feature):
            def selection(self):
                return BrokenSel([])

        feat = BrokenFeat("x", "TemperatureBoundary", "X", [])
        ifc = _Physics("ht", "HeatTransfer", "HT", [feat])
        summary = describe(_Model([ifc]))
        assert summary["physics"][0]["features"][0]["selection_entities"] == []

    def test_no_physics_interfaces(self):
        summary = describe(_Model([]))
        assert summary == {"what": "physics", "physics": []}


# ----------------------------------------------------------------------
# Text formatter
# ----------------------------------------------------------------------


class TestFormatText:
    def test_block_with_hole_has_three_lines_per_user_bc(self):
        summary = describe(_block_with_hole_model())
        out = format_text(summary)
        # One header + 11 features + section title
        assert 'Physics: ht (HeatTransfer) — "Heat Transfer in Solids"' in out
        assert "features (11):" in out

    def test_temperature_boundary_shows_T0_highlight(self):
        summary = describe(_block_with_hole_model())
        out = format_text(summary)
        assert "T0=373[K]" in out
        assert "T0=293[K]" in out

    def test_heat_flux_shows_convection_highlights(self):
        summary = describe(_block_with_hole_model())
        out = format_text(summary)
        assert "HeatFluxType=ConvectiveHeatFlux" in out
        assert "h=50[W/(m^2*K)]" in out

    def test_named_selection_overrides_entities(self):
        line = _format_feature_line({
            "tag": "x", "type": "TemperatureBoundary", "name": "X",
            "selection_entities": [1, 2, 3], "selection_named": "left_face",
            "properties": {"T0": "300[K]"},
        })
        assert 'sel="left_face"' in line
        assert "entities=[1, 2, 3]" not in line

    def test_no_selection_no_highlights(self):
        line = _format_feature_line({
            "tag": "idi1", "type": "IsothermalDomainInterface",
            "name": "Isothermal Domain Interface 1",
            "selection_entities": [], "selection_named": None, "properties": {},
        })
        assert "idi1" in line
        assert "IsothermalDomainInterface" in line
        # No trailing junk
        assert line.rstrip() == line

    def test_empty_summary(self):
        out = format_text({"what": "physics", "physics": []})
        assert out == "(no physics interfaces in model)"

    def test_rejects_non_physics_summary(self):
        with pytest.raises(ValueError):
            format_text({"what": "materials", "materials": []})
