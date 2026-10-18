# Persist the active partially-premixed PDF table.
#
# Expected caller-provided global:
#   PDF_TABLE_FILE: output .pdf table path
#
# Optional global:
#   PDF_TABLE_BINARY = True

from pathlib import Path


if "PDF_TABLE_FILE" not in globals():
    raise RuntimeError("Missing required global: PDF_TABLE_FILE")

pdf_table_file = Path(PDF_TABLE_FILE).resolve()
pdf_table_file.parent.mkdir(parents=True, exist_ok=True)
binary = bool(globals().get("PDF_TABLE_BINARY", True))

root = solver.setup.models.species.partially_premixed_model_options
root.table.write_pdf_cmd(
    binary=binary,
    write_pdf_file=str(pdf_table_file),
)

_result = {
    "step": "write-pdf-table",
    "pdf_table_file": str(pdf_table_file),
    "binary": binary,
    "pdf_written": pdf_table_file.exists(),
    "ok": pdf_table_file.exists(),
}
