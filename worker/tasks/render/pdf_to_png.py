from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List, Tuple

from .utils.ghostscript import pdf_to_png as ghostscript_pdf_to_png


def convert(pdf_bytes: bytes, base_name: str, *, dpi: int = 300, color: bool = True) -> List[Tuple[str, bytes]]:
    """Render a PDF document to PNG images using Ghostscript."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        pdf_path = tmp_path / "source.pdf"
        pdf_path.write_bytes(pdf_bytes)

        png_paths = ghostscript_pdf_to_png(
            pdf_path=pdf_path,
            output_dir=tmp_path,
            base_name=base_name,
            dpi=dpi,
            color=color,
        )

        total = len(png_paths)
        result: List[Tuple[str, bytes]] = []
        for idx, path in enumerate(png_paths, start=1):
            filename = f"{base_name}-{idx:03d}.png" if total > 1 else f"{base_name}.png"
            result.append((filename, path.read_bytes()))
        return result
