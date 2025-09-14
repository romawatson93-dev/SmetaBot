from PIL import Image, ImageDraw, ImageFont


def _load_font(preferred: str, fallback: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        preferred,
        "/usr/share/fonts/truetype/roboto/Roboto-Regular.ttf",
        fallback,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def apply_tiled_watermark(
    img: Image.Image,
    text: str,
    opacity: int = 56,
    step: int = 280,
    angle: int = -30,
    color=(0, 0, 0),
    font_preferred: str = "Roboto-Regular.ttf",
    font_fallback: str = "DejaVuSans.ttf",
) -> Image.Image:
    """Apply tiled watermark. Skips if text is empty.

    - Uses dark semi-transparent text for visibility on light backgrounds
    - Attempts to use Roboto (Cyrillic), falls back to DejaVuSans
    - Step and font size scale with image width
    """
    if not text or not str(text).strip():
        return img if img.mode == "RGB" else img.convert("RGB")

    W, H = img.size
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # Увеличил размер ~ в 3 раза относительно раннего варианта
    # Reduce size to ~0.10 of width for readability
    font_size = max(18, int(W * 0.10))
    font = _load_font(font_preferred, font_fallback, font_size)

    tile_w, tile_h = int(W * 0.5), int(H * 0.22)
    tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(tile)
    bbox = d2.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    rgba = (*color, max(16, min(255, opacity)))
    d2.text(((tile_w - tw)//2, (tile_h - th)//2), text, font=font, fill=rgba)
    tile = tile.rotate(angle, expand=True)

    for y in range(-tile.height, H + tile.height, step):
        for x in range(-tile.width, W + tile.width, step):
            overlay.alpha_composite(tile, dest=(x, y))

    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
