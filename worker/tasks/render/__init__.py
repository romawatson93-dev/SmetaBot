from __future__ import annotations

import base64
import io
import mimetypes
import re
from pathlib import Path
from typing import List, Tuple

from celery import shared_task
from PIL import Image

from ..publish import send_document
from tasks.watermark import apply_tiled_watermark

from .doc_to_png import convert as convert_doc_to_png
from .pdf_to_png import convert as convert_pdf_to_png
from .xls_to_png import convert as convert_xls_to_png

PDF_MIME_TYPES = {"application/pdf"}
DOC_MIME_TYPES = {
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
XLS_MIME_TYPES = {
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroenabled.12",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.spreadsheet-template",
}

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_basename(filename: str, default: str) -> str:
    base = Path(filename).stem or default
    sanitized = _SANITIZE_RE.sub("_", base)
    return sanitized[:48] or default


def _guess_mime(filename: str, provided: str | None) -> str:
    if provided:
        return provided.lower()
    guess, _ = mimetypes.guess_type(filename)
    if guess:
        return guess.lower()
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".doc", ".dot"}:
        return "application/msword"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix in {".xls", ".xlt"}:
        return "application/vnd.ms-excel"
    if suffix in {".xlsx", ".xlsm"}:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if suffix in {".ods", ".fods"}:
        return "application/vnd.oasis.opendocument.spreadsheet"
    return ""


def render_to_png(file_bytes: bytes, filename: str, mime_type: str | None) -> List[Tuple[str, bytes]]:
    """Render supported office documents to PNG images."""
    mime = _guess_mime(filename, mime_type)
    suffix = Path(filename).suffix.lower()

    if mime in PDF_MIME_TYPES:
        base_name = _sanitize_basename(filename, "page")
        return convert_pdf_to_png(file_bytes, base_name=base_name)

    if mime in DOC_MIME_TYPES:
        suffix = suffix if suffix in {".doc", ".docx"} else ".docx"
        base_name = _sanitize_basename(filename, "document")
        return convert_doc_to_png(file_bytes, base_name=base_name, suffix=suffix)

    if mime in XLS_MIME_TYPES:
        suffix = suffix if suffix in {".xls", ".xlsx", ".xlsm", ".ods", ".fods"} else ".xlsx"
        base_name = _sanitize_basename(filename, "sheet")
        return convert_xls_to_png(file_bytes, base_name=base_name, suffix=suffix)

    raise RuntimeError(f"Неподдерживаемый MIME-тип для конвертации в PNG: {mime or 'неизвестно'}")


def _apply_watermark(png_bytes: bytes, watermark_text: str | None) -> bytes:
    if not watermark_text or not str(watermark_text).strip():
        return png_bytes
    with Image.open(io.BytesIO(png_bytes)).convert("RGB") as img:
        stamped = apply_tiled_watermark(img, text=str(watermark_text), opacity=56, step=280, angle=-30)
        out = io.BytesIO()
        stamped.save(out, format="PNG", optimize=True)
        return out.getvalue()


def _decode_b64(data_b64: str) -> bytes:
    try:
        return base64.b64decode(data_b64)
    except Exception as exc:  # pragma: no cover - защитный слой
        raise RuntimeError(f"Не удалось декодировать файл из Base64: {exc}") from exc


def _send_png(chat_id: int, filename: str, payload: bytes) -> bool:
    return bool(send_document.run(chat_id, payload, filename, caption=""))


@shared_task
def render_pdf_to_png_300dpi(pdf_bytes: bytes, watermark_text: str | None = None) -> bytes:
    """Render the first PDF page to PNG (300 DPI)."""
    pages = render_to_png(pdf_bytes, filename="document.pdf", mime_type="application/pdf")
    if not pages:
        raise RuntimeError("PDF не содержит страниц.")
    _, first_page = pages[0]
    return _apply_watermark(first_page, watermark_text)


@shared_task
def render_pdf_to_jpeg_300dpi(pdf_bytes: bytes, watermark_text: str | None = None) -> bytes:
    """Compatibility wrapper that delegates to the PNG renderer."""
    return render_pdf_to_png_300dpi(pdf_bytes, watermark_text)


@shared_task
def process_and_publish_pdf(
    chat_id: int,
    pdf_b64: str,
    watermark_text: str | None = None,
    filename: str = "smeta.png",
) -> bool:
    """Decode a PDF, render the first page to PNG and post it to Telegram."""
    try:
        pdf_bytes = _decode_b64(pdf_b64)
        pages = render_to_png(pdf_bytes, filename=filename or "document.pdf", mime_type="application/pdf")
        if not pages:
            raise RuntimeError("PDF не содержит страниц.")

        name, png_bytes = pages[0]
        payload = _apply_watermark(png_bytes, watermark_text)
        return _send_png(chat_id, name, payload)
    except Exception as exc:
        print("Ошибка process_and_publish_pdf:", exc)
        return False


@shared_task
def process_and_publish_png(
    chat_id: int,
    png_b64: str,
    watermark_text: str | None = None,
    filename: str = "smeta.png",
    apply_watermark: bool = True,
) -> bool:
    """Send an existing PNG file to Telegram, optionally applying a watermark."""
    try:
        png_bytes = _decode_b64(png_b64)
        payload = png_bytes

        if apply_watermark and watermark_text and str(watermark_text).strip():
            with Image.open(io.BytesIO(png_bytes)).convert("RGB") as img:
                stamped = apply_tiled_watermark(img, text=watermark_text, opacity=56, step=280, angle=-30)
                out = io.BytesIO()
                stamped.save(out, format="PNG", optimize=True, dpi=(300, 300))
                payload = out.getvalue()
        else:
            try:
                with Image.open(io.BytesIO(png_bytes)) as img:
                    out = io.BytesIO()
                    img.save(out, format="PNG", optimize=True, dpi=(300, 300))
                    payload = out.getvalue()
            except Exception:
                payload = png_bytes

        return _send_png(chat_id, filename, payload)
    except Exception as exc:
        print("Ошибка process_and_publish_png:", exc)
        return False


@shared_task
def process_and_publish_doc(
    chat_id: int,
    doc_b64: str,
    watermark_text: str | None = None,
    filename: str = "document.docx",
) -> bool:
    """Convert DOC/DOCX to PNG pages and post them to Telegram."""
    try:
        doc_bytes = _decode_b64(doc_b64)
        pages = render_to_png(doc_bytes, filename=filename, mime_type=None)
        if not pages:
            raise RuntimeError("Документ не содержит страниц.")

        ok = True
        for name, png_bytes in pages:
            payload = _apply_watermark(png_bytes, watermark_text)
            if not _send_png(chat_id, name, payload):
                ok = False
        return ok
    except Exception as exc:
        print("Ошибка process_and_publish_doc:", exc)
        return False


@shared_task
def process_and_publish_excel(
    chat_id: int,
    excel_b64: str,
    watermark_text: str | None = None,
    filename: str = "document.xlsx",
) -> bool:
    """Convert spreadsheet documents to PNG pages and post them to Telegram."""
    try:
        excel_bytes = _decode_b64(excel_b64)
        pages = render_to_png(excel_bytes, filename=filename, mime_type=None)
        if not pages:
            raise RuntimeError("Табличный документ не содержит страниц после рендеринга.")

        ok = True
        for name, png_bytes in pages:
            payload = _apply_watermark(png_bytes, watermark_text)
            if not _send_png(chat_id, name, payload):
                ok = False
        return ok
    except Exception as exc:
        print("Ошибка process_and_publish_excel:", exc)
        return False
