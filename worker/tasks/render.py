from celery import shared_task
import fitz, io
from PIL import Image
from tasks.watermark import apply_tiled_watermark
from .publish import send_document

@shared_task
def render_pdf_to_png_300dpi(pdf_bytes: bytes, watermark_text: str | None = None) -> bytes:
    """Render first PDF page to PNG 300 DPI and apply tiled watermark.

    Returns PNG bytes.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(dpi=300, alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")

    if watermark_text and str(watermark_text).strip():
        img = apply_tiled_watermark(img, text=watermark_text, opacity=56, step=280, angle=-30)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    out.seek(0)
    return out.read()

# Backward-compat alias
@shared_task
def render_pdf_to_jpeg_300dpi(pdf_bytes: bytes, watermark_text: str | None = None) -> bytes:
    return render_pdf_to_png_300dpi(pdf_bytes, watermark_text)

@shared_task
def process_and_publish_pdf(chat_id: int, pdf_b64: str, watermark_text: str | None = None, filename: str = "smeta.png") -> bool:
    """Accept base64 PDF, render PNG 300DPI with watermark, and send to Telegram."""
    import base64
    try:
        pdf_bytes = base64.b64decode(pdf_b64)
        png = render_pdf_to_png_300dpi(pdf_bytes, watermark_text)
        # Execute publish synchronously in this worker process to avoid the need for result backend
        return bool(send_document.run(chat_id, png, filename, caption=""))
    except Exception as e:
        print("process_and_publish_pdf error:", e)
        return False
