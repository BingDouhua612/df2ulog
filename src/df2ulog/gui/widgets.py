"""Small painted widgets and HTML helpers for the dark df2ulog GUI."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from .i18n import LANG_ZH, normalize_lang, tr


class GlyphIcon(QWidget):
    """Vector icon painted in the accent color (avoids emoji/font fallback issues)."""

    def __init__(self, kind: str = "download", size: int = 56, parent=None) -> None:
        super().__init__(parent)
        self._kind = kind
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(3, 3, -3, -3)
        accent = QColor("#38bdf8")
        side = min(rect.width(), rect.height())
        left = rect.center().x() - side / 2
        top_edge = rect.center().y() - side / 2
        if self._kind == "download":
            tint = QColor(accent)
            tint.setAlpha(32)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(tint)
            painter.drawRoundedRect(rect, int(side * 0.3), int(side * 0.3))
            pen = QPen(accent, max(1.8, side * 0.055))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            center_x = int(left + side * 0.5)
            arrow_top = int(top_edge + side * 0.25)
            arrow_bottom = int(top_edge + side * 0.66)
            head = int(side * 0.14)
            tray = int(side * 0.26)
            painter.drawLine(center_x, arrow_top, center_x, arrow_bottom)
            painter.drawLine(center_x, arrow_bottom, center_x - head, arrow_bottom - head)
            painter.drawLine(center_x, arrow_bottom, center_x + head, arrow_bottom - head)
            painter.drawLine(
                center_x - tray,
                arrow_bottom + int(side * 0.09),
                center_x + tray,
                arrow_bottom + int(side * 0.09),
            )
        else:  # document glyph
            pen = QPen(accent, 2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            left_i, top_i = rect.left() + 8, rect.top() + 5
            right_i, bottom_i = rect.right() - 8, rect.bottom() - 5
            fold = 9
            path = QPainterPath()
            path.moveTo(left_i, top_i)
            path.lineTo(right_i - fold, top_i)
            path.lineTo(right_i, top_i + fold)
            path.lineTo(right_i, bottom_i)
            path.lineTo(left_i, bottom_i)
            path.closeSubpath()
            painter.drawPath(path)
            painter.drawLine(right_i - fold, top_i, right_i - fold, top_i + fold)
            painter.drawLine(right_i - fold, top_i + fold, right_i, top_i + fold)
            line_pen = QPen(QColor("#9fb0c3"), 1.4)
            painter.setPen(line_pen)
            for index in range(2):
                y = top_i + fold + 9 + index * 7
                painter.drawLine(left_i + 6, y, right_i - 6, y)


def app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#38bdf8"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, 63, 63, 14, 14)
    painter.setPen(QColor("#071018"))
    painter.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "d2u")
    painter.end()
    return QIcon(pixmap)


def _row(label: str, value: str, *, value_color: str = "#e6edf5") -> str:
    return (
        '<div style="margin:2px 0;">'
        f'<span style="color:#7d8b9c;">{label}</span>&nbsp;&nbsp;'
        f'<span style="color:{value_color};">{value}</span>'
        "</div>"
    )


def result_html(outcome, lang: str = LANG_ZH) -> str:
    """Render a ConversionOutcome as a compact, styled HTML summary."""
    lang = normalize_lang(lang)
    parts: list[str] = [
        '<div style="font-size:9pt; line-height:130%; color:#c9d4e0;">'
    ]
    if outcome.output_path is not None:
        parts.append(
            _row(
                tr("result.output_file", lang),
                html.escape(str(outcome.output_path)),
            )
        )
    result = outcome.result
    if result is not None:
        df_types = len({plan.df_type_id for plan in result.topics})
        if lang == LANG_ZH:
            topic_value = (
                f"{len(result.topics)}（{df_types} 个 DF 类型） · "
                f"{result.data_record_count:,} 条"
            )
        else:
            topic_value = (
                f"{len(result.topics)} ({df_types} DF types) · "
                f"{result.data_record_count:,} rec"
            )
        parts.extend(
            [
                _row(tr("result.topic_record", lang), topic_value),
                _row(
                    tr("result.params_logs_info", lang),
                    f"{result.params_written} / {result.logging_records} / "
                    f"{result.info_records}",
                ),
                _row(
                    tr("result.size_elapsed", lang),
                    f"{result.output_size:,} B · {result.elapsed_s:.2f} s",
                ),
                _row(
                    tr("result.sha256", lang),
                    '<span style="font-family:Consolas, monospace; color:#8ab4f8;">'
                    f"{html.escape(result.output_sha256)}</span>",
                ),
                _row(
                    tr("result.firmware_frame", lang),
                    f"{html.escape(result.firmware or '-')} · "
                    f"{html.escape(result.frame or '-')}",
                ),
                _row(tr("result.gps_utc", lang), html.escape(result.gps_utc or "-")),
            ]
        )
        if result.source_tail_bytes:
            parts.append(
                _row(
                    tr("result.source_tail", lang),
                    tr("result.source_tail_warn", lang, bytes=result.source_tail_bytes),
                    value_color="#fbbf24",
                )
            )
    if outcome.verify_ok is True:
        parts.append(
            '<div style="margin-top:6px; color:#34d399; font-weight:600;">'
            f"{tr('result.verify_pass', lang)}</div>"
        )
    elif outcome.verify_ok is False:
        parts.append(
            '<div style="margin-top:6px; color:#f87171; font-weight:600;">'
            f"{tr('result.verify_fail', lang)}</div>"
        )
        for failure in outcome.verify_failures:
            parts.append(
                f'<div style="color:#f87171;">&nbsp;&nbsp;- {html.escape(failure)}</div>'
            )
    parts.append("</div>")
    return "".join(parts)


def batch_summary_html(outcome, lang: str = LANG_ZH) -> str:
    """Render a batch conversion summary (success/skipped/failed/cancelled)."""
    lang = normalize_lang(lang)
    total = len(outcome.items)
    cancelled_suffix = "（已取消）" if lang == LANG_ZH else " (cancelled)"
    separator = "：" if lang == LANG_ZH else ": "
    parts: list[str] = [
        '<div style="font-size:9.5pt; line-height:140%; color:#c9d4e0;">',
        (
            f'<div style="margin:0 0 5px 0;">'
            f"{tr('summary.files', lang, count=total)}"
            f"{cancelled_suffix if outcome.cancelled else ''}</div>"
        ),
        _row(tr("summary.success", lang), str(outcome.success_count), value_color="#34d399"),
        _row(tr("summary.skipped", lang), str(outcome.skipped_count), value_color="#fbbf24"),
        _row(tr("summary.failed", lang), str(outcome.failed_count), value_color="#f87171"),
    ]
    if outcome.cancelled_count:
        parts.append(
            _row(
                tr("summary.cancelled", lang),
                str(outcome.cancelled_count),
                value_color="#9fb0c3",
            )
        )
    failures = [item for item in outcome.items if item.status == "failed"]
    for item in failures[:5]:
        parts.append(
            '<div style="color:#f87171; margin-top:3px;">✕ '
            f"{html.escape(item.source.name)}{separator}"
            f"{html.escape(item.message[:180])}</div>"
        )
    skipped = [item for item in outcome.items if item.status == "skipped"][:5]
    for item in skipped:
        parts.append(
            '<div style="color:#fbbf24; margin-top:2px;">– '
            f"{html.escape(item.source.name)}{separator}"
            f"{html.escape(item.message[:160])}</div>"
        )
    parts.append("</div>")
    return "".join(parts)
