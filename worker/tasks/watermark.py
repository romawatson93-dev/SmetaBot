from PIL import Image, ImageDraw, ImageFont

from common.watermark import WATERMARK_SETTINGS, WatermarkSettings


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
    *,
    settings: WatermarkSettings | None = None,
) -> Image.Image:
    """Apply tiled watermark. Skips if text is empty."""
    if not text or not str(text).strip():
        return img if img.mode == "RGB" else img.convert("RGB")

    cfg = settings or WATERMARK_SETTINGS
    W, H = img.size
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    font_size = max(cfg.min_font_size, int(max(W, H) * cfg.font_scale))
    font = _load_font(cfg.font_preferred, cfg.font_fallback, font_size)

    tile_w = max(64, int(W * cfg.tile_scale_x))
    tile_h = max(64, int(H * cfg.tile_scale_y))
    tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(tile)
    bbox = d2.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    rgba = (*cfg.color, max(16, min(255, cfg.opacity)))
    if cfg.text_offset < 0:
        pos_x = (tile_w - tw) // 2
        pos_y = (tile_h - th) // 2
    else:
        pos_x = cfg.text_offset
        pos_y = cfg.text_offset
    d2.text((pos_x, pos_y), text, font=font, fill=rgba)
    tile = tile.rotate(cfg.angle, expand=True)

    base_step = max(1, cfg.step)
    step_x = max(base_step, tile.width // 2)
    step_y = max(base_step, tile.height // 2)

    for y in range(-tile.height, H + tile.height, step_y):
        for x in range(-tile.width, W + tile.width, step_x):
            overlay.alpha_composite(tile, dest=(x, y))

    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
