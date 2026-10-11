"""文字排版与卡拉OK 填充绘制。"""

from __future__ import annotations

import math
from collections import OrderedDict

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QTransform,
)

_SPRITE_CACHE: "OrderedDict[tuple, TextSprite]" = OrderedDict()
_CACHE_LIMIT = 256


class TextSprite:
    """一段文字的矢量轮廓，可缩放绘制而不失真。"""

    __slots__ = ("text", "size", "path", "advance", "ascent", "descent", "height")

    def __init__(self, text: str, font: QFont) -> None:
        self.text = text
        self.size = font.pixelSize()

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


def _font(family: str, size: int, weight) -> QFont:
    font = QFont(family)
    font.setPixelSize(max(1, int(size)))
    font.setWeight(weight)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def make_sprite(text: str, family: str, size: int, weight) -> TextSprite:
    key = (text, family, int(size), int(weight))
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
