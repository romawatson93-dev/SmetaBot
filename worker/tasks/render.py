from __future__ import annotations



import base64

import io

import os

import re

import subprocess
import shutil

import tempfile

from pathlib import Path

from typing import List, Tuple



import fitz

from celery import shared_task

from PIL import Image



from tasks.watermark import apply_tiled_watermark

from .publish import send_document



_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_OFFICE_TO_PDF_CANDIDATES = [
    "officetopdf",
    "OfficeToPDF",
    "OfficeToPDF.exe",
]





def _sanitize_basename(name: str, default: str = "page") -> str:

    base = os.path.splitext(name)[0] or default

    base = _SANITIZE_RE.sub("_", base)

    return base[:48] or default





def _pdf_to_png_pages(

    pdf_bytes: bytes,

    watermark_text: str | None,

    base_name: str,

) -> List[Tuple[str, bytes]]:

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    pages: List[Tuple[str, bytes]] = []

    try:

        total = doc.page_count

        for idx, page in enumerate(doc, start=1):

            pix = page.get_pixmap(dpi=300, alpha=False)

            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")

            if watermark_text and str(watermark_text).strip():

                img = apply_tiled_watermark(img, text=watermark_text, opacity=56, step=280, angle=-30)

            out = io.BytesIO()

            img.save(out, format="PNG", optimize=True)

            name = f"{base_name}-{idx:02}.png" if total > 1 else f"{base_name}.png"

            pages.append((name, out.getvalue()))

    finally:

        doc.close()

    return pages





def _find_office_to_pdf() -> str | None:
    for name in _OFFICE_TO_PDF_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


def _office_to_pdf(src_path: Path, out_path: Path) -> bool:
    binary = _find_office_to_pdf()
    if not binary:
        return False
    cmd = [binary, str(src_path), str(out_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=240)
    except Exception as exc:
        print(f"OfficeToPDF invocation failed: {exc}")
        return False
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="ignore") if proc.stderr else ""
        stdout = proc.stdout.decode(errors="ignore") if proc.stdout else ""
        print(f"OfficeToPDF non-zero exit ({proc.returncode}): {stderr or stdout}")
        return False
    if not out_path.exists():
        print("OfficeToPDF did not create output file.")
        return False
    return True


def _doc_to_pdf_bytes(doc_bytes: bytes, suffix: str) -> bytes:

    suffix = suffix.lower()

    if suffix not in {".doc", ".docx"}:

        raise ValueError("Only DOC and DOCX documents are supported.")

    try:

        with tempfile.TemporaryDirectory() as tmpdir:

            tmp_path = Path(tmpdir)

            src_path = tmp_path / f"source{suffix}"

            src_path.write_bytes(doc_bytes)

            out_path = tmp_path / "output.pdf"

            if _office_to_pdf(src_path, out_path):
                return out_path.read_bytes()

            binary = shutil.which("libreoffice") or shutil.which("soffice")

            if not binary:

                raise RuntimeError("LibreOffice binary not found in PATH.")

            cmd = [
                binary,
                "--headless",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                "--norestore",
                "--convert-to",
                "pdf:writer_pdf_Export:EmbedStandardFonts=true;UseLosslessCompression=true;SelectPdfVersion=1;UseUserPageSize=true",
                "--outdir",
                str(tmp_path),
                str(src_path),
            ]
            env = os.environ.copy()
            env.setdefault("HOME", str(tmp_path))
            env.setdefault("TMPDIR", str(tmp_path))
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=240,
                cwd=tmp_path,
                env=env,
            )
            if proc.returncode != 0:
                stderr = proc.stderr.decode(errors="ignore") or proc.stdout.decode(errors="ignore")
                raise RuntimeError(f"LibreOffice failed to convert DOC/DOCX: {stderr}")
            pdf_path = src_path.with_suffix(".pdf")
            if not pdf_path.exists():
                candidates = list(tmp_path.glob("*.pdf"))
                if not candidates:
                    raise RuntimeError("LibreOffice did not produce a PDF file.")
                pdf_path = candidates[0]
            return pdf_path.read_bytes()

    except FileNotFoundError as exc:

        raise RuntimeError("LibreOffice binary not found.") from exc

    except subprocess.TimeoutExpired as exc:

        raise RuntimeError("LibreOffice timed out during conversion.") from exc


def _doc_to_png_pages(
    doc_bytes: bytes,
    suffix: str,
    base_name: str,
    *,
    color: bool = False,
    persist_pdf: bool = True,
) -> List[Tuple[str, bytes]]:
    pdf_bytes = _doc_to_pdf_bytes(doc_bytes, suffix)

    if persist_pdf:
        try:
            out_dir = Path("/app/out")
            out_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = out_dir / f"{base_name}.pdf"
            pdf_path.write_bytes(pdf_bytes)
        except Exception as exc:
            print(f"Failed to persist intermediate PDF: {exc}")

    return _pdf_to_png_via_gs(pdf_bytes, base_name, color=color)


def _pdf_to_png_via_gs(
    pdf_bytes: bytes,
    base_name: str,
    *,
    color: bool = False,
) -> List[Tuple[str, bytes]]:
    device = "png16m" if color else "pnggray"
    safe_base = _sanitize_basename(base_name, "page")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        pdf_path = tmp_path / "source.pdf"
        pdf_path.write_bytes(pdf_bytes)

        output_pattern = tmp_path / f"{safe_base}-%03d.png"
        cmd = [
            "gs",
            "-dSAFER",
            "-dBATCH",
            "-dNOPAUSE",
            "-dQUIET",
            f"-sDEVICE={device}",
            "-r300",
            "-dUseCropBox",
            f"-sOutputFile={output_pattern}",
            str(pdf_path),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=240,
            cwd=tmp_path,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode(errors="ignore") or proc.stdout.decode(errors="ignore")
            raise RuntimeError(f"Ghostscript failed to render PDF: {stderr}")

        png_paths = sorted(tmp_path.glob(f"{safe_base}-*.png"))
        if not png_paths:
            raise RuntimeError("Ghostscript did not produce any PNG files.")

        total = len(png_paths)
        pages: List[Tuple[str, bytes]] = []
        for idx, path in enumerate(png_paths, start=1):
            final_name = f"{base_name}-{idx:03d}.png" if total > 1 else f"{base_name}.png"
            pages.append((final_name, path.read_bytes()))
        return pages

def _spreadsheet_to_pdf_bytes(sheet_bytes: bytes, suffix: str) -> bytes:

    suffix = suffix.lower()

    allowed = {".xls", ".xlsx", ".xlsm", ".ods", ".fods"}

    if suffix not in allowed:

        raise ValueError("Only Excel/ODS spreadsheets (.xls, .xlsx, .xlsm, .ods, .fods) are supported.")

    try:

        with tempfile.TemporaryDirectory() as tmpdir:

            tmp_path = Path(tmpdir)

            src_path = tmp_path / f"source{suffix}"

            src_path.write_bytes(sheet_bytes)

            binary = shutil.which("libreoffice") or shutil.which("soffice")

            if not binary:

                raise RuntimeError("LibreOffice binary not found in PATH.")

            cmd = [

                binary,

                "--headless",

                "--nologo",

                "--nodefault",

                "--nofirststartwizard",

                "--norestore",

                "--convert-to",

                "pdf",

                "--outdir",

                str(tmp_path),

                str(src_path),

            ]

            env = os.environ.copy()

            env.setdefault("HOME", str(tmp_path))

            env.setdefault("TMPDIR", str(tmp_path))

            proc = subprocess.run(

                cmd,

                capture_output=True,

                timeout=240,

                cwd=tmp_path,

                env=env,

            )

            if proc.returncode != 0:

                stderr = proc.stderr.decode(errors="ignore") or proc.stdout.decode(errors="ignore")

                raise RuntimeError(f"LibreOffice failed to convert spreadsheet: {stderr}")

            pdf_path = src_path.with_suffix(".pdf")

            if not pdf_path.exists():

                candidates = list(tmp_path.glob("*.pdf"))

                if not candidates:

                    raise RuntimeError("LibreOffice did not produce a PDF file.")

                pdf_path = candidates[0]

            return pdf_path.read_bytes()

    except FileNotFoundError as exc:

        raise RuntimeError("LibreOffice binary not found.") from exc

    except subprocess.TimeoutExpired as exc:

        raise RuntimeError("LibreOffice timed out during spreadsheet conversion.") from exc


@shared_task

def render_pdf_to_png_300dpi(pdf_bytes: bytes, watermark_text: str | None = None) -> bytes:

    """Render first PDF page to PNG 300 DPI and apply tiled watermark."""

    pages = _pdf_to_png_pages(pdf_bytes, watermark_text, base_name="page")

    if not pages:

        raise RuntimeError("PDF не содержит страниц.")

    return pages[0][1]





@shared_task

def render_pdf_to_jpeg_300dpi(pdf_bytes: bytes, watermark_text: str | None = None) -> bytes:

    return render_pdf_to_png_300dpi(pdf_bytes, watermark_text)





@shared_task

def process_and_publish_pdf(

    chat_id: int,

    pdf_b64: str,

    watermark_text: str | None = None,

    filename: str = "smeta.png",

) -> bool:

    """Accept base64 PDF, render an image, and send to Telegram."""

    try:

        pdf_bytes = base64.b64decode(pdf_b64)

        base_name = Path(filename).stem or "page"

        pages = _pdf_to_png_pages(pdf_bytes, watermark_text, base_name)

        if not pages:

            raise RuntimeError("PDF не содержит страниц.")

        name, png = pages[0]

        return bool(send_document.run(chat_id, png, name, caption=""))

    except Exception as exc:

        print("process_and_publish_pdf error:", exc)

        return False





@shared_task

def process_and_publish_doc(

    chat_id: int,

    doc_b64: str,

    watermark_text: str | None = None,

    filename: str = "document.docx",

) -> bool:

    """Convert DOC/DOCX to PNG pages and send them to Telegram."""

    try:

        doc_bytes = base64.b64decode(doc_b64)

        suffix = Path(filename).suffix or ".docx"

        base_name = Path(filename).stem or "page"

        pages = _doc_to_png_pages(doc_bytes, suffix, base_name)

        if not pages:

            raise RuntimeError("Документ не содержит страниц.")

        ok = True

        for name, png_bytes in pages:

            payload = png_bytes

            if watermark_text and str(watermark_text).strip():

                with Image.open(io.BytesIO(png_bytes)).convert("RGB") as img:

                    stamped = apply_tiled_watermark(img, text=watermark_text, opacity=56, step=280, angle=-30)

                    out = io.BytesIO()

                    stamped.save(out, format="PNG", optimize=True)

                    payload = out.getvalue()

            if not send_document.run(chat_id, payload, name, caption=""):

                ok = False

        return ok

    except Exception as exc:

        print("process_and_publish_doc error:", exc)

        return False



@shared_task

def process_and_publish_excel(

    chat_id: int,

    excel_b64: str,

    watermark_text: str | None = None,

    filename: str = "document.xlsx",

) -> bool:

    """Convert Excel-like spreadsheets to PNG pages and send them to Telegram."""

    try:

        excel_bytes = base64.b64decode(excel_b64)

        suffix = Path(filename).suffix or ".xlsx"

        pdf_bytes = _spreadsheet_to_pdf_bytes(excel_bytes, suffix)

        base_name = _sanitize_basename(filename, "sheet")

        pages = _pdf_to_png_pages(pdf_bytes, watermark_text, base_name)

        if not pages:

            raise RuntimeError("Spreadsheet conversion resulted in no pages.")

        ok = True

        for name, png in pages:

            if not send_document.run(chat_id, png, name, caption=""):

                ok = False

        return ok

    except Exception as exc:

        print("process_and_publish_excel error:", exc)

        return False
