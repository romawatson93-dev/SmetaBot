from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List, Tuple

from .pdf_to_png import convert as pdf_bytes_to_png
from .utils.libreoffice import convert_to_pdf

DOC_SUFFIXES = {".doc", ".docx"}
_DOC_FILTER = (
    "writer_pdf_Export:"
    "EmbedStandardFonts=true;"
    "UseTaggedPDF=false;"
    "UseLosslessCompression=true;"
    "ExportNotes=false;"
    "SkipEmptyPages=false;"
    "ExportBookmarks=false;"
    "SelectPdfVersion=1"
)


def convert(doc_bytes: bytes, base_name: str, *, suffix: str) -> List[Tuple[str, bytes]]:
    """Convert DOC/DOCX documents to PNG using LibreOffice and Ghostscript."""
    suffix = suffix.lower()
    if suffix not in DOC_SUFFIXES:
        raise RuntimeError(f"Формат {suffix or 'неизвестный'} не поддерживается для конвертации Word → PNG.")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        source_path = tmp_path / f"source{suffix}"
        source_path.write_bytes(doc_bytes)

        pdf_path = convert_to_pdf(source_path, tmp_path, filter_name=_DOC_FILTER)
        pdf_bytes = pdf_path.read_bytes()

        return pdf_bytes_to_png(pdf_bytes, base_name=base_name)
