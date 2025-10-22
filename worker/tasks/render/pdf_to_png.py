from __future__ import annotations

from typing import List, Optional, Tuple

import fitz


def _resolve_page_bounds(total_pages: int, first_page: Optional[int], last_page: Optional[int]) -> Tuple[int, int]:
    """Clamp requested page range to the document boundaries."""
    start = first_page or 1
    end = last_page or total_pages
    if start < 1 or start > total_pages:
        raise ValueError(f"Requested first_page {start} is outside document (1..{total_pages}).")
    if end < start:
        raise ValueError(f"Requested last_page {end} must be >= first_page {start}.")
    end = min(end, total_pages)
    return start, end


def convert(
    pdf_bytes: bytes,
    base_name: str,
    *,
    dpi: int = 300,
    color: bool = True,
    first_page: Optional[int] = None,
    last_page: Optional[int] = None,
) -> List[Tuple[str, bytes]]:
    """Render a PDF document to PNG images using PyMuPDF."""
    zoom = max(dpi, 72) / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        total_pages = doc.page_count
        if total_pages == 0:
            return []

        start, end = _resolve_page_bounds(total_pages, first_page, last_page)
        total_requested = end - start + 1

        colorspace = None
        if not color:
            colorspace = getattr(fitz, "csGRAY", None)

        result: List[Tuple[str, bytes]] = []
        for idx, page_index in enumerate(range(start - 1, end), start=1):
            page = doc.load_page(page_index)
            if colorspace is not None:
                pix = page.get_pixmap(matrix=matrix, colorspace=colorspace, alpha=False)
            else:
                pix = page.get_pixmap(matrix=matrix, alpha=False)
            filename = f"{base_name}-{idx:03d}.png" if total_requested > 1 else f"{base_name}.png"
            result.append((filename, pix.tobytes("png")))

        return result
