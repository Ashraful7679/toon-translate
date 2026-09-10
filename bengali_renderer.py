"""Isolated Bengali text shaping/rendering helper.

Uses HarfBuzz for OpenType shaping and FreeType for glyph rasterization.
This intentionally does not modify Pillow's global text pipeline.
"""
from functools import lru_cache

from PIL import Image, ImageDraw

try:
    import uharfbuzz as hb
    import freetype
    _AVAILABLE = True
except Exception as exc:  # pragma: no cover - deployment fallback
    hb = None
    freetype = None
    _AVAILABLE = False
    _IMPORT_ERROR = exc


def _font_path(font):
    path = getattr(font, "path", None)
    if not path:
        raise ValueError("A TrueType/OpenType font with a file path is required")
    return path


@lru_cache(maxsize=16)
def _font_data(path):
    with open(path, "rb") as f:
        return f.read()


def _shape(text, path, size):
    if not _AVAILABLE:
        raise RuntimeError(f"Bengali shaping dependencies unavailable: {_IMPORT_ERROR}")
    data = _font_data(path)
    face = hb.Face(data)
    font = hb.Font(face)
    scale = int(size * 64)
    font.scale = (scale, scale)
    hb.ot_font_set_funcs(font)

    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": True, "liga": True, "clig": True})
    return buf.glyph_infos, buf.glyph_positions


def text_width(text, font):
    """Return shaped advance width in pixels."""
    if not text:
        return 0.0
    path = _font_path(font)
    size = int(getattr(font, "size", 16))
    _, positions = _shape(text, path, size)
    return sum(p.x_advance for p in positions) / 64.0


def _glyph_mask(face):
    bitmap = face.glyph.bitmap
    width, rows = int(bitmap.width), int(bitmap.rows)
    if width <= 0 or rows <= 0:
        return None
    pitch = int(bitmap.pitch)
    raw = bytes(bitmap.buffer)
    stride = abs(pitch)
    if stride == width:
        return Image.frombytes("L", (width, rows), raw[: width * rows])
    rows_data = []
    for row in range(rows):
        start = row * stride
        rows_data.append(raw[start:start + width])
    if pitch < 0:
        rows_data.reverse()
    return Image.frombytes("L", (width, rows), b"".join(rows_data))


def draw_shaped_line(draw, xy, text, font, fill="black"):
    """Draw one HarfBuzz-shaped line onto a Pillow ImageDraw object."""
    if not text:
        return
    path = _font_path(font)
    size = int(getattr(font, "size", 16))
    infos, positions = _shape(text, path, size)
    face = freetype.Face(path)
    face.set_pixel_sizes(0, size)
    baseline = float(xy[1]) + float(face.size.ascender) / 64.0
    pen_x = float(xy[0])

    for info, pos in zip(infos, positions):
        gid = int(info.codepoint)
        face.load_glyph(gid, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL)
        glyph = face.glyph
        mask = _glyph_mask(face)
        if mask is not None:
            gx = int(round(pen_x + pos.x_offset / 64.0 + glyph.bitmap_left))
            gy = int(round(baseline - pos.y_offset / 64.0 - glyph.bitmap_top))
            draw.bitmap((gx, gy), mask, fill=fill)
        pen_x += pos.x_advance / 64.0


def draw_bengali_block(draw, bbox, lines, font, spacing=4, fill="black", align="center"):
    """Center a list of already-wrapped lines inside bbox using real shaping."""
    x0, y0, x1, y1 = [float(v) for v in bbox]
    size = int(getattr(font, "size", 16))
    path = _font_path(font)
    face = freetype.Face(path)
    face.set_pixel_sizes(0, size)
    line_height = max(1.0, float(face.size.height) / 64.0)
    gap = float(max(0, spacing))
    total_h = line_height * len(lines) + gap * max(0, len(lines) - 1)
    y = y0 + max(0.0, (y1 - y0 - total_h) / 2.0)

    for line in lines:
        width = text_width(line, font)
        if align == "left":
            x = x0
        elif align == "right":
            x = x1 - width
        else:
            x = x0 + max(0.0, (x1 - x0 - width) / 2.0)
        draw_shaped_line(draw, (x, y), line, font, fill=fill)
        y += line_height + gap


def is_available():
    return _AVAILABLE
