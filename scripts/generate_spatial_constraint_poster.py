#!/usr/bin/env python3
"""Generate the UniLab spatial-constraint explainer poster as PDF and SVG."""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "pdf"
STEM = "2026-08-28-unilab-spatial-constraint-auto-compute-poster"
PDF_PATH = OUT_DIR / f"{STEM}.pdf"
SVG_PATH = OUT_DIR / f"{STEM}.svg"

PAGE_W, PAGE_H = landscape(A3)
FONT_REGULAR = "/System/Library/Fonts/STHeiti Light.ttc"
FONT_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"

BG = "#071522"
PANEL = "#0E2233"
PANEL_2 = "#10283C"
LINE = "#26465C"
WHITE = "#F4FAFC"
MUTED = "#9FB7C5"
CYAN = "#2DD4BF"
BLUE = "#55A6FF"
GREEN = "#43D17A"
AMBER = "#F6C85F"
RED = "#FF6B6B"
PURPLE = "#A78BFA"

SOFT_FILL = {
    CYAN: "#123A3B",
    BLUE: "#173550",
    GREEN: "#173C2B",
    AMBER: "#3A3320",
    RED: "#3B242B",
    PURPLE: "#302743",
}


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float
    fill: str
    stroke: str | None = None
    radius: float = 0
    stroke_width: float = 1


@dataclass(frozen=True)
class Text:
    x: float
    y: float
    value: str
    size: float
    color: str = WHITE
    bold: bool = False
    anchor: str = "start"
    letter_spacing: float = 0


@dataclass(frozen=True)
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    color: str
    width: float = 1
    dashed: bool = False


@dataclass(frozen=True)
class Circle:
    cx: float
    cy: float
    r: float
    fill: str
    stroke: str | None = None
    stroke_width: float = 1


@dataclass(frozen=True)
class Polygon:
    points: tuple[tuple[float, float], ...]
    fill: str


Primitive = Rect | Text | Line | Circle | Polygon


def _register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("PosterCN", FONT_REGULAR, subfontIndex=0))
    pdfmetrics.registerFont(TTFont("PosterCN-Bold", FONT_BOLD, subfontIndex=0))


def add_text_lines(
    items: list[Primitive],
    x: float,
    y: float,
    lines: list[str],
    size: float,
    color: str = MUTED,
    leading: float | None = None,
    bold: bool = False,
    anchor: str = "start",
) -> None:
    step = leading or size * 1.45
    for index, line in enumerate(lines):
        items.append(Text(x, y + index * step, line, size, color, bold, anchor))


def status_chip(
    items: list[Primitive],
    x: float,
    y: float,
    label: str,
    color: str,
    width: float,
) -> None:
    items.append(Rect(x, y, width, 22, SOFT_FILL[color], color, 11, 0.8))
    items.append(Text(x + width / 2, y + 5.5, label, 9.5, color, True, "middle"))


def build_primitives() -> list[Primitive]:
    items: list[Primitive] = [Rect(0, 0, PAGE_W, PAGE_H, BG)]

    # Quiet technical-grid background.
    for x in range(0, int(PAGE_W) + 1, 52):
        items.append(Line(x, 0, x, PAGE_H, "#0B1C2A", 0.45))
    for y in range(0, int(PAGE_H) + 1, 52):
        items.append(Line(0, y, PAGE_W, y, "#0B1C2A", 0.45))
    items.extend(
        [
            Circle(PAGE_W - 60, 70, 112, "#102D40"),
            Circle(PAGE_W - 60, 70, 72, BG, "#1E5068", 1.2),
            Circle(42, PAGE_H - 12, 88, "#0D2A35"),
        ]
    )

    # Header.
    items.append(Text(36, 26, "UNILAB · SPATIAL SHADOW PIPELINE", 10, CYAN, True, letter_spacing=1.2))
    items.append(Text(36, 50, "空间约束自动计算", 31, WHITE, True))
    items.append(Text(36, 90, "从“动作脚本”到“可追溯空间证据”", 18, BLUE, True))
    items.append(
        Text(
            36,
            119,
            "一句话：把设备、动作和误差放进同一坐标系，计算“谁在何时占用哪片空间”，再输出可解释决定。",
            12.5,
            MUTED,
        )
    )

    status_x, status_y, status_w, status_h = PAGE_W - 248, 27, 212, 102
    items.append(Rect(status_x, status_y, status_w, status_h, PANEL_2, CYAN, 16, 1.1))
    items.append(Text(status_x + 16, status_y + 14, "当前运行模式", 10, MUTED, True))
    items.append(Text(status_x + 16, status_y + 38, "OFFLINE + SHADOW", 16.5, CYAN, True))
    items.append(Text(status_x + 16, status_y + 68, "只计算、只记录", 10.5, WHITE, True))
    items.append(Text(status_x + 16, status_y + 84, "不改变派发 · 不控制真机", 9.5, MUTED))

    # Evidence numbers.
    items.append(Text(36, 157, "这轮已经有的硬证据", 11, WHITE, True))
    metrics = [
        ("5", "份 v0 Schema", CYAN),
        ("24", "个输入被摘要锁定", BLUE),
        ("15", "个静态碰撞代理", AMBER),
        ("14", "个机器人 waypoint", GREEN),
        ("2", "个工具状态", PURPLE),
        ("30/30", "根仓测试通过", CYAN),
    ]
    mx, my, gap = 36, 181, 10
    metric_w = (PAGE_W - 72 - gap * 5) / 6
    for index, (number, label, color) in enumerate(metrics):
        x = mx + index * (metric_w + gap)
        items.append(Rect(x, my, metric_w, 62, PANEL, LINE, 12, 0.8))
        items.append(Text(x + 14, my + 11, number, 20, color, True))
        items.append(Text(x + 14, my + 39, label, 9.5, MUTED))

    # Pipeline.
    items.append(Text(36, 274, "自动计算流水线", 14, WHITE, True))
    items.append(Text(174, 278, "实线 = 已有纵切    虚线/浅色 = 下一阶段", 9.5, MUTED))
    card_y, card_h, card_gap = 303, 202, 13
    card_w = (PAGE_W - 72 - card_gap * 5) / 6
    steps = [
        {
            "n": "01",
            "title": ["锁定输入"],
            "status": "已实现",
            "status_w": 55,
            "color": GREEN,
            "body": ["CAD / URDF / 点表 / 标定", "记录路径、bytes、SHA-256", "输入一变，旧证书立即失效"],
        },
        {
            "n": "02",
            "title": ["搭碰撞世界"],
            "status": "部分",
            "status_w": 45,
            "color": AMBER,
            "body": ["统一为 Z-up / meter", "已编译 15 个静态代理", "动态 CR5 / 工具 / 载荷待补"],
        },
        {
            "n": "03",
            "title": ["翻译动作"],
            "status": "已实现",
            "status_w": 55,
            "color": GREEN,
            "body": ["tank1 pick → 14 个 waypoint", "2 个工具状态 + 载荷阶段", "保留点表和动作来源"],
        },
        {
            "n": "04",
            "title": ["还原连续运动"],
            "status": "下一步",
            "status_w": 55,
            "color": BLUE,
            "body": ["FK + move_j / move_l 插补", "CP 与采样间保守膨胀", "语义不完整就 unknown"],
        },
        {
            "n": "05",
            "title": ["扫出走廊与冲突"],
            "status": "未实现",
            "status_w": 55,
            "color": RED,
            "body": ["link / tool / payload 扫掠体", "+ 几何/标定/跟踪/采样误差", "求碰撞、最近距离和阶段"],
        },
        {
            "n": "06",
            "title": ["发证书与决定"],
            "status": "初版",
            "status_w": 45,
            "color": PURPLE,
            "body": ["certificate 绑定全部摘要", "allowed / blocked / unknown", "当前 unknown · effect=none"],
        },
    ]
    for index, step in enumerate(steps):
        x = 36 + index * (card_w + card_gap)
        border = step["color"]
        items.append(Rect(x, card_y, card_w, card_h, PANEL, border, 14, 1.0))
        items.append(Circle(x + 27, card_y + 31, 16, SOFT_FILL[step["color"]], step["color"], 1.0))
        items.append(Text(x + 27, card_y + 22.5, step["n"], 10.5, step["color"], True, "middle"))
        status_chip(items, x + card_w - step["status_w"] - 12, card_y + 20, step["status"], step["color"], step["status_w"])
        add_text_lines(items, x + 15, card_y + 63, step["title"], 14, WHITE, 18, True)
        items.append(Line(x + 15, card_y + 91, x + card_w - 15, card_y + 91, LINE, 0.8))
        add_text_lines(items, x + 15, card_y + 109, step["body"], 9.2, MUTED, 23)
        if index < len(steps) - 1:
            arrow_x = x + card_w + 3
            arrow_y = card_y + card_h / 2
            arrow_color = CYAN if index < 3 else LINE
            items.append(Line(arrow_x, arrow_y, arrow_x + 8, arrow_y, arrow_color, 1.5, index >= 3))
            items.append(Polygon(((arrow_x + 8, arrow_y - 4), (arrow_x + 12, arrow_y), (arrow_x + 8, arrow_y + 4)), arrow_color))

    # The calculation in plain language and formula form.
    formula_y = 521
    items.append(Rect(36, formula_y, PAGE_W - 72, 52, "#0B2A38", "#1B5266", 13, 0.9))
    items.append(Text(53, formula_y + 9, "核心计算", 10.5, CYAN, True))
    items.append(
        Text(
            141,
            formula_y + 8,
            "动作占用空间 = 所有时刻 × 所有动态实体 × 世界变换 × 碰撞几何 + 可解释的不确定度",
            13.2,
            WHITE,
            True,
        )
    )
    items.append(
        Text(
            141,
            formula_y + 31,
            "不确定度必须拆开记录：几何 + 标定 + 运动学 + 跟踪 + 载荷 + 采样；不能只写一个模糊的 margin。",
            9.3,
            MUTED,
        )
    )

    # Bottom-left: concrete example.
    left_x, bottom_y, left_w, bottom_h = 36, 590, 700, 203
    items.append(Rect(left_x, bottom_y, left_w, bottom_h, PANEL, LINE, 15, 0.9))
    items.append(Text(left_x + 18, bottom_y + 14, "看一个具体动作：robot_tank_pick(tank_id=1)", 13.5, WHITE, True))
    items.append(Text(left_x + 18, bottom_y + 39, "先固定 rail slot 5 和 P1 锚点，再读取机器人与工具阶段。", 9.8, MUTED))

    timeline_y = bottom_y + 86
    node_xs = [left_x + 47, left_x + 230, left_x + 438, left_x + 642]
    node_colors = [BLUE, GREEN, PURPLE, BLUE]
    node_labels = ["P1", "P75 …", "吸附", "P1"]
    node_notes = ["起始锚点", "14 个 waypoint", "plate-attached", "终点仍携带板"]
    for index in range(len(node_xs) - 1):
        items.append(Line(node_xs[index] + 14, timeline_y, node_xs[index + 1] - 14, timeline_y, "#3B718A", 2))
        mid_x = (node_xs[index] + node_xs[index + 1]) / 2
        items.append(Polygon(((mid_x - 2, timeline_y - 4), (mid_x + 4, timeline_y), (mid_x - 2, timeline_y + 4)), "#3B718A"))
    for x, color, label, note in zip(node_xs, node_colors, node_labels, node_notes, strict=True):
        items.append(Circle(x, timeline_y, 14, SOFT_FILL[color], color, 1.3))
        items.append(Text(x, timeline_y - 5, label, 9.5, WHITE, True, "middle"))
        items.append(Text(x, timeline_y + 22, note, 8.5, MUTED, False, "middle"))

    chip_y = bottom_y + 137
    chips = [
        ("rotary-down", PURPLE, 92),
        ("suction-on", CYAN, 82),
        ("payload: plate-attached", AMBER, 144),
    ]
    chip_x = left_x + 18
    for label, color, width in chips:
        status_chip(items, chip_x, chip_y, label, color, width)
        chip_x += width + 10

    result_x = left_x + 377
    items.append(Rect(result_x, chip_y - 1, 305, 49, "#2A2338", PURPLE, 10, 0.9))
    items.append(Text(result_x + 13, chip_y + 6, "SHADOW DECISION", 8.5, MUTED, True))
    items.append(Text(result_x + 13, chip_y + 24, "UNKNOWN", 12.5, AMBER, True))
    items.append(Text(result_x + 116, chip_y + 25, "effect = none", 10.5, WHITE, True))
    items.append(Text(result_x + 216, chip_y + 25, "✓ 失败关闭", 9.5, GREEN, True))

    # Bottom-right: why unknown and safety boundary.
    right_x, right_w = 752, PAGE_W - 788
    items.append(Rect(right_x, bottom_y, right_w, bottom_h, "#171F30", PURPLE, 15, 0.9))
    items.append(Text(right_x + 18, bottom_y + 14, "为什么 UNKNOWN 才是正确答案？", 13.5, WHITE, True))
    reasons = [
        ("1", "waypoint 序列 ≠ 控制器真实连续轨迹"),
        ("2", "静态代理 ≠ 动态机器人碰撞世界"),
        ("3", "还没有经过验证的停止模型"),
    ]
    reason_y = bottom_y + 48
    for number, reason in reasons:
        items.append(Circle(right_x + 29, reason_y + 9, 10, SOFT_FILL[PURPLE], PURPLE, 1))
        items.append(Text(right_x + 29, reason_y + 3.5, number, 8.5, PURPLE, True, "middle"))
        items.append(Text(right_x + 49, reason_y + 2.5, reason, 9.8, WHITE))
        reason_y += 31

    safe_y = bottom_y + 147
    items.append(Rect(right_x + 17, safe_y, right_w - 34, 41, "#35262A", RED, 10, 0.8))
    items.append(Text(right_x + 29, safe_y + 7, "安全边界", 9.5, RED, True))
    items.append(Text(right_x + 96, safe_y + 7, "UI 只展示证据；PLC / 控制器 / 急停硬链保持独立。", 8.8, WHITE))
    items.append(Text(right_x + 29, safe_y + 24, "没有 collision / trajectory / stop 资格，就绝不输出 model_allowed。", 8.6, MUTED))

    # Footer.
    items.append(Line(36, 809, PAGE_W - 36, 809, LINE, 0.8))
    items.append(
        Text(
            36,
            818,
            "成熟度：SP0 initial slice DONE   ·   SP1 static scene PARTIAL   ·   SP2 waypoint parser PARTIAL   ·   hardware-qualified NO",
            8.3,
            MUTED,
        )
    )
    items.append(
        Text(
            PAGE_W - 36,
            818,
            "证据基线：Design & Plan v2 · spatial shadow initial report · 2026-08-28",
            8.3,
            MUTED,
            False,
            "end",
        )
    )
    return items


def render_pdf(items: list[Primitive], path: Path) -> None:
    _register_fonts()
    pdf = canvas.Canvas(str(path), pagesize=(PAGE_W, PAGE_H), pageCompression=1)
    pdf.setTitle("UniLab 空间约束自动计算海报")
    pdf.setAuthor("UniLab / Codex")
    for item in items:
        if isinstance(item, Rect):
            pdf.setFillColor(item.fill)
            pdf.setStrokeColor(item.stroke or item.fill)
            pdf.setLineWidth(item.stroke_width)
            y = PAGE_H - item.y - item.h
            if item.radius:
                pdf.roundRect(item.x, y, item.w, item.h, item.radius, fill=1, stroke=1 if item.stroke else 0)
            else:
                pdf.rect(item.x, y, item.w, item.h, fill=1, stroke=1 if item.stroke else 0)
        elif isinstance(item, Text):
            pdf.setFont("PosterCN-Bold" if item.bold else "PosterCN", item.size)
            pdf.setFillColor(item.color)
            width = pdfmetrics.stringWidth(item.value, "PosterCN-Bold" if item.bold else "PosterCN", item.size)
            x = item.x
            if item.anchor == "middle":
                x -= width / 2
            elif item.anchor == "end":
                x -= width
            pdf.drawString(x, PAGE_H - item.y - item.size, item.value)
        elif isinstance(item, Line):
            pdf.setStrokeColor(item.color)
            pdf.setLineWidth(item.width)
            pdf.setDash(4, 3) if item.dashed else pdf.setDash()
            pdf.line(item.x1, PAGE_H - item.y1, item.x2, PAGE_H - item.y2)
            pdf.setDash()
        elif isinstance(item, Circle):
            pdf.setFillColor(item.fill)
            pdf.setStrokeColor(item.stroke or item.fill)
            pdf.setLineWidth(item.stroke_width)
            pdf.circle(item.cx, PAGE_H - item.cy, item.r, fill=1, stroke=1 if item.stroke else 0)
        elif isinstance(item, Polygon):
            path_obj = pdf.beginPath()
            first_x, first_y = item.points[0]
            path_obj.moveTo(first_x, PAGE_H - first_y)
            for x, y in item.points[1:]:
                path_obj.lineTo(x, PAGE_H - y)
            path_obj.close()
            pdf.setFillColor(item.fill)
            pdf.drawPath(path_obj, fill=1, stroke=0)
    pdf.showPage()
    pdf.save()


def render_svg(items: list[Primitive], path: Path) -> None:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{PAGE_W:.2f}" '
            f'height="{PAGE_H:.2f}" viewBox="0 0 {PAGE_W:.2f} {PAGE_H:.2f}">'
        ),
        "<title>UniLab 空间约束自动计算海报</title>",
    ]
    font_family = "'STHeiti','PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif"
    for item in items:
        if isinstance(item, Rect):
            stroke = item.stroke or "none"
            parts.append(
                f'<rect x="{item.x:.2f}" y="{item.y:.2f}" width="{item.w:.2f}" height="{item.h:.2f}" '
                f'rx="{item.radius:.2f}" fill="{item.fill}" stroke="{stroke}" stroke-width="{item.stroke_width:.2f}"/>'
            )
        elif isinstance(item, Text):
            anchor = {"start": "start", "middle": "middle", "end": "end"}[item.anchor]
            weight = "700" if item.bold else "400"
            parts.append(
                f'<text x="{item.x:.2f}" y="{item.y + item.size:.2f}" fill="{item.color}" '
                f'font-family="{font_family}" font-size="{item.size:.2f}" font-weight="{weight}" '
                f'text-anchor="{anchor}" letter-spacing="{item.letter_spacing:.2f}">{html.escape(item.value)}</text>'
            )
        elif isinstance(item, Line):
            dash = ' stroke-dasharray="4 3"' if item.dashed else ""
            parts.append(
                f'<line x1="{item.x1:.2f}" y1="{item.y1:.2f}" x2="{item.x2:.2f}" y2="{item.y2:.2f}" '
                f'stroke="{item.color}" stroke-width="{item.width:.2f}"{dash}/>'
            )
        elif isinstance(item, Circle):
            stroke = item.stroke or "none"
            parts.append(
                f'<circle cx="{item.cx:.2f}" cy="{item.cy:.2f}" r="{item.r:.2f}" fill="{item.fill}" '
                f'stroke="{stroke}" stroke-width="{item.stroke_width:.2f}"/>'
            )
        elif isinstance(item, Polygon):
            points = " ".join(f"{x:.2f},{y:.2f}" for x, y in item.points)
            parts.append(f'<polygon points="{points}" fill="{item.fill}"/>')
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    primitives = build_primitives()
    render_pdf(primitives, PDF_PATH)
    render_svg(primitives, SVG_PATH)
    print(PDF_PATH)
    print(SVG_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
