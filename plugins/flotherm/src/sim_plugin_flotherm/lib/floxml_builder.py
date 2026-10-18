"""Minimal Pythonic builder for Flotherm FloXML (`<xml_case>`) documents.

Emits valid FloXML that the existing `lib.floxml.lint_floxml` accepts and
that the Flotherm 2504 translator can ingest. Scope is deliberately
minimal — just enough to build small reference cases for testing and
cell-ordering certification:

  - Isotropic materials
  - Ambients (with temperature, pressure, optional HTC)
  - Fluids (constant-property)
  - Heat sources (`source_att`) with a single `option`
  - Thermal boundary conditions (`thermal_att` with `fixed_temperature`)
  - Cuboid geometry that references those attributes
  - Solution-domain bounding box with per-face Ambient or symmetry BCs

All other fields (turbulence, gravity, solve control, grid, etc.) get
vendor-blessed defaults observed in the bundled reference case
`sim-skills/flotherm/base/reference/examples/xsd_element_validation.xml`.
Override what you need; ignore the rest.

Future scope (separate PR): orthotropic materials, transient runs, HTC
boundary conditions, monitor points beyond cuboid centers, fan curves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from xml.dom import minidom
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import Element, SubElement

# Boundary condition references on the solution-domain faces. The vendor
# treats per-face "ambient" as an attribute name (string) and `symmetry`
# as a literal flag — any non-symmetry value is taken as an Ambient name.
BCType = Literal["symmetry"] | str

# Vendor-blessed defaults for the verbose `<model>` / `<solve>` / `<grid>`
# scaffolding. Pulled from xsd_element_validation.xml.
_DEFAULT_AMBIENT_K = 298.15  # 25°C, vendor default
_DEFAULT_DATUM_PRESSURE = 101325


# ---------------------------------------------------------------------------
# Attribute primitives
# ---------------------------------------------------------------------------


@dataclass
class IsotropicMaterial:
    name: str
    conductivity: float           # W/(m·K)
    density: float                # kg/m³
    specific_heat: float          # J/(kg·K)


@dataclass
class Ambient:
    name: str
    temperature_k: float = _DEFAULT_AMBIENT_K   # NOTE: this is K, vendor convention
    pressure: float = 0.0
    radiant_temperature_k: float = _DEFAULT_AMBIENT_K
    heat_transfer_coeff: float = 0.0


@dataclass
class Fluid:
    """Constant-property fluid. Air defaults from xsd_element_validation."""
    name: str = "Air"
    conductivity: float = 0.0261
    viscosity: float = 1.84e-5
    density: float = 1.1614
    specific_heat: float = 1008.0
    expansivity: float = 0.003


@dataclass
class HeatSource:
    """`<source_att>` with a single power-applied option."""
    name: str
    power_w: float


@dataclass
class FixedTemperature:
    """`<thermal_att thermal_model="fixed_temperature">`. Temp is in °C."""
    name: str
    temperature_c: float


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


@dataclass
class Cuboid:
    """Axis-aligned cuboid geometry. Position is the min corner."""
    name: str
    position: tuple[float, float, float]   # (x, y, z) in metres
    size: tuple[float, float, float]
    material: str | None = None            # IsotropicMaterial.name
    thermal: str | None = None             # FixedTemperature.name (Dirichlet pin)
    source: str | None = None              # HeatSource.name


# ---------------------------------------------------------------------------
# Solution domain
# ---------------------------------------------------------------------------


@dataclass
class SolutionDomain:
    position: tuple[float, float, float]
    size: tuple[float, float, float]
    fluid: str = "Air"
    # Per-face boundary: an Ambient name or the literal "symmetry"
    x_low: BCType = "Ambient"
    x_high: BCType = "Ambient"
    y_low: BCType = "Ambient"
    y_high: BCType = "Ambient"
    z_low: BCType = "Ambient"
    z_high: BCType = "Ambient"


# ---------------------------------------------------------------------------
# Project — the root builder
# ---------------------------------------------------------------------------


@dataclass
class Project:
    """Top-level FloXML project (`<xml_case>`).

    Build incrementally:

        project = Project(name="cell_order_ref")
        project.materials.append(IsotropicMaterial("Silicon", 148, 2330, 700))
        project.thermals.append(FixedTemperature("HotFace", 60))
        project.cuboids.append(Cuboid(
            "HotPlate", position=(0, 0, 0), size=(5e-3, 1e-3, 1.1e-2),
            material="Silicon", thermal="HotFace",
        ))
        project.solution_domain = SolutionDomain(
            position=(-1e-3, -1e-3, -1e-3),
            size=(7e-3, 5e-3, 1.3e-2),
        )
        xml_text = project.to_xml()

    Required: at least one Ambient (added by default), one Fluid (Air),
    a SolutionDomain, and one Cuboid.
    """
    name: str
    materials: list[IsotropicMaterial] = field(default_factory=list)
    ambients: list[Ambient] = field(default_factory=lambda: [Ambient("Ambient")])
    fluids: list[Fluid] = field(default_factory=lambda: [Fluid()])
    sources: list[HeatSource] = field(default_factory=list)
    thermals: list[FixedTemperature] = field(default_factory=list)
    cuboids: list[Cuboid] = field(default_factory=list)
    solution_domain: SolutionDomain | None = None
    # Mesh hint — populated in <grid>. None = use vendor defaults.
    grid_max_size: float = 5e-3   # default cell ceiling (~5mm)
    grid_min_size: float = 5e-4   # default cell floor (~0.5mm)
    outer_iterations: int = 500
    ambient_temperature_k: float = _DEFAULT_AMBIENT_K

    def to_xml(self) -> str:
        """Render to a UTF-8 FloXML document with `<?xml ...?>` prolog."""
        if self.solution_domain is None:
            raise ValueError("Project.solution_domain must be set before to_xml()")
        if not self.cuboids:
            raise ValueError("Project must have at least one cuboid")

        root = Element("xml_case")
        SubElement(root, "name").text = self.name
        self._add_model(root)
        self._add_solve(root)
        self._add_grid(root)
        self._add_attributes(root)
        self._add_geometry(root)
        self._add_solution_domain(root)

        raw = ET.tostring(root, encoding="unicode")
        # minidom adds a prolog and indentation; strip its empty first line
        pretty = minidom.parseString(raw).toprettyxml(
            indent="  ", encoding="UTF-8",
        ).decode("utf-8")
        # Drop blank lines that minidom interleaves on Python 3.10+
        return "\n".join(ln for ln in pretty.splitlines() if ln.strip()) + "\n"

    # -- model ---------------------------------------------------------------

    def _add_model(self, root: Element) -> None:
        m = SubElement(root, "model")
        modeling = SubElement(m, "modeling")
        for tag, val in [
            ("solution", "flow_heat"),
            ("radiation", "off"),
            ("dimensionality", "3d"),
            ("transient", "false"),
            ("store_mass_flux", "false"),
            ("store_heat_flux", "false"),
            ("store_surface_temp", "true"),
            ("store_grad_t", "false"),
            ("store_bn_sc", "false"),
            ("store_power_density", "false"),
            ("store_mean_radiant_temperature", "false"),
            ("compute_capture_index", "false"),
            ("user_defined_subgroups", "false"),
            ("store_lma", "false"),
        ]:
            SubElement(modeling, tag).text = val

        turb = SubElement(m, "turbulence")
        SubElement(turb, "type").text = "turbulent"
        SubElement(turb, "turbulence_type").text = "auto_algebraic"

        grav = SubElement(m, "gravity")
        SubElement(grav, "type").text = "normal"
        SubElement(grav, "normal_direction").text = "neg_y"
        SubElement(grav, "value_type").text = "user"
        SubElement(grav, "gravity_value").text = "9.81"

        glob = SubElement(m, "global")
        SubElement(glob, "datum_pressure").text = str(_DEFAULT_DATUM_PRESSURE)
        SubElement(glob, "radiant_temperature").text = str(self.ambient_temperature_k)
        SubElement(glob, "ambient_temperature").text = str(self.ambient_temperature_k)
        for i in range(1, 6):
            SubElement(glob, f"concentration_{i}").text = "0"

    def _add_solve(self, root: Element) -> None:
        s = SubElement(root, "solve")
        ctl = SubElement(s, "overall_control")
        SubElement(ctl, "outer_iterations").text = str(self.outer_iterations)
        SubElement(ctl, "fan_relaxation").text = "1"
        SubElement(ctl, "estimated_free_convection_velocity").text = "0.2"
        SubElement(ctl, "solver_option").text = "multi_grid"
        SubElement(ctl, "active_plate_conduction").text = "false"
        SubElement(ctl, "use_double_precision").text = "false"
        SubElement(ctl, "network_assembly_block_correction").text = "false"
        SubElement(ctl, "freeze_flow").text = "false"
        SubElement(ctl, "store_error_field").text = "false"

    def _add_grid(self, root: Element) -> None:
        g = SubElement(root, "grid")
        sg = SubElement(g, "system_grid")
        SubElement(sg, "smoothing").text = "true"
        SubElement(sg, "smoothing_type").text = "v3"
        SubElement(sg, "dynamic_update").text = "true"
        for axis in ("x_grid", "y_grid", "z_grid"):
            ax = SubElement(sg, axis)
            SubElement(ax, "min_size").text = str(self.grid_min_size)
            SubElement(ax, "grid_type").text = "max_size"
            SubElement(ax, "max_size").text = str(self.grid_max_size)
            SubElement(ax, "smoothing_value").text = "12"

    # -- attributes ----------------------------------------------------------

    def _add_attributes(self, root: Element) -> None:
        a = SubElement(root, "attributes")

        mats = SubElement(a, "materials")
        for mat in self.materials:
            self._emit_material(mats, mat)

        ambs = SubElement(a, "ambients")
        for amb in self.ambients:
            self._emit_ambient(ambs, amb)

        fluids = SubElement(a, "fluids")
        for fluid in self.fluids:
            self._emit_fluid(fluids, fluid)

        if self.sources:
            srcs = SubElement(a, "sources")
            for src in self.sources:
                self._emit_source(srcs, src)

        if self.thermals:
            therms = SubElement(a, "thermals")
            for therm in self.thermals:
                self._emit_thermal(therms, therm)

    @staticmethod
    def _emit_material(parent: Element, mat: IsotropicMaterial) -> None:
        m = SubElement(parent, "isotropic_material_att")
        SubElement(m, "name").text = mat.name
        SubElement(m, "conductivity").text = str(mat.conductivity)
        SubElement(m, "density").text = str(mat.density)
        SubElement(m, "specific_heat").text = str(mat.specific_heat)
        er = SubElement(m, "electrical_resistivity")
        SubElement(er, "type").text = "constant"
        SubElement(er, "resistivity_value").text = "0"

    @staticmethod
    def _emit_ambient(parent: Element, amb: Ambient) -> None:
        e = SubElement(parent, "ambient_att")
        SubElement(e, "name").text = amb.name
        SubElement(e, "pressure").text = str(amb.pressure)
        SubElement(e, "temperature").text = str(amb.temperature_k)
        SubElement(e, "radiant_temperature").text = str(amb.radiant_temperature_k)
        SubElement(e, "heat_transfer_coeff").text = str(amb.heat_transfer_coeff)
        v = SubElement(e, "velocity")
        SubElement(v, "x").text = "0"
        SubElement(v, "y").text = "0"
        SubElement(v, "z").text = "0"
        SubElement(e, "turbulent_kinetic_energy").text = "0"
        SubElement(e, "turbulent_dissipation_rate").text = "0"
        for i in range(1, 6):
            SubElement(e, f"concentration_{i}").text = "0"

    @staticmethod
    def _emit_fluid(parent: Element, fluid: Fluid) -> None:
        f = SubElement(parent, "fluid_att")
        SubElement(f, "name").text = fluid.name
        SubElement(f, "conductivity_type").text = "constant"
        SubElement(f, "conductivity").text = str(fluid.conductivity)
        SubElement(f, "viscosity_type").text = "constant"
        SubElement(f, "viscosity").text = str(fluid.viscosity)
        SubElement(f, "density_type").text = "constant"
        SubElement(f, "density").text = str(fluid.density)
        SubElement(f, "specific_heat").text = str(fluid.specific_heat)
        SubElement(f, "expansivity").text = str(fluid.expansivity)
        SubElement(f, "diffusivity").text = "0"

    @staticmethod
    def _emit_source(parent: Element, src: HeatSource) -> None:
        s = SubElement(parent, "source_att")
        SubElement(s, "name").text = src.name
        opts = SubElement(s, "source_options")
        opt = SubElement(opts, "option")
        SubElement(opt, "applies_to").text = "temperature"
        SubElement(opt, "type").text = "total"
        SubElement(opt, "value").text = "0"
        SubElement(opt, "power").text = str(src.power_w)
        SubElement(opt, "linear_coefficient").text = "0"

    @staticmethod
    def _emit_thermal(parent: Element, therm: FixedTemperature) -> None:
        t = SubElement(parent, "thermal_att")
        SubElement(t, "name").text = therm.name
        SubElement(t, "thermal_model").text = "fixed_temperature"
        SubElement(t, "fixed_temperature").text = str(therm.temperature_c)

    # -- geometry ------------------------------------------------------------

    def _add_geometry(self, root: Element) -> None:
        g = SubElement(root, "geometry")
        for cub in self.cuboids:
            self._emit_cuboid(g, cub)

    @staticmethod
    def _emit_cuboid(parent: Element, c: Cuboid) -> None:
        e = SubElement(parent, "cuboid")
        SubElement(e, "name").text = c.name
        SubElement(e, "active").text = "true"
        pos = SubElement(e, "position")
        SubElement(pos, "x").text = str(c.position[0])
        SubElement(pos, "y").text = str(c.position[1])
        SubElement(pos, "z").text = str(c.position[2])
        sz = SubElement(e, "size")
        SubElement(sz, "x").text = str(c.size[0])
        SubElement(sz, "y").text = str(c.size[1])
        SubElement(sz, "z").text = str(c.size[2])
        ori = SubElement(e, "orientation")
        for axis_name, vec in (("local_x", (1, 0, 0)),
                               ("local_y", (0, 1, 0)),
                               ("local_z", (0, 0, 1))):
            ax = SubElement(ori, axis_name)
            for tag, v in zip(("i", "j", "k"), vec):
                SubElement(ax, tag).text = str(v)
        if c.material:
            SubElement(e, "material").text = c.material
        if c.thermal:
            SubElement(e, "thermal").text = c.thermal
        if c.source:
            SubElement(e, "source").text = c.source
        SubElement(e, "localized_grid").text = "false"

    # -- solution domain -----------------------------------------------------

    def _add_solution_domain(self, root: Element) -> None:
        sd = self.solution_domain
        assert sd is not None  # checked in to_xml()
        e = SubElement(root, "solution_domain")
        pos = SubElement(e, "position")
        SubElement(pos, "x").text = str(sd.position[0])
        SubElement(pos, "y").text = str(sd.position[1])
        SubElement(pos, "z").text = str(sd.position[2])
        sz = SubElement(e, "size")
        SubElement(sz, "x").text = str(sd.size[0])
        SubElement(sz, "y").text = str(sd.size[1])
        SubElement(sz, "z").text = str(sd.size[2])
        for face_name, bc in [
            ("x_low", sd.x_low), ("x_high", sd.x_high),
            ("y_low", sd.y_low), ("y_high", sd.y_high),
            ("z_low", sd.z_low), ("z_high", sd.z_high),
        ]:
            tag = f"{face_name}_boundary" if bc == "symmetry" else f"{face_name}_ambient"
            SubElement(e, tag).text = bc
        SubElement(e, "fluid").text = sd.fluid
