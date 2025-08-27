from PIL import Image, ImageDraw, ImageFont

def apply_tiled_watermark(img: Image.Image, text: str, opacity: int = 32, step: int = 320, angle: int = -30) -> Image.Image:
    W, H = img.size
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", max(16, int(W * 0.04)))
    except Exception:
        font = ImageFont.load_default()

    # Создаём тайл
    tile_w, tile_h = int(W * 0.5), int(H * 0.2)
    tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(tile)
    tw, th = d2.textbbox((0, 0), text, font=font)[2:]
    d2.text(((tile_w - tw)//2, (tile_h - th)//2), text, font=font, fill=(255, 255, 255, opacity))
    tile = tile.rotate(angle, expand=True)

    for y in range(-tile.height, H + tile.height, step):
        for x in range(-tile.width, W + tile.width, step):
            overlay.alpha_composite(tile, dest=(x, y))

    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
