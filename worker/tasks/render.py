from celery import shared_task
import fitz, io
from PIL import Image
from tasks.watermark import apply_tiled_watermark

@shared_task
def render_pdf_to_jpeg_300dpi(pdf_bytes: bytes, watermark_text: str = "CONFIDENTIAL") -> bytes:
    # Рендер только первой страницы (MVP)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(dpi=300, alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")

    img = apply_tiled_watermark(img, text=watermark_text, opacity=32, step=320, angle=-30)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90, optimize=True)
    out.seek(0)
    return out.read()
