# Partially premixed steady-diffusion flamelet/PDF setup.
#
# Expected caller-provided globals:
#   MECHANISM_FILE: path to CHEMKIN mechanism file
#   THERMO_FILE: path to CHEMKIN thermodynamic database
#   FUEL_STREAM: dict of species -> fuel-stream mass fraction
#   OXIDIZER_STREAM: dict of species -> oxidizer-stream mass fraction
#
# Optional globals:
#   FLAMELET_MATERIAL_NAME = "flamelet-mixture"
#   FUEL_TEMPERATURE = 294.0
#   OXIDIZER_TEMPERATURE = 291.0
#   FLAMELET_GRID_POINTS = 32
#   MAXIMUM_PDF_SPECIES = 20

from pathlib import Path


def _required(name):
    if name not in globals():
        raise RuntimeError(f"Missing required global: {name}")
    return globals()[name]


def _tui_quote(value):
    text = str(value).replace("\\", "/")
    return '"' + text + '"'


def _validate_tui_file(path_like, label):
    path = Path(path_like).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    if " " in str(path):
        raise RuntimeError(
            f"{label} path contains spaces; copy it into the run directory "
            "before using Fluent's CHEMKIN TUI import."
        )
    return path


mechanism_file = _validate_tui_file(_required("MECHANISM_FILE"), "MECHANISM_FILE")
thermo_file = _validate_tui_file(_required("THERMO_FILE"), "THERMO_FILE")
fuel_stream = dict(_required("FUEL_STREAM"))
oxidizer_stream = dict(_required("OXIDIZER_STREAM"))

material_name = globals().get("FLAMELET_MATERIAL_NAME", "flamelet-mixture")
fuel_temperature = float(globals().get("FUEL_TEMPERATURE", 294.0))
oxidizer_temperature = float(globals().get("OXIDIZER_TEMPERATURE", 291.0))
flamelet_grid_points = int(globals().get("FLAMELET_GRID_POINTS", 32))
maximum_pdf_species = int(globals().get("MAXIMUM_PDF_SPECIES", 20))

species = solver.setup.models.species
species.model.option = "partially-premixed-combustion"
root = species.partially_premixed_model_options

chemistry = root.chemistry
chemistry.state_relation = "steady-diffusion"
chemistry.energy_treatment = "non-adia"
chemistry.flamelet_options = "create-flamelet"
try:
    chemistry.flamelet_type = "diffusion-flamelet"
except Exception:
    pass

solver.tui.file.import_.chemkin_mechanism(
    _tui_quote(material_name),
    _tui_quote(mechanism_file),
    _tui_quote(thermo_file),
)

boundary = root.boundary
all_species = sorted(set(fuel_stream) | set(oxidizer_stream))
for species_name in all_species:
    species_boundary = boundary.species_boundary[species_name]
    species_boundary.fuel = float(fuel_stream.get(species_name, 0.0))
    species_boundary.oxidizer = float(oxidizer_stream.get(species_name, 0.0))
boundary.fuel_temperature = fuel_temperature
boundary.oxidizer_temperature = oxidizer_temperature

flamelet = root.flamelet
try:
    flamelet.parameters.number_grid_points_in_flamelet = flamelet_grid_points
except Exception:
    pass

table = root.table
try:
    table.parameters.maximum_species = maximum_pdf_species
except Exception:
    pass

flamelet.parameters.calc_fla()
table.calc_pdf()

_result = {
    "step": "setup-partially-premixed-flamelet",
    "model": species.model(),
    "material_name": material_name,
    "mechanism_file": str(mechanism_file),
    "thermo_file": str(thermo_file),
    "fuel_species": sorted(fuel_stream),
    "oxidizer_species": sorted(oxidizer_stream),
    "flamelets_generated": True,
    "pdf_table_generated": True,
    "ok": True,
}
