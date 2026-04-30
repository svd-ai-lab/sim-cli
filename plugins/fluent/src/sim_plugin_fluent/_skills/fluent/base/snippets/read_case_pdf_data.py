# Read a Fluent case with its persisted flamelet/PDF table and data file.
#
# Expected caller-provided globals:
#   CASE_FILE: .cas or .cas.h5 path
#   PDF_TABLE_FILE: .pdf table path written by write_pdf_cmd
#
# Optional global:
#   DATA_FILE: .dat or .dat.h5 path. If omitted, derived from CASE_FILE.

from pathlib import Path


def _required_path(name):
    if name not in globals():
        raise RuntimeError(f"Missing required global: {name}")
    path = Path(globals()[name]).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{name} not found: {path}")
    return path


def _derive_data_file(case_file):
    text = str(case_file)
    candidates = []
    if text.endswith(".cas.h5"):
        candidates.append(Path(text[:-7] + ".dat.h5"))
    if text.endswith(".cas"):
        candidates.append(Path(text[:-4] + ".dat"))
    candidates.append(case_file.with_suffix(".dat.h5"))
    candidates.append(case_file.with_suffix(".dat"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "DATA_FILE was not provided and no matching .dat/.dat.h5 file was found."
    )


case_file = _required_path("CASE_FILE")
pdf_table_file = _required_path("PDF_TABLE_FILE")
if "DATA_FILE" in globals():
    data_file = _required_path("DATA_FILE")
else:
    data_file = _derive_data_file(case_file)

solver.settings.file.read_case(file_name=str(case_file))
solver.settings.file.read_pdf(file_name=str(pdf_table_file))
solver.settings.file.read_data(file_name=str(data_file))

_result = {
    "step": "read-case-pdf-data",
    "case_file": str(case_file),
    "pdf_table_file": str(pdf_table_file),
    "data_file": str(data_file),
    "readback_order": ["read_case", "read_pdf", "read_data"],
    "ok": True,
}
