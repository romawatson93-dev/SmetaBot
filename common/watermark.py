from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Tuple


@dataclass(frozen=True)
class WatermarkSettings:
    """Configuration values used to render a tiled watermark."""

    opacity: int = 63
    step: int = 350
    angle: int = -25
    color: Tuple[int, int, int] = (60, 60, 60)
    font_preferred: str = "Roboto-Regular.ttf"
    font_fallback: str = "DejaVuSans.ttf"
    font_scale: float = 0.03
    min_font_size: int = 18
    tile_scale_x: float = 0.6
    tile_scale_y: float = 0.25
    text_offset: int = -1


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _tuple_env(name: str, default: Tuple[int, int, int]) -> Tuple[int, int, int]:
    raw = os.getenv(name, "")
    if not raw:
        return default
    try:
        parts = [int(part.strip()) for part in raw.split(",")]
    except ValueError:
        return default
    while len(parts) < 3:
        parts.append(default[len(parts)])
    return tuple(max(0, min(255, value)) for value in parts[:3])  # type: ignore[return-value]


def load_watermark_settings() -> WatermarkSettings:
    """Read watermark settings from environment or fall back to defaults."""
    defaults = WatermarkSettings()
    return WatermarkSettings(
        opacity=_int_env("WATERMARK_OPACITY", defaults.opacity),
        step=_int_env("WATERMARK_STEP", defaults.step),
        angle=_int_env("WATERMARK_ANGLE", defaults.angle),
        color=_tuple_env("WATERMARK_COLOR", defaults.color),
        font_preferred=os.getenv("WATERMARK_FONT_PREFERRED", defaults.font_preferred),
        font_fallback=os.getenv("WATERMARK_FONT_FALLBACK", defaults.font_fallback),
        font_scale=_float_env("WATERMARK_FONT_SCALE", defaults.font_scale),
        min_font_size=_int_env("WATERMARK_MIN_FONT_SIZE", defaults.min_font_size),
        tile_scale_x=_float_env("WATERMARK_TILE_SCALE_X", defaults.tile_scale_x),
        tile_scale_y=_float_env("WATERMARK_TILE_SCALE_Y", defaults.tile_scale_y),
        text_offset=_int_env("WATERMARK_TEXT_OFFSET", defaults.text_offset),
    )


WATERMARK_SETTINGS = load_watermark_settings()


__all__ = ["WatermarkSettings", "WATERMARK_SETTINGS", "load_watermark_settings"]
