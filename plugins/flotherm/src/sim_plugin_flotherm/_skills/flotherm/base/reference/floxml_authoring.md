# FloXML Authoring Reference

The vendor-blessed format for **authoring** Flotherm models from scratch.
FloSCRIPT is the wrong tool for this — use it only for orchestration and
parametric sweeps over an existing model. See
[`floscript_modeling.md`](floscript_modeling.md) for the FloSCRIPT side.

## Why FloXML

| | FloSCRIPT | FloXML |
|---|---|---|
| Designed for | record-and-replay of GUI actions | model authoring / import |
| Property names | undocumented internal enums | named XML elements (self-documenting) |
| Schema | `xs:string` for everything semantic | rich, all elements typed |
| Examples shipped | `Utilities/Grid-HeatSinks-and-Fans.xml` only | `Project FloXML Examples/`, `Assembly FloXML Examples/` |
| Authoring works | structural geometry only (size/position) | yes |

## Pipeline

```
1. Author Project FloXML  (full model in one <xml_case> file)
2. <project_import filename="..." import_type="FloXML"/>   ← via FloSCRIPT
3. <project_save_as project_name="..."/>                    ← creates .pack
4. <start start_type="solver"/>                             ← solve
5. Read .pack solution dir for results
```

## Reference hierarchy

When you need an element you haven't used before, consult sources in this order:

| Order | Source | What it gives you | Where |
|---|---|---|---|
| 1 | **FloXML XSD** | Canonical declaration of every element/attribute/enum | `examples/DCIM Development Toolkit/Schema Files/FloXML/*.xsd` (5 files, ~190 KB) |
| 2 | **Vendor templates** | Working examples of common cases | `examples/FloXML/FloXML Files/` (8 files, ~120 KB) |
| 3 | **lixiekun/flotherm-automation** | Real-world full models (~95 KB Heatsink_final.xml etc.) | https://github.com/lixiekun/flotherm-automation |
| 4 | **GUI export oracle** | Last-resort: build it in GUI, export, read syntax | `Project → Export → FloXML` |

**Rule:** start with XSD. The templates are tutorials, not specifications — they show ~10 of the 18 `_att` types and ~18 of the ~30 geometry types. The XSD has all of them.

## FloXML XSD (canonical reference, 5 files)

```
C:\Program Files\Siemens\SimcenterFlotherm\2504\examples\DCIM Development Toolkit\Schema Files\FloXML\
├── XmlAttributes.xsd       36 KB    All <*_att> definitions (18 types — see below)
├── XmlGeometry.xsd        111 KB    All geometry types (cuboid, source, pcb, network_*, etc.)
├── XmlEntities.xsd         28 KB    Shared sub-types (color, position, transparency, electrical_resistivity, ...)
├── XmlDefinitions.xsd      11 KB    Numeric base types (doubleGTZero, percentage, trueFalse, ...)
└── xmlSchema.xsd            7 KB    Top-level schema bindings
```

### All `_att` types declared in XmlAttributes.xsd

```
ambient_att              biaxial_material_att     control_att              control_curve_att
fan_att                  fluid_att                grid_constraint_att      isotropic_material_att
occupancy_att            orthotropic_material_att radiation_att            resistance_att
source_att               surface_att              surface_exchange_att     temperature_dependant_material_att
thermal_att              transient_att
```

### Concrete examples for elements not in vendor templates

**`<orthotropic_material_att>`** (anisotropic material — needed for HBM μbumps).
From XmlAttributes.xsd line 88-109:
```xml
<orthotropic_material_att>
  <name>Bump_Composite</name>
  <x_conductivity>1.0</x_conductivity>          <!-- in-plane k_xy -->
  <y_conductivity>25.0</y_conductivity>         <!-- through-stack k_z -->
  <z_conductivity>1.0</z_conductivity>          <!-- in-plane k_xy -->
  <density>5000</density>
  <specific_heat>400</specific_heat>
  <electrical_resistivity>
    <type>constant</type>
    <resistivity_value>0</resistivity_value>
  </electrical_resistivity>
</orthotropic_material_att>
```
Optional fields per XSD: `x_input_method`/`y_input_method`/`z_input_method` (curve vs constant), `x_conductivity_curve`/`y_conductivity_curve`/`z_conductivity_curve`, `transparent`, `transparency`, `phase_change`, `surface`, `notes`.

**`<thermal_att>` with all 4 thermal_model enums** (XmlAttributes.xsd line 242-263). Templates only show `conduction`; the XSD declares 4:
```xml
<!-- conduction (heat flux into solid via conductivity contact) -->
<thermal_att>
  <name>...</name>
  <thermal_model>conduction</thermal_model>
  <power>3.0</power>
</thermal_att>

<!-- fixed_temperature (Dirichlet BC — what we wanted in HBM Phase 1b) -->
<thermal_att>
  <name>ColdPlate</name>
  <thermal_model>fixed_temperature</thermal_model>
  <fixed_temperature>333.15</fixed_temperature>
</thermal_att>

<!-- fixed_heat_flow (Neumann BC) -->
<thermal_att>
  <name>...</name>
  <thermal_model>fixed_heat_flow</thermal_model>
  <fixed_heat_flow>...</fixed_heat_flow>
</thermal_att>

<!-- joule_heating (electrical heating) -->
<thermal_att>
  <name>...</name>
  <thermal_model>joule_heating</thermal_model>
  <joule_heating>...</joule_heating>
</thermal_att>
```

**Unit gotcha** (verified 2026-04-19 on Flotherm 2504): `<fixed_temperature>` value is in **°C**, not K. This is inconsistent with `<ambient_att><temperature>` which IS in K. Concretely:

```xml
<!-- correct: 60 °C cold plate -->
<thermal_att>
  <name>ColdPlate</name>
  <thermal_model>fixed_temperature</thermal_model>
  <fixed_temperature>60</fixed_temperature>
</thermal_att>

<!-- correct: 25 °C ambient -->
<ambient_att>
  <name>Ambient</name>
  <temperature>298.15</temperature>    <!-- Kelvin! -->
  ...
</ambient_att>
```

If you put `333.15` in `<fixed_temperature>` thinking it's Kelvin, you get 333.15 °C = ~606 K, way too hot.

**End-to-end validation on Flotherm 2504 (2026-04-19):** both `<orthotropic_material_att>` and `<thermal_att thermal_model="fixed_temperature">` were verified via import + solve on a modified HBM 3-block model. The pad cuboid (material Aluminum, thermal ColdPlate, fixed at 60 °C) ended up at exactly 60.00 °C with heat flowing into it from the stack above; BottomBump_Aniso cuboid correctly resolved to orthotropic material by name. Reference test case: [examples/xsd_element_validation.xml](examples/xsd_element_validation.xml).

(HBM Phase 1b used a high-HTC ambient_att as a workaround — that was unnecessary. `thermal_model=fixed_temperature` is the canonical path. Phase 2a should switch.)

## Vendor templates (working examples, 8 files)

Location: `C:\Program Files\Siemens\SimcenterFlotherm\2504\examples\FloXML\FloXML Files\`

### Coverage matrix (audited 2026-04-19)

| Template | Lines | `_att` types covered | Geometry types covered |
|---|---:|---|---|
| `Assembly FloXML Examples/Block.xml` | 31 | `isotropic_material_att` | `cuboid` |
| `Assembly FloXML Examples/Nested-Assemblies.xml` | 72 | `isotropic_material_att` | `cuboid`, `assembly` (nested) |
| `Assembly FloXML Examples/2R-Model.xml` | 118 | `thermal_att` (name+power, no thermal_model) | `resistance`, `assembly`, `monitor_point` |
| `Assembly FloXML Examples/Advanced-Resistance.xml` | 38 | `resistance_att` | `resistance` |
| `Project FloXML Examples/Default.xml` | 96 | none | none — bare project skeleton (model/grid/solve/solution_domain) |
| `Project FloXML Examples/PDML-Referencing-FullModel.xml` | 170 | `ambient_att`, `fluid_att` | `fixed_flow`, `monitor_point` |
| `Project FloXML Examples/Heatsink-Windtunnel-FullModel.xml` ★ | 994 | `isotropic_material_att`, `surface_att`, `ambient_att`, `fluid_att`, `source_att` | `cuboid`, `source`, `fixed_flow`, `monitor_point`, `assembly` |
| `Project FloXML Examples/All-Objects-Attributes-Settings-FullModel.xml` ★★ | 2400+ | `isotropic_material_att`, `surface_att`, `ambient_att`, `fluid_att`, `source_att`, `thermal_att` (with `thermal_model=conduction`), `radiation_att`, `resistance_att`, `grid_constraint_att`, `transient_att`, `control_att`, `fan_att`, `occupancy_att`, `surface_exchange_att` | 18 types: `cuboid`, `source`, `cylinder`, `prism`, `tet`, `fan`, `fixed_flow`, `hole`, `monitor_point`, `pcb`, `resistance`, `cooler`, `enclosure`, `cutout`, `controller`, `tec`, `die`, `assembly` |

★ Recommended starting point for full thermal cases.
★★ Reference for any unfamiliar element type — pull the relevant block and adapt.

### Templates don't show — XSD does

Several common elements aren't in any vendor template but ARE fully declared in the XSD. **Don't conclude "unsupported" from template absence — check the XSD first.** Audited 2026-04-19:

| Element | In templates? | In XSD? | Where in XSD |
|---|---|---|---|
| `<orthotropic_material_att>` | No | **Yes** | XmlAttributes.xsd:88-109 |
| `<biaxial_material_att>` | No | **Yes** | XmlAttributes.xsd:130+ |
| `<temperature_dependant_material_att>` | No | **Yes** | XmlAttributes.xsd:112-127 |
| `<thermal_att thermal_model="fixed_temperature">` | No (only `conduction`) | **Yes** (4 enum values) | XmlAttributes.xsd:242-263 |
| `<thermal_att thermal_model="fixed_heat_flow">` | No | **Yes** | same |
| `<thermal_att thermal_model="joule_heating">` | No | **Yes** | same |

For elements legitimately outside FloXML scope (boolean geometry ops like mold-compound wrapping a die stack with cutouts), use the GUI: create in `FloMCAD Bridge`, then `Project → Export → FloXML`. Or model as separate cuboids and accept the slightly cruder geometry.

**Workflow for any unfamiliar element:**
1. `grep -n "complexType name=\"<thing>\"" XmlAttributes.xsd XmlGeometry.xsd` — find the declaration
2. Read the `<xs:all>` block — these are the child elements + their types
3. For enum-restricted attributes, the values are right there in `<xs:enumeration>`
4. If still ambiguous, build it in the GUI and `Project → Export → FloXML` for ground truth

**Start from `Heatsink-Windtunnel-FullModel.xml`** for any new authored model — it's the smallest complete project FloXML with geometry + attributes + boundaries + solver settings. Then layer in XSD-derived elements as needed.

## Project FloXML structure

```xml
<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
<xml_case>
  <name>MyProject</name>
  <model>            <!-- modeling, turbulence, gravity, global -->
  <solve>            <!-- overall_control: iterations, relaxation -->
  <grid>             <!-- system_grid x/y/z resolution -->
  <attributes>       <!-- materials, sources, ambients, fluids, etc -->
  <geometry>         <!-- cuboids, sources, monitor_points -->
  <solution_domain>  <!-- bounding box + boundary BCs -->
</xml_case>
```

## Material attribute (canonical)

```xml
<attributes>
  <materials>
    <isotropic_material_att>
      <name>Silicon</name>
      <conductivity>148</conductivity>     <!-- W/m·K -->
      <density>2330</density>              <!-- kg/m³ -->
      <specific_heat>700</specific_heat>   <!-- J/kg·K -->
      <electrical_resistivity>
        <type>constant</type>
        <resistivity_value>0</resistivity_value>
      </electrical_resistivity>
    </isotropic_material_att>
  </materials>
</attributes>
```

For anisotropic, use `<orthotropic_material_att>` with `<x_conductivity>`,
`<y_conductivity>`, `<z_conductivity>` (note: snake_case prefix, NOT
`conductivity_x`).

## Source attribute (canonical)

```xml
<attributes>
  <sources>
    <source_att>
      <name>Source_3W</name>
      <source_options>
        <option>
          <applies_to>temperature</applies_to>
          <type>total</type>
          <value>0</value>
          <power>3</power>                <!-- Watts -->
          <linear_coefficient>0</linear_coefficient>
        </option>
      </source_options>
    </source_att>
  </sources>
</attributes>
```

## Geometry: cuboid + material attachment

```xml
<geometry>
  <cuboid>
    <name>BaseDie</name>
    <active>true</active>
    <position><x>0</x><y>0</y><z>0</z></position>
    <size><x>0.011</x><y>0.0001</y><z>0.011</z></size>     <!-- meters -->
    <orientation>
      <local_x><i>1</i><j>0</j><k>0</k></local_x>
      <local_y><i>0</i><j>1</j><k>0</k></local_y>
      <local_z><i>0</i><j>0</j><k>1</k></local_z>
    </orientation>
    <material>Silicon</material>                            <!-- attribute reference by name -->
    <localized_grid>false</localized_grid>
  </cuboid>
</geometry>
```

## Geometry: source (heater) referencing source attribute

```xml
<source>
  <name>BaseDie_Heater</name>
  <active>true</active>
  <position><x>0.001</x><y>0.00005</y><z>0.001</z></position>
  <size><x>0.009</x><y>0.00001</y><z>0.009</z></size>      <!-- thin slab inside the die -->
  <orientation>...</orientation>
  <source>Source_3W</source>                                <!-- attribute reference by name -->
  <localized_grid>false</localized_grid>
</source>
```

The `<source>` geometry overlaps the heat-generating volume of the die.
Make it thin (e.g. 10 µm) and slightly inset from the die edges to
ensure cells are captured.

## Solution domain (bounding box + BCs)

```xml
<solution_domain>
  <position><x>-0.005</x><y>-0.001</y><z>-0.005</z></position>
  <size><x>0.021</x><y>0.011</y><z>0.021</z></size>
  <x_low_ambient>Ambient</x_low_ambient>
  <x_high_ambient>Ambient</x_high_ambient>
  <y_low_boundary>symmetry</y_low_boundary>
  <y_high_ambient>Ambient</y_high_ambient>
  <z_low_ambient>Ambient</z_low_ambient>
  <z_high_ambient>Ambient</z_high_ambient>
  <fluid>Air</fluid>
</solution_domain>
```

Each face of the bounding box is either:
- `<face_ambient>NameOfAmbientAttribute</face_ambient>` (open to ambient)
- `<face_boundary>symmetry</face_boundary>` (mirror)

## Importing into Flotherm

```xml
<!-- via FloSCRIPT -->
<xml_log_file version="1.0">
  <project_import filename="C:/path/to/model.xml" import_type="FloXML"/>
</xml_log_file>
```

Then inside the same FloSCRIPT or a follow-up:

```xml
<xml_log_file version="1.0">
  <project_save_as project_name="my_project"/>
  <start start_type="solver"/>
</xml_log_file>
```

## Result extraction

After solve, results live at:
```
flouser/<project_name>.<32-hex-hash>/DataSets/BaseSolution/
  PDTemp/logit                       # solver residuals (text)
  msp_0/end/Temperature              # binary float32, 4-byte header + nx*ny*nz floats
  msp_0/end/Pressure                 # same layout
  msp_0/end/{X,Y,Z}Velocity          # same layout
  msp_0/end/Speed                    # |velocity|
```

Mesh dimensions (`nx`, `ny`, `nz`) are in the logit file:
`domain 0 no. in x =NN no. in y =NN no. in z =NN`.

Binary layout verified 2026-04-26 across 4 solved projects: header is a
4-byte sentinel (observed `00 00 00 00`), body is exactly `nx·ny·nz`
IEEE-754 float32 little-endian values, file size = `4 + 4·nx·ny·nz`,
no Fortran trailing record marker.

Cell ordering (x-fastest vs z-fastest) and temperature units (°C vs K)
are still unverified — sample a Dirichlet-pinned cell (e.g. a
`<thermal_att thermal_model="fixed_temperature">` cuboid) before trusting
absolute values. See [`postprocessing.md`](postprocessing.md) for the
full reader sketch + the FloSCRIPT export commands that bypass binary
parsing entirely.

## End-to-end example

See [hbm-flotherm/build/hbm_3block.xml](https://github.com/svd-ai-lab/hbm-flotherm/blob/main/build/hbm_3block.xml)
for a complete 3-block HBM stack (cuboids + materials + sources +
monitor points + boundaries) that imports + solves cleanly on
Flotherm 2504.

## Gotchas

### `solve_all` is not top-level FloSCRIPT — use `<start start_type="solver"/>`
`<solve_all/>` is valid only inside `external_command process="MCAD"`
scenario contexts. Top-level FloSCRIPT solve element is `<start>`.

### Don't sweep imports back-to-back
Each `<project_import>` opens the imported project as a NEW Flotherm
window. ~10 in a row exhausted Flotherm and crashed all instances.
**One import per session, then operate on it.**

### Mesh tuning matters
The default `system_grid` `max_size` of 0.001 m gives ~10K cells for
a 21mm domain. For HBM-scale (sub-millimeter features), drop `min_size`
to 1e-5 and `max_size` to 5e-4 for the y-axis (vertical, where layers
are thinnest).

### Coordinate units are meters
Throughout — sizes, positions, etc. Convert from mm to m before writing.

### "FluidConductivity" appears in solution dir even for solid-only models
That's fine. The solver always outputs the air fluid conductivity field
because the solution domain has fluid bg.
