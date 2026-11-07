"""文字排版与卡拉OK 填充绘制。"""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTransform,
)

_SPRITE_CACHE: "OrderedDict[tuple, TextSprite]" = OrderedDict()
_CACHE_LIMIT = 256
_LINE_CACHE: "OrderedDict[tuple, LineArt]" = OrderedDict()
_LINE_CACHE_LIMIT = 160
_GLOW_CACHE: "OrderedDict[tuple, tuple[QPixmap, QPixmap]]" = OrderedDict()
_GLOW_CACHE_LIMIT = 12
_ENTRY_CACHE: "OrderedDict[tuple, QPixmap]" = OrderedDict()
_ENTRY_CACHE_LIMIT = 12

# 全局字间距（px）。歌词字体统一套这个值；图标 / 时间这类不走精灵的文字不受影响。
_LETTER_SPACING = 0.0


def set_letter_spacing(px: float) -> None:
    """设置字间距；变了就清空精灵缓存，否则旧宽度的纹理还会被复用。"""
    global _LETTER_SPACING
    value = float(px)
    if abs(value - _LETTER_SPACING) < 1e-6:
        return
    _LETTER_SPACING = value
    _SPRITE_CACHE.clear()
    clear_line_cache()


def letter_spacing() -> float:
    return _LETTER_SPACING


class TextSprite:
    """一段文字的矢量轮廓，可缩放绘制而不失真。"""

    __slots__ = (
        "text", "family", "size", "weight", "path",
        "advance", "ascent", "descent", "height",
    )

    def __init__(self, text: str, font: QFont) -> None:
        self.text = text
        self.family = font.family()
        self.size = font.pixelSize()
        self.weight = int(font.weight())

        metrics = QFontMetricsF(font)
        self.advance = metrics.horizontalAdvance(text) if text else 0.0
        self.ascent = metrics.ascent()
        self.descent = metrics.descent()
        self.height = metrics.height()

        path = QPainterPath()
        if text:
            # 路径以「文字中心」为原点，绘制时只需平移到目标中心即可
            path.addText(-self.advance / 2.0, 0.0, font, text)
        self.path = path


@dataclass
class LineArt:
    """一行歌词的预渲染底字与高光位图。"""

    base: QPixmap
    highlight: QPixmap | None
    soft_highlight: QPixmap | None
    advance: float
    ascent: float
    descent: float
    offset_x: float
    baseline_y: float
    height: float
    font_size: int = 0
    glow_near: QPixmap | None = None
    glow_far: QPixmap | None = None
    blur_steps: tuple[QPixmap, ...] = ()


_SOFT_BUFFER: QPixmap | None = None
_SOFT_BUFFER_KEY: tuple[int, int, float] | None = None
_SOFT_MASK_STATE: tuple | None = None


def clear_line_cache() -> None:
    _LINE_CACHE.clear()
    _GLOW_CACHE.clear()
    _ENTRY_CACHE.clear()


def _blur_layers(
    source: QPixmap,
    radius: float,
) -> QPixmap:
    """三级降采样近似高斯模糊，结果与源图物理尺寸一致。"""
    if source.isNull():
        return source
    levels = 2 if radius < source.height() * 0.18 else 3
    image = source.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    sizes = [(image.width(), image.height())]
    current = image
    for _ in range(levels):
        width = max(1, current.width() // 2)
        height = max(1, current.height() // 2)
        current = current.scaled(
            width,
            height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        sizes.append((width, height))
    for width, height in reversed(sizes[:-1]):
        current = current.scaled(
            width,
            height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    result = QPixmap.fromImage(current)
    result.setDevicePixelRatio(source.devicePixelRatio())
    return result


def glow_layers(
    source: QPixmap,
    font_size: int,
) -> tuple[QPixmap, QPixmap]:
    """取得近 / 远两层预模糊光晕；最多缓存 12 行。"""
    dpr = round(float(source.devicePixelRatio()), 2)
    near_radius = max(2.0, float(font_size) * 0.28)
    far_radius = max(4.0, float(font_size) * 0.65)
    key = (
        source.cacheKey(),
        round(near_radius, 2),
        round(far_radius, 2),
        dpr,
    )
    cached = _GLOW_CACHE.get(key)
    if cached is not None:
        _GLOW_CACHE.move_to_end(key)
        return cached
    value = (
        _blur_layers(source, near_radius),
        _blur_layers(source, far_radius),
    )
    _GLOW_CACHE[key] = value
    if len(_GLOW_CACHE) > _GLOW_CACHE_LIMIT:
        _GLOW_CACHE.popitem(last=False)
    return value


def entry_blur_layer(source: QPixmap, radius: float) -> QPixmap:
    """取得入场用的固定模糊档，最多缓存 12 张。"""
    dpr = round(float(source.devicePixelRatio()), 2)
    key = (source.cacheKey(), round(float(radius), 2), dpr)
    cached = _ENTRY_CACHE.get(key)
    if cached is not None:
        _ENTRY_CACHE.move_to_end(key)
        return cached
    value = _blur_layers(source, radius)
    _ENTRY_CACHE[key] = value
    if len(_ENTRY_CACHE) > _ENTRY_CACHE_LIMIT:
        _ENTRY_CACHE.popitem(last=False)
    return value


def _font(family: str, size: int, weight) -> QFont:
    font = QFont(family)
    font.setPixelSize(max(1, int(size)))
    font.setWeight(weight)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, _LETTER_SPACING)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def make_sprite(text: str, family: str, size: int, weight) -> TextSprite:
    # 缓存 key 必须带字间距：不然拖滑块时命中旧纹理，看不出变化
    key = (text, family, int(size), int(weight), round(_LETTER_SPACING, 2))
    cached = _SPRITE_CACHE.get(key)
    if cached is not None:
        _SPRITE_CACHE.move_to_end(key)
        return cached
    sprite = TextSprite(text, _font(family, size, weight))
    _SPRITE_CACHE[key] = sprite
    if len(_SPRITE_CACHE) > _CACHE_LIMIT:
        _SPRITE_CACHE.popitem(last=False)
    return sprite


def measure(text: str, family: str, size: int, weight) -> float:
    return make_sprite(text, family, size, weight).advance


def fit_size(
    text: str,
    family: str,
    weight,
    base_size: int,
    max_width: float,
    min_size: int = 12,
) -> int:
    """在不超过 max_width 的前提下取最大字号。"""
    if max_width <= 0 or not text:
        return base_size
    if measure(text, family, base_size, weight) <= max_width:
        return base_size
    low, high = min_size, base_size
    best = min_size
    while low <= high:
        mid = (low + high) // 2
        if measure(text, family, mid, weight) <= max_width:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    return best


def ease_out_back(t: float, overshoot: float = 1.7) -> float:
    t = max(0.0, min(1.0, t))
    c = overshoot + 1.0
    u = t - 1.0
    return u * u * ((c + 1.0) * u + c) + 1.0


def quad_transform(src, dst) -> QTransform | None:
    """由 4 组对应点解出透视变换矩阵。

    这里自己解 8 元一次方程组，而不是调用 QTransform.quadToQuad，
    避免依赖绑定层对「输出参数」的处理。
    """
    if len(src) != 4 or len(dst) != 4:
        return None

    rows: list[list[float]] = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1.0, 0.0, 0.0, 0.0, -x * u, -y * u, u])
        rows.append([0.0, 0.0, 0.0, x, y, 1.0, -x * v, -y * v, v])

    size = 8
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        for j in range(col, size + 1):
            rows[col][j] /= divisor
        for r in range(size):
            if r == col:
                continue
            factor = rows[r][col]
            if factor == 0.0:
                continue
            for j in range(col, size + 1):
                rows[r][j] -= factor * rows[col][j]

    values = [rows[i][size] for i in range(size)]
    if any(math.isnan(v) or math.isinf(v) for v in values):
        return None
    m11, m21, m31, m12, m22, m32, m13, m23 = values
    return QTransform(m11, m12, m13, m21, m22, m23, m31, m32, 1.0)


def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - math.pow(1.0 - t, 3)


def _stroke_path(painter: QPainter, sprite: TextSprite, color: QColor, width: float) -> None:
    if width <= 0:
        return
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(sprite.path)


def _fill_path(painter: QPainter, sprite: TextSprite, paint) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(paint)
    painter.drawPath(sprite.path)


def _color_key(color: QColor | None) -> str:
    return color.name(QColor.NameFormat.HexArgb) if color is not None else ""


def make_line_art(
    sprite: TextSprite,
    base_color: QColor,
    grad_colors: tuple[str, str, str] | None = None,
    glow_color: QColor | None = None,
    outline_width: float = 0.0,
    outline_color: QColor | None = None,
    shadow: bool = True,
    dpr: float = 1.0,
    glow: bool = False,
) -> LineArt:
    """把一行文字烘成普通层 + 高光层，绘制时只贴图。"""
    key = (
        sprite.text,
        sprite.family,
        sprite.size,
        sprite.weight,
        round(sprite.advance, 2),
        _color_key(base_color),
        grad_colors,
        _color_key(glow_color),
        round(float(outline_width), 2),
        _color_key(outline_color),
        bool(shadow),
        round(float(dpr), 2),
        bool(glow),
    )
    cached = _LINE_CACHE.get(key)
    if cached is not None:
        _LINE_CACHE.move_to_end(key)
        return cached

    dpr = max(1.0, float(dpr))
    glow_pad = sprite.size * 0.8 if glow else 0.0
    pad_x = max(
        4.0,
        sprite.advance * 0.08,
        float(outline_width) * 1.5 + 2.0,
        glow_pad,
    )
    logical_w = max(1.0, sprite.advance + pad_x * 2.0)
    logical_h = max(1.0, (sprite.ascent + sprite.descent) * 1.9 + glow_pad * 1.4)
    offset_x = pad_x + sprite.advance / 2.0
    baseline_y = logical_h / 2.0 + (sprite.ascent - sprite.descent) / 2.0

    physical_w = max(2, int(math.ceil(logical_w * dpr)))
    physical_h = max(2, int(math.ceil(logical_h * dpr)))

    def new_pixmap() -> QPixmap:
        pixmap = QPixmap(physical_w, physical_h)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(dpr)
        return pixmap

    def begin(pixmap: QPixmap) -> QPainter:
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.translate(offset_x, baseline_y)
        return painter

    base = new_pixmap()
    painter = begin(base)
    if shadow:
        painter.save()
        painter.translate(0.0, max(1.0, sprite.size * 0.055))
        _fill_path(painter, sprite, QColor(0, 0, 0, 115))
        painter.restore()
    if outline_width > 0 and outline_color is not None:
        _stroke_path(painter, sprite, outline_color, outline_width)
    _fill_path(painter, sprite, base_color)
    painter.end()

    highlight = None
    soft_highlight = None
    if grad_colors is not None and glow_color is not None:
        highlight = new_pixmap()
        painter = begin(highlight)
        glow_pen = QPen(
            QColor(glow_color.red(), glow_color.green(), glow_color.blue(), 70)
        )
        glow_pen.setWidthF(max(2.0, sprite.size * 0.13))
        glow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(glow_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(sprite.path)
        gradient = QLinearGradient(
            -sprite.advance / 2.0, 0.0, sprite.advance / 2.0, 0.0
        )
        gradient.setColorAt(0.0, QColor(grad_colors[0]))
        gradient.setColorAt(0.5, QColor(grad_colors[1]))
        gradient.setColorAt(1.0, QColor(grad_colors[2]))
        _fill_path(painter, sprite, gradient)
        painter.end()

        # 高光软边分两层：纵向上下 10% 慢慢淡出，横向向远端略微收光。
        # 这一层跟着 LineArt 缓存在换行时生成一次，逐帧只做前沿遮罩。
        soft_highlight = new_pixmap()
        painter = QPainter(soft_highlight)
        painter.drawPixmap(0, 0, highlight)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_DestinationIn
        )
        vertical = QLinearGradient(0.0, 0.0, 0.0, logical_h)
        vertical.setColorAt(0.0, QColor(255, 255, 255, 0))
        vertical.setColorAt(0.10, QColor(255, 255, 255, 255))
        vertical.setColorAt(0.90, QColor(255, 255, 255, 255))
        vertical.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(vertical)
        painter.drawRect(QRectF(0.0, 0.0, logical_w, logical_h))
        horizontal = QLinearGradient(0.0, 0.0, logical_w, 0.0)
        horizontal.setColorAt(0.0, QColor(255, 255, 255, 255))
        horizontal.setColorAt(0.58, QColor(255, 255, 255, 235))
        horizontal.setColorAt(1.0, QColor(255, 255, 255, 184))
        painter.setBrush(horizontal)
        painter.drawRect(QRectF(0.0, 0.0, logical_w, logical_h))
        painter.end()

    art = LineArt(
        base=base,
        highlight=highlight,
        soft_highlight=soft_highlight,
        advance=sprite.advance,
        ascent=sprite.ascent,
        descent=sprite.descent,
        offset_x=offset_x,
        baseline_y=baseline_y,
        height=logical_h,
        font_size=sprite.size,
    )
    _LINE_CACHE[key] = art
    if len(_LINE_CACHE) > _LINE_CACHE_LIMIT:
        _LINE_CACHE.popitem(last=False)
    return art


def draw_line_art(
    painter: QPainter,
    art: LineArt,
    center_x: float,
    baseline: float,
    progress: float = 0.0,
    scale: float = 1.0,
    opacity: float = 1.0,
    softness: float = 0.0,
    tail_progress: float | None = None,
    tail_alpha: float = 0.72,
    glow_scale: float = 0.0,
    entry_blur: float = 0.0,
    rotation: float = 0.0,
) -> None:
    painter.save()
    painter.setOpacity(max(0.0, min(1.0, painter.opacity() * opacity)))
    painter.translate(center_x, baseline)
    if rotation:
        painter.rotate(rotation)
    if scale != 1.0:
        painter.scale(scale, scale)
    glow_alpha = glow_scale * max(0.0, 1.0 - entry_blur / 10.0)
    if glow_alpha > 0.01 and art.highlight is not None:
        near, far = glow_layers(art.highlight, art.font_size)
        painter.save()
        painter.setOpacity(painter.opacity() * min(1.0, glow_alpha * 0.28))
        painter.drawPixmap(
            QPointF(-art.offset_x, -art.baseline_y), far
        )
        painter.setOpacity(painter.opacity() * min(1.0, glow_alpha * 0.52))
        painter.drawPixmap(
            QPointF(-art.offset_x, -art.baseline_y), near
        )
        painter.restore()
    base_layer = art.base
    if entry_blur > 0.0:
        if entry_blur >= 7.5:
            radius = 10.0
        elif entry_blur >= 3.5:
            radius = 5.0
        elif entry_blur >= 0.8:
            radius = 2.5
        else:
            radius = 0.0
        if radius > 0.0:
            base_layer = entry_blur_layer(art.base, radius)
    painter.drawPixmap(QPointF(-art.offset_x, -art.baseline_y), base_layer)

    progress = max(0.0, min(1.0, float(progress)))
    if progress > 0.0 and art.highlight is not None and entry_blur < 7.0:
        if softness > 0.0 and art.soft_highlight is not None:
            _draw_soft_highlight(
                painter,
                art,
                progress=progress,
                opacity=min(1.0, progress * 6.0),
                softness=softness,
                tail_progress=tail_progress,
                tail_alpha=tail_alpha,
            )
            painter.restore()
            return
        painter.save()
        painter.setClipRect(
            QRectF(
                -art.advance / 2.0,
                -art.ascent * 1.25,
                art.advance * progress,
                art.height * 1.9,
            )
        )
        painter.setOpacity(painter.opacity() * min(1.0, progress * 6.0))
        painter.drawPixmap(
            QPointF(-art.offset_x, -art.baseline_y), art.highlight
        )
        painter.restore()
    painter.restore()


def _draw_soft_highlight(
    painter: QPainter,
    art: LineArt,
    *,
    progress: float,
    opacity: float,
    softness: float,
    tail_progress: float | None,
    tail_alpha: float,
) -> None:
    global _SOFT_BUFFER, _SOFT_BUFFER_KEY, _SOFT_MASK_STATE
    dpr = max(1.0, art.soft_highlight.devicePixelRatio())
    key = (art.soft_highlight.width(), art.soft_highlight.height(), dpr)
    if _SOFT_BUFFER is None or _SOFT_BUFFER_KEY != key:
        _SOFT_BUFFER = QPixmap(art.soft_highlight.size())
        _SOFT_BUFFER.setDevicePixelRatio(dpr)
        _SOFT_BUFFER_KEY = key
        _SOFT_MASK_STATE = None
    mask_state = (
        art.soft_highlight.cacheKey(),
        round(float(progress), 4),
        round(float(tail_progress if tail_progress is not None else progress), 4),
        round(float(softness), 2),
        round(float(tail_alpha), 3),
        round(float(dpr), 2),
    )
    if _SOFT_MASK_STATE != mask_state:
        _SOFT_BUFFER.fill(Qt.GlobalColor.transparent)
        buffer_painter = QPainter(_SOFT_BUFFER)
        buffer_painter.drawPixmap(0, 0, art.soft_highlight)
        buffer_painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_DestinationIn
        )
        logical_w = art.soft_highlight.width() / dpr
        logical_h = art.soft_highlight.height() / dpr
        left = art.offset_x - art.advance / 2.0
        solid_x = left + art.advance * progress
        tail = max(progress, float(tail_progress if tail_progress is not None else progress))
        tail_x = left + art.advance * tail
        feather_x = min(left + art.advance, tail_x + max(1.0, float(softness)))
        width = max(0.01, feather_x - left)
        edge = QLinearGradient(left, 0.0, feather_x, 0.0)
        edge.setColorAt(0.0, QColor(255, 255, 255, 255))
        edge.setColorAt(
            max(0.0, min(1.0, (solid_x - left) / width)),
            QColor(255, 255, 255, 255),
        )
        edge.setColorAt(
            max(0.0, min(1.0, (tail_x - left) / width)),
            QColor(255, 255, 255, int(max(0.0, min(1.0, tail_alpha)) * 255)),
        )
        edge.setColorAt(1.0, QColor(255, 255, 255, 0))
        buffer_painter.setPen(Qt.PenStyle.NoPen)
        buffer_painter.setBrush(edge)
        buffer_painter.drawRect(QRectF(0.0, 0.0, logical_w, logical_h))
        buffer_painter.end()
        _SOFT_MASK_STATE = mask_state

    painter.save()
    painter.setOpacity(painter.opacity() * opacity)
    painter.drawPixmap(
        QPointF(-art.offset_x, -art.baseline_y), _SOFT_BUFFER
    )
    painter.restore()


def draw_sprite(
    painter: QPainter,
    sprite: TextSprite,
    center_x: float,
    baseline: float,
    color: QColor,
    scale: float = 1.0,
    opacity: float = 1.0,
    outline_width: float = 0.0,
    outline_color: QColor | None = None,
    shadow: bool = True,
) -> None:
    if not sprite.text:
        return
    painter.save()
    # 用「相乘」而不是「覆盖」，这样外层还能再套一个整体透明度
    painter.setOpacity(max(0.0, min(1.0, painter.opacity() * opacity)))
    painter.translate(center_x, baseline)
    if scale != 1.0:
        painter.scale(scale, scale)

    if shadow:
        painter.save()
        painter.translate(0.0, max(1.0, sprite.size * 0.055))
        _fill_path(painter, sprite, QColor(0, 0, 0, 110))
        painter.restore()

    if outline_width > 0 and outline_color is not None:
        _stroke_path(painter, sprite, outline_color, outline_width)

    _fill_path(painter, sprite, color)
    painter.restore()


def draw_karaoke(
    painter: QPainter,
    sprite: TextSprite,
    center_x: float,
    baseline: float,
    base_color: QColor,
    grad_colors: tuple[str, str, str],
    progress: float,
    glow_color: QColor,
    scale: float = 1.0,
    opacity: float = 1.0,
    outline_width: float = 0.0,
    outline_color: QColor | None = None,
    shadow: bool = True,
) -> None:
    """先画底字，再按 progress 裁切画出渐变高亮，形成逐字推进效果。"""
    if not sprite.text:
        return

    left = center_x - sprite.advance / 2.0
    right = center_x + sprite.advance / 2.0

    painter.save()
    painter.setOpacity(max(0.0, min(1.0, painter.opacity() * opacity)))
    painter.translate(center_x, baseline)
    if scale != 1.0:
        painter.scale(scale, scale)

    if shadow:
        painter.save()
        painter.translate(0.0, max(1.0, sprite.size * 0.055))
        _fill_path(painter, sprite, QColor(0, 0, 0, 115))
        painter.restore()

    if outline_width > 0 and outline_color is not None:
        _stroke_path(painter, sprite, outline_color, outline_width)

    _fill_path(painter, sprite, base_color)

    progress = max(0.0, min(1.0, progress))
    if progress > 0.0:
        painter.save()
        clip_left = -sprite.advance / 2.0
        clip_width = sprite.advance * progress
        painter.setClipRect(QRectF(clip_left, -sprite.ascent * 1.25, clip_width, sprite.height * 1.9))
        painter.setOpacity(painter.opacity() * min(1.0, progress * 6.0))

        gradient = QLinearGradient(-sprite.advance / 2.0, 0.0, sprite.advance / 2.0, 0.0)
        gradient.setColorAt(0.0, QColor(grad_colors[0]))
        gradient.setColorAt(0.5, QColor(grad_colors[1]))
        gradient.setColorAt(1.0, QColor(grad_colors[2]))

        # 高光描边，做出轻微发光
        glow_pen = QPen(QColor(glow_color.red(), glow_color.green(), glow_color.blue(), 70))
        glow_pen.setWidthF(max(2.0, sprite.size * 0.13))
        glow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(glow_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(sprite.path)

        _fill_path(painter, sprite, gradient)
        painter.restore()

    painter.restore()
