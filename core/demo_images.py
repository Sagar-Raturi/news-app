"""Generate abstract editorial illustrations for demo articles (no network, no licences)."""

import hashlib
import io
import random

from PIL import Image, ImageDraw, ImageFilter

# Muted, print-like palettes per section: (background, shapes...)
PALETTES = {
    "politics": ("#e9e1d3", "#7a2e1d", "#1f2a44", "#c9a227", "#b4441c"),
    "international": ("#dfe6e4", "#1f4e5f", "#c9a227", "#7d8c7a", "#17140f"),
    "local": ("#ece4d6", "#4f6d3a", "#b4441c", "#2f4858", "#d9a441"),
    "economy": ("#e8e2d0", "#1d3b2a", "#b4441c", "#c9a227", "#3b3731"),
    "society": ("#efe3d8", "#8c3b4a", "#2f4858", "#e0a458", "#5b6e58"),
    "education": ("#e4e6dc", "#264653", "#e9c46a", "#b4441c", "#6d597a"),
    "health": ("#e3ebe6", "#2a6f68", "#d17a5c", "#1f2a44", "#9cb4a8"),
    "science-tech": ("#dde3ea", "#14213d", "#3a6ea5", "#fca311", "#b4441c"),
    "opinion": ("#efe9dd", "#17140f", "#b4441c", "#8a817c", "#c9a227"),
}
DEFAULT_PALETTE = PALETTES["opinion"]


def _rgba(hex_colour, alpha):
    hex_colour = hex_colour.lstrip("#")
    return tuple(int(hex_colour[i : i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def illustration(seed, section_slug, size=(1600, 900)):
    """Return PNG bytes of a deterministic abstract illustration."""
    rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:12], 16))
    bg, *colours = PALETTES.get(section_slug, DEFAULT_PALETTE)
    width, height = size
    base = Image.new("RGBA", size, _rgba(bg, 255))

    # Ledger lines.
    lines = ImageDraw.Draw(base)
    for y in range(0, height, 36):
        lines.line([(0, y), (width, y)], fill=_rgba(colours[-1], 22), width=1)

    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    # Large discs.
    for _ in range(rng.randint(2, 3)):
        r = rng.randint(height // 4, int(height * 0.62))
        cx, cy = rng.randint(0, width), rng.randint(int(height * 0.1), height)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_rgba(rng.choice(colours), rng.randint(150, 220)))

    # Column bars, like a chart rising from the baseline.
    bar_w = rng.randint(40, 80)
    start = rng.randint(0, width // 2)
    colour = rng.choice(colours)
    for i in range(rng.randint(4, 8)):
        h = rng.randint(height // 6, int(height * 0.7))
        x = start + i * (bar_w + 18)
        draw.rectangle([x, height - h, x + bar_w, height], fill=_rgba(colour, 200))

    # Diagonal band.
    y0 = rng.randint(0, height)
    draw.polygon(
        [(0, y0), (width, y0 - rng.randint(150, 450)), (width, y0 - rng.randint(60, 140)), (0, y0 + 90)],
        fill=_rgba(rng.choice(colours), 120),
    )

    # Halftone dot field.
    dot_colour = _rgba(colours[0], 170)
    ox, oy = rng.randint(0, width // 2), rng.randint(0, height // 2)
    for gx in range(14):
        for gy in range(9):
            radius = max(1, 7 - (gx + gy) // 3)
            x, y = ox + gx * 26, oy + gy * 26
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=dot_colour)

    image = Image.alpha_composite(base, layer.filter(ImageFilter.GaussianBlur(0.6))).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=86, optimize=True)
    return buffer.getvalue()
