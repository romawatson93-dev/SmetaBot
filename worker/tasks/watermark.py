from __future__ import annotations

from threading import Lock
from typing import Dict, Tuple

from PIL import Image, ImageDraw, ImageFont

from common.watermark import WATERMARK_SETTINGS, WatermarkSettings

_MAX_TILE_CACHE = 32
_TILE_CACHE: Dict[Tuple[str, Tuple[str, str], int, int, int, Tuple[int, int, int], int, int, int], Image.Image] = {}
_TILE_CACHE_LOCK = Lock()


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


def _cache_key(
    text: str,
    font: ImageFont.FreeTypeFont,
    cfg: WatermarkSettings,
    tile_w: int,
    tile_h: int,
) -> Tuple[str, Tuple[str, str], int, int, int, Tuple[int, int, int], int, int, int]:
    font_name = font.getname()
    font_size = getattr(font, "size", 0)
    return (
        text,
        font_name,
        font_size,
        tile_w,
        tile_h,
        cfg.color,
        cfg.opacity,
        cfg.angle,
        cfg.text_offset,
    )


def _get_rotated_tile(
    text: str,
    font: ImageFont.FreeTypeFont,
    cfg: WatermarkSettings,
    tile_w: int,
    tile_h: int,
) -> Image.Image:
    key = _cache_key(text, font, cfg, tile_w, tile_h)
    with _TILE_CACHE_LOCK:
        cached = _TILE_CACHE.get(key)
        if cached is not None:
            return cached

    tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    drawer = ImageDraw.Draw(tile)
    bbox = drawer.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    rgba = (*cfg.color, max(16, min(255, cfg.opacity)))
    if cfg.text_offset < 0:
        pos_x = (tile_w - tw) // 2
        pos_y = (tile_h - th) // 2
    else:
        pos_x = cfg.text_offset
        pos_y = cfg.text_offset
    drawer.text((pos_x, pos_y), text, font=font, fill=rgba)
    rotated = tile.rotate(cfg.angle, expand=True)

    with _TILE_CACHE_LOCK:
        if len(_TILE_CACHE) >= _MAX_TILE_CACHE:
            _TILE_CACHE.pop(next(iter(_TILE_CACHE)))
        _TILE_CACHE[key] = rotated
    return rotated


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
    tile = _get_rotated_tile(text, font, cfg, tile_w, tile_h)
    base_step = max(1, cfg.step)
    step_x = max(base_step, tile.width // 2)
    step_y = max(base_step, tile.height // 2)

    for y in range(-tile.height, H + tile.height, step_y):
        for x in range(-tile.width, W + tile.width, step_x):
            overlay.alpha_composite(tile, dest=(x, y))

    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
