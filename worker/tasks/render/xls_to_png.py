from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List, Tuple

from .pdf_to_png import convert as pdf_bytes_to_png
from .utils.libreoffice import convert_to_pdf

XLS_SUFFIXES = {".xls", ".xlsx", ".xlsm", ".ods", ".fods"}
_XLS_FILTER = (
    "calc_pdf_Export:"
    "UseLosslessCompression=true;"
    "SelectPdfVersion=1;"
    "FitToPages=true"
)


def convert(sheet_bytes: bytes, base_name: str, *, suffix: str) -> List[Tuple[str, bytes]]:
    """Convert spreadsheet files (XLS/XLSX/ODS) to PNG via LibreOffice and Ghostscript."""
    suffix = suffix.lower()
    if suffix not in XLS_SUFFIXES:
        raise RuntimeError(f"Формат {suffix or 'неизвестный'} не поддерживается для конвертации таблиц → PNG.")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        source_path = tmp_path / f"source{suffix}"
        source_path.write_bytes(sheet_bytes)

        pdf_path = convert_to_pdf(source_path, tmp_path, filter_name=_XLS_FILTER)
        pdf_bytes = pdf_path.read_bytes()

        return pdf_bytes_to_png(pdf_bytes, base_name=base_name)
