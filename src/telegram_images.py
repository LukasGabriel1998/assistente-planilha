# -*- coding: utf-8 -*-
"""Layout visual compartilhado para imagens enviadas pelo bot no Telegram."""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from typing import Callable

from .dates import now_local

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore


@dataclass(frozen=True)
class ImageTheme:
    outer_bg: tuple[int, int, int] = (226, 232, 240)
    card_bg: tuple[int, int, int] = (255, 255, 255)
    shadow: tuple[int, int, int] = (203, 213, 225)
    shadow_soft: tuple[int, int, int] = (241, 245, 249)
    border: tuple[int, int, int] = (226, 232, 240)
    ink: tuple[int, int, int] = (15, 23, 42)
    muted: tuple[int, int, int] = (100, 116, 139)
    header_top: tuple[int, int, int] = (15, 23, 42)
    header_bottom: tuple[int, int, int] = (30, 64, 175)
    header_text: tuple[int, int, int] = (255, 255, 255)
    header_sub: tuple[int, int, int] = (191, 219, 254)
    profit: tuple[int, int, int] = (5, 150, 105)
    loss: tuple[int, int, int] = (220, 38, 38)
    pending: tuple[int, int, int] = (217, 119, 6)
    table_header_bg: tuple[int, int, int] = (241, 245, 249)
    table_header_ink: tuple[int, int, int] = (30, 41, 59)
    zebra: tuple[int, int, int] = (248, 250, 252)
    highlight: tuple[int, int, int] = (254, 243, 199)
    status_paid: tuple[int, int, int] = (209, 250, 229)
    status_pending: tuple[int, int, int] = (254, 249, 195)
    delivery_done: tuple[int, int, int] = (187, 247, 208)


THEME = ImageTheme()

_FONT_CACHE: dict[tuple[int, bool], object] = {}

_FONT_REGULAR = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    r"C:\Windows\Fonts\arial.ttf",
)

_FONT_BOLD = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\calibrib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
)


def pil_available() -> bool:
    return Image is not None


def load_font(size: int, *, bold: bool = False):
    if ImageFont is None:
        return None
    key = (size, bold)
    cached = _FONT_CACHE.get(key)
    if cached is not None:
        return cached
    for fp in (_FONT_BOLD if bold else _FONT_REGULAR):
        try:
            font = ImageFont.truetype(fp, size=size)
            _FONT_CACHE[key] = font
            return font
        except Exception:
            continue
    font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def save_telegram_jpeg(img) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    tmp.close()
    img.save(tmp.name, format="JPEG", quality=90, optimize=False)
    return tmp.name


def format_brl(value: float) -> str:
    txt = f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {txt}"


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    try:
        return int(draw.textlength(text, font=font))
    except Exception:
        return max(1, len(text)) * 8


def _text_height(font) -> int:
    bbox = font.getbbox("Ag")
    return int(bbox[3] - bbox[1])


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _blend(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (_lerp(c1[0], c2[0], t), _lerp(c1[1], c2[1], t), _lerp(c1[2], c2[2], t))


def _draw_card_shadow(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], *, radius: int = 20) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle((x0 + 2, y0 + 6, x1 + 2, y1 + 6), radius=radius, fill=THEME.shadow)
    draw.rounded_rectangle((x0 + 1, y0 + 3, x1 + 1, y1 + 3), radius=radius, fill=THEME.shadow_soft)


def _draw_gradient_header(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    title: str,
    subtitle: str | None = None,
    radius: int = 20,
) -> int:
    x0, y0, x1, y1 = box
    height = y1 - y0
    for i in range(height):
        t = i / max(1, height - 1)
        color = _blend(THEME.header_top, THEME.header_bottom, t)
        draw.line((x0, y0 + i, x1, y0 + i), fill=color)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=None)
    draw.rectangle((x0, y0 + radius, x1, y1), fill=THEME.header_bottom)

    font_title = load_font(24, bold=True)
    font_sub = load_font(15, bold=False)
    tw = _text_width(draw, title, font_title)
    draw.text((x0 + ((x1 - x0) - tw) / 2, y0 + 14), title, fill=THEME.header_text, font=font_title)
    if subtitle:
        sw = _text_width(draw, subtitle, font_sub)
        draw.text(
            (x0 + ((x1 - x0) - sw) / 2, y0 + 44),
            subtitle,
            fill=THEME.header_sub,
            font=font_sub,
        )
    return height


def _truncate(draw: ImageDraw.ImageDraw, text: str, max_width: int, font) -> str:
    text = str(text or "")
    if _text_width(draw, text, font) <= max_width:
        return text
    suffix = "..."
    while text and _text_width(draw, text + suffix, font) > max_width:
        text = text[:-1]
    return (text + suffix) if text else suffix


def _updated_subtitle() -> str:
    return f"Atualizado em {now_local().strftime('%d/%m/%Y às %H:%M')}"


def render_kpi_dashboard(
    items: list[tuple[str, str, bool]],
    *,
    title: str = "TOTAL DOS LUCROS MENSAIS E ANUAIS",
    accent_colors: list[tuple[int, int, int]] | None = None,
    profit_value: float = 0.0,
) -> str | None:
    if not pil_available() or not items:
        return None

    accents = accent_colors or [
        (37, 99, 235),
        (5, 150, 105),
        (217, 119, 6),
        (124, 58, 237),
        (100, 116, 139),
        (5, 150, 105),
    ]

    font_label = load_font(15, bold=False)
    font_value = load_font(26, bold=True)

    pad = 24
    card_w = 920
    header_h = 72
    gap = 16
    cols = 2
    rows = (len(items) + cols - 1) // cols
    inner_w = card_w - pad * 2
    cell_w = (inner_w - gap) // 2
    cell_h = 112
    body_h = rows * cell_h + max(0, rows - 1) * gap
    card_h = pad + header_h + 20 + body_h + pad
    img_w = card_w + pad * 2
    img_h = card_h + pad * 2

    img = Image.new("RGB", (img_w, img_h), THEME.outer_bg)
    draw = ImageDraw.Draw(img)

    cx0, cy0 = pad, pad
    cx1, cy1 = cx0 + card_w, cy0 + card_h
    _draw_card_shadow(draw, (cx0, cy0, cx1, cy1))
    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=20, fill=THEME.card_bg, outline=THEME.border, width=1)

    header_box = (cx0, cy0, cx1, cy0 + header_h)
    _draw_gradient_header(draw, header_box, title=title, subtitle=_updated_subtitle(), radius=20)

    y0 = cy0 + header_h + 20
    x0 = cx0 + pad

    for i, (label, value, is_profit) in enumerate(items):
        r, c = divmod(i, cols)
        x = x0 + c * (cell_w + gap)
        y = y0 + r * (cell_h + gap)
        accent = accents[i % len(accents)]
        if is_profit:
            accent = THEME.profit if profit_value >= 0 else THEME.loss
            fill = (236, 253, 245) if profit_value >= 0 else (254, 242, 242)
            outline = accent
            outline_w = 2
        else:
            fill = THEME.card_bg if (r + c) % 2 else THEME.zebra
            outline = THEME.border
            outline_w = 1

        draw.rounded_rectangle((x, y, x + cell_w, y + cell_h), radius=14, fill=fill, outline=outline, width=outline_w)
        draw.rounded_rectangle((x, y + 10, x + 6, y + cell_h - 10), radius=3, fill=accent)

        label_txt = _truncate(draw, label, cell_w - 36, font_label)
        draw.text((x + 18, y + 16), label_txt, fill=THEME.muted, font=font_label)

        val_color = accent if is_profit else THEME.ink
        value_txt = _truncate(draw, value, cell_w - 36, font_value)
        draw.text((x + 18, y + 52), value_txt, fill=val_color, font=font_value)

    return save_telegram_jpeg(img)


def render_text_card(text: str, *, title: str = "Resumo da planilha") -> str | None:
    if not pil_available():
        return None
    raw = (text or "").strip()
    if not raw:
        return None

    lines_in = [ln.replace("*", "").replace("📄", "").replace("📋", "").rstrip() for ln in raw.splitlines()]
    font_body = load_font(18, bold=False)
    font_title = load_font(24, bold=True)
    pad = 24
    card_w = 920
    header_h = 72
    line_h = _text_height(font_body) + 10
    max_text_w = card_w - pad * 2 - 36

    img_probe = Image.new("RGB", (20, 20))
    probe = ImageDraw.Draw(img_probe)

    wrapped: list[str] = []
    for ln in lines_in:
        if not ln.strip():
            wrapped.append("")
            continue
        words = ln.split()
        cur = ""
        for w in words:
            nxt = (cur + " " + w).strip()
            if _text_width(probe, nxt, font_body) <= max_text_w:
                cur = nxt
            else:
                if cur:
                    wrapped.append(cur)
                cur = w
        wrapped.append(cur)

    body_h = len(wrapped) * line_h + 12
    card_h = pad + header_h + 20 + body_h + pad
    img_w = card_w + pad * 2
    img_h = card_h + pad * 2

    img = Image.new("RGB", (img_w, img_h), THEME.outer_bg)
    draw = ImageDraw.Draw(img)

    cx0, cy0 = pad, pad
    cx1, cy1 = cx0 + card_w, cy0 + card_h
    _draw_card_shadow(draw, (cx0, cy0, cx1, cy1))
    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=20, fill=THEME.card_bg, outline=THEME.border, width=1)
    _draw_gradient_header(draw, (cx0, cy0, cx1, cy0 + header_h), title=title, subtitle=_updated_subtitle(), radius=20)

    y = cy0 + header_h + 24
    for ln in wrapped:
        if not ln.strip():
            y += line_h // 2
            continue
        color = THEME.muted if ln.strip().lower().startswith("nenhuma") else THEME.ink
        draw.text((cx0 + pad + 6, y), ln, fill=color, font=font_body)
        y += line_h

    return save_telegram_jpeg(img)


def render_data_table(
    *,
    title: str,
    meta: str,
    headers: list[str],
    rows: list[list[str]],
    col_widths: list[int] | None = None,
    cell_style: Callable[[int, int, str, list[str]], tuple[tuple[int, int, int], tuple[int, int, int]]] | None = None,
) -> str | None:
    if not pil_available() or not headers or not rows:
        return None

    font_body = load_font(17, bold=False)
    font_header = load_font(16, bold=True)
    pad = 24
    card_pad = 18
    cell_pad_x = 14
    cell_pad_y = 10

    img_probe = Image.new("RGB", (20, 20))
    probe = ImageDraw.Draw(img_probe)

    if col_widths is None:
        col_widths = []
        for ci, header in enumerate(headers):
            maxw = _text_width(probe, header, font_header)
            for row in rows:
                maxw = max(maxw, _text_width(probe, str(row[ci]), font_body))
            cap = 320 if header.lower() in ("cliente", "produto") else 210
            floor = 110
            col_widths.append(max(floor, min(cap, maxw + cell_pad_x * 2)))

    row_h = _text_height(font_body) + cell_pad_y * 2 + 4
    header_h = 72
    meta_h = 28
    table_w = sum(col_widths)
    table_h = row_h * (1 + len(rows))
    card_w = table_w + card_pad * 2
    card_h = header_h + meta_h + table_h + card_pad * 2 + 16
    img_w = card_w + pad * 2
    img_h = card_h + pad * 2

    img = Image.new("RGB", (img_w, img_h), THEME.outer_bg)
    draw = ImageDraw.Draw(img)

    cx0, cy0 = pad, pad
    cx1, cy1 = cx0 + card_w, cy0 + card_h
    _draw_card_shadow(draw, (cx0, cy0, cx1, cy1))
    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=20, fill=THEME.card_bg, outline=THEME.border, width=1)
    _draw_gradient_header(draw, (cx0, cy0, cx1, cy0 + header_h), title=title, subtitle=meta, radius=20)

    x0 = cx0 + card_pad
    y0 = cy0 + header_h + meta_h + 8

    x = x0
    for ci, header in enumerate(headers):
        w = col_widths[ci]
        draw.rounded_rectangle((x, y0, x + w, y0 + row_h), radius=8, fill=THEME.table_header_bg, outline=THEME.border, width=1)
        ht = _truncate(draw, header, w - 2 * cell_pad_x, font_header)
        draw.text((x + cell_pad_x, y0 + cell_pad_y), ht, fill=THEME.table_header_ink, font=font_header)
        x += w

    for ri, row in enumerate(rows, start=1):
        y = y0 + row_h * ri
        x = x0
        for ci, txt in enumerate(row):
            w = col_widths[ci]
            header = headers[ci]
            if cell_style:
                cell_fill, cell_ink = cell_style(ri - 1, ci, header, row)
            else:
                cell_fill = THEME.zebra if ri % 2 == 0 else THEME.card_bg
                cell_ink = THEME.ink
            draw.rectangle((x, y, x + w, y + row_h), fill=cell_fill, outline=THEME.border, width=1)
            shown = _truncate(draw, str(txt), w - 2 * cell_pad_x, font_body)
            is_money = header.lower() in ("pago", "pendente", "entrada", "material", "custo material")
            if is_money:
                tw = _text_width(draw, shown, font_body)
                tx = x + w - cell_pad_x - tw
            else:
                tx = x + cell_pad_x
            draw.text((tx, y + cell_pad_y), shown, fill=cell_ink, font=font_body)
            x += w

    return save_telegram_jpeg(img)


__all__ = [
    "format_brl",
    "load_font",
    "pil_available",
    "render_data_table",
    "render_kpi_dashboard",
    "render_text_card",
    "save_telegram_jpeg",
]
