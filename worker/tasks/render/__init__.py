from __future__ import annotations

import base64
import io
import mimetypes
import os
import re
import traceback
from pathlib import Path
from typing import List, Optional, Tuple

import redis
from celery import shared_task

from common.watermark import WATERMARK_SETTINGS, WatermarkSettings
from PIL import Image

from ..publish import send_document
from bot.services import channels as channels_service
from bot.services import db as db_service
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

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
_storage = redis.Redis.from_url(REDIS_URL)


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

    raise RuntimeError(f"Unsupported MIME type for PNG conversion: {mime or 'unknown'}")


def _apply_watermark(
    png_bytes: bytes,
    watermark_text: str | None,
    *,
    settings: WatermarkSettings | None = None,
) -> bytes:
    if not watermark_text or not str(watermark_text).strip():
        return png_bytes
    with Image.open(io.BytesIO(png_bytes)).convert("RGB") as img:
        stamped = apply_tiled_watermark(
            img,
            text=str(watermark_text),
            settings=settings or WATERMARK_SETTINGS,
        )
        out = io.BytesIO()
        stamped.save(out, format="PNG", optimize=True)
        return out.getvalue()


def _decode_b64(data_b64: str) -> bytes:
    try:
        return base64.b64decode(data_b64)
    except Exception as exc:  # pragma: no cover - invalid input
        raise RuntimeError(f"Failed to decode Base64 payload: {exc}") from exc


def _send_png(chat_id: int, filename: str, payload: bytes) -> dict[str, object] | None:
    response = send_document.run(chat_id, payload, filename, caption="")
    if isinstance(response, dict) and response.get("ok"):
        return response.get("result")
    return None


async def _record_publication_async(
    chat_id: int,
    filename: str,
    message_payload: dict[str, object],
    source_document_id: int | None = None,
) -> None:
    """Записывает публикацию в core.publications и событие в analytics.events."""
    await db_service.init_pool()
    try:
        # Прямой импорт для избежания циклических зависимостей
        from bot.services.events import log_file_posted
        
        document = message_payload.get("document") if isinstance(message_payload, dict) else None
        message_id = int(message_payload.get("message_id", 0))
        
        mime_type = None
        if document and isinstance(document, dict):
            mime_type_val = document.get("mime_type")
            if isinstance(mime_type_val, str):
                mime_type = mime_type_val
        
        try:
            print(f"DEBUG: filename={filename}, mime_type={mime_type}, message_payload keys={list(message_payload.keys()) if message_payload else None}")
            publication_id = await channels_service.record_channel_file(
                channel_id=chat_id,
                message_id=message_id,
                filename=filename,
                file_type=mime_type,
                views=int(message_payload.get("views", 0) or 0),
            )
            channel_db = await db_service.fetchrow(
                "SELECT id FROM core.channels WHERE tg_chat_id = $1",
                chat_id
            )
            if channel_db:
                channel_db_id = channel_db["id"]
                await log_file_posted(
                    channel_id=channel_db_id,
                    message_id=message_id,
                    file_name=filename,
                    file_type=mime_type or "unknown",
                )
        except Exception as exc:
            print(f"Failed to record publication: {exc}")
    finally:
        await db_service.close_pool()


def _record_publication(chat_id: int, filename: str, message_payload: dict[str, object] | None, source_document_id: int | None = None) -> None:
    if not message_payload:
        return
    try:
        import asyncio
        asyncio.run(_record_publication_async(chat_id, filename, message_payload, source_document_id))
    except Exception as exc:  # pragma: no cover - best effort
        print("Failed to record publication metadata:", exc)


def _filter_pages(pages: List[Tuple[str, bytes]], page_indices: List[int] | None) -> List[Tuple[str, bytes]]:
    if not page_indices:
        return pages
    ordered: List[Tuple[str, bytes]] = []
    seen: set[int] = set()
    total = len(pages)
    for idx in page_indices:
        if idx in seen:
            continue
        if idx < 1 or idx > total:
            continue
        ordered.append(pages[idx - 1])
        seen.add(idx)
    return ordered


def _pop_storage_blob(key: str) -> bytes:
    if not key:
        raise RuntimeError("Storage key is empty.")
    try:
        pipe = _storage.pipeline()
        pipe.get(key)
        pipe.delete(key)
        data, _ = pipe.execute()
    except Exception as exc:
        raise RuntimeError(f"Не удалось получить файл из хранилища ({key}): {exc}") from exc
    if data is None:
        raise RuntimeError(f"Файл по ключу {key} не найден или уже был использован.")
    return data


def _resolve_payload(b64_data: Optional[str], storage_key: Optional[str], kind: str) -> bytes:
    if storage_key:
        return _pop_storage_blob(storage_key)
    if b64_data:
        return _decode_b64(b64_data)
    raise RuntimeError(f"Не передан файл для {kind}.")


@shared_task
def render_pdf_to_png_300dpi(pdf_bytes: bytes, watermark_text: str | None = None) -> bytes:
    """Render the first PDF page to PNG (300 DPI)."""
    pages = render_to_png(pdf_bytes, filename="document.pdf", mime_type="application/pdf")
    if not pages:
        raise RuntimeError("PDF has no pages.")
    _, first_page = pages[0]
    return _apply_watermark(first_page, watermark_text)


@shared_task
def render_pdf_to_jpeg_300dpi(pdf_bytes: bytes, watermark_text: str | None = None) -> bytes:
    """Compatibility wrapper that delegates to the PNG renderer."""
    return render_pdf_to_png_300dpi(pdf_bytes, watermark_text)


@shared_task
def process_and_publish_pdf(
    chat_id: int,
    pdf_b64: Optional[str] = None,
    pdf_key: Optional[str] = None,
    watermark_text: str | None = None,
    filename: str = "smeta.pdf",
    page_indices: List[int] | None = None,
) -> bool:
    """Decode a PDF, render selected pages to PNG and post them to Telegram."""
    try:
        pdf_bytes = _resolve_payload(pdf_b64, pdf_key, "PDF")
        pages = render_to_png(pdf_bytes, filename=filename or "document.pdf", mime_type="application/pdf")
        if not pages:
            raise RuntimeError("PDF has no pages.")

        selected = _filter_pages(pages, page_indices) or [pages[0]]

        ok = True
        for name, png_bytes in selected:
            payload = _apply_watermark(png_bytes, watermark_text)
            message_payload = _send_png(chat_id, name, payload)
            if not message_payload:
                ok = False
            else:
                _record_publication(chat_id, name, message_payload)
        return ok
    except Exception as exc:
        print("Error in process_and_publish_pdf:", exc)
        traceback.print_exc()
        return False


@shared_task
def process_and_publish_png(
    chat_id: int,
    png_b64: Optional[str] = None,
    png_key: Optional[str] = None,
    watermark_text: str | None = None,
    filename: str = "smeta.png",
    apply_watermark: bool = True,
) -> bool:
    """Send an existing PNG file to Telegram, optionally applying a watermark."""
    try:
        png_bytes = _resolve_payload(png_b64, png_key, "PNG")
        payload = png_bytes

        if apply_watermark and watermark_text and str(watermark_text).strip():
            with Image.open(io.BytesIO(png_bytes)).convert("RGB") as img:
                stamped = apply_tiled_watermark(
                    img,
                    text=watermark_text,
                    settings=WATERMARK_SETTINGS,
                )
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

        message_payload = _send_png(chat_id, filename, payload)
        if message_payload:
            _record_publication(chat_id, filename, message_payload)
            return True
        return False
    except Exception as exc:
        print("Error in process_and_publish_png:", exc)
        traceback.print_exc()
        return False


@shared_task
def process_and_publish_doc(
    chat_id: int,
    doc_b64: Optional[str] = None,
    doc_key: Optional[str] = None,
    watermark_text: str | None = None,
    filename: str = "document.docx",
    page_indices: List[int] | None = None,
) -> bool:
    """Convert DOC/DOCX to PNG pages and post them to Telegram."""
    try:
        doc_bytes = _resolve_payload(doc_b64, doc_key, "DOC")
        pages = render_to_png(doc_bytes, filename=filename, mime_type=None)
        if not pages:
            raise RuntimeError("Document has no pages.")

        selected = _filter_pages(pages, page_indices) or pages

        ok = True
        for name, png_bytes in selected:
            payload = _apply_watermark(png_bytes, watermark_text)
            message_payload = _send_png(chat_id, name, payload)
            if not message_payload:
                ok = False
            else:
                _record_publication(chat_id, name, message_payload)
        return ok
    except Exception as exc:
        print("Error in process_and_publish_doc:", exc)
        traceback.print_exc()
        return False


@shared_task
def process_and_publish_excel(
    chat_id: int,
    excel_b64: Optional[str] = None,
    excel_key: Optional[str] = None,
    watermark_text: str | None = None,
    filename: str = "document.xlsx",
    page_indices: List[int] | None = None,
) -> bool:
    """Convert spreadsheet documents to PNG pages and post them to Telegram."""
    try:
        excel_bytes = _resolve_payload(excel_b64, excel_key, "Excel")
        pages = render_to_png(excel_bytes, filename=filename, mime_type=None)
        if not pages:
            raise RuntimeError("Spreadsheet has no pages to export.")

        selected = _filter_pages(pages, page_indices) or pages

        ok = True
        for name, png_bytes in selected:
            payload = _apply_watermark(png_bytes, watermark_text)
            message_payload = _send_png(chat_id, name, payload)
            if not message_payload:
                ok = False
            else:
                _record_publication(chat_id, name, message_payload)
        return ok
    except Exception as exc:
        print("Error in process_and_publish_excel:", exc)
        traceback.print_exc()
        return False
