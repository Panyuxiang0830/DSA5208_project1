#!/usr/bin/env python3
"""Generate the Chinese and English final project reports as polished PDFs.

Every table and every headline statistic in this report is computed from the
committed machine-readable summaries in ``results/summary/*.json`` (and the
election/replication-lag timings in
``results/summary/extended_fault_timings.csv``) at build time -- nothing here
is retyped by hand. If the underlying experiments are rerun and the summary
files change, rerunning this script picks up the new numbers automatically.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path
from statistics import mean
from typing import Any

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    Image,
    KeepTogether,
    LongTable,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pdf"
SUMMARY_DIR = ROOT / "results" / "summary"
# Optional extra copy of the built PDFs (e.g. a personal sync folder). Unset by
# default so the build never fails or writes outside the repo on someone
# else's machine; set REPORT_EXTRA_OUTPUT_DIR to opt in.
USER_OUT = Path(os.environ["REPORT_EXTRA_OUTPUT_DIR"]).expanduser() if os.environ.get(
    "REPORT_EXTRA_OUTPUT_DIR"
) else None
FIG = ROOT / "results" / "figures"

# Candidate Unicode/CJK font files, checked in order. The first one that both
# exists on disk AND can be loaded by reportlab's pure-Python TrueType parser
# (which cannot read PostScript/CFF outlines, so most Linux "Noto ... CJK"
# packages are skipped in favor of a TrueType-outline fallback) is used. This
# lets the report build on the original author's Mac, on a teammate's Linux
# or Windows machine, and in CI without editing the script. Override with the
# REPORT_FONT_PATH environment variable to force a specific file.
FONT_CANDIDATES = [
    os.environ.get("REPORT_FONT_PATH"),
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",  # macOS
    "/System/Library/Fonts/STHeiti Light.ttc",  # macOS (Chinese)
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",  # Debian/Ubuntu (fonts-wqy-zenhei)
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # Debian/Ubuntu (fonts-wqy-microhei)
    "C:/Windows/Fonts/msyh.ttc",  # Windows (Microsoft YaHei)
    "C:/Windows/Fonts/simhei.ttf",  # Windows (SimHei)
]

NAVY = colors.HexColor("#123047")
BLUE = colors.HexColor("#1F6F8B")
TEAL = colors.HexColor("#2A9D8F")
PALE = colors.HexColor("#EAF3F6")
PALE2 = colors.HexColor("#F4F7F8")
ORANGE = colors.HexColor("#E07A5F")
INK = colors.HexColor("#24323A")
MUTED = colors.HexColor("#5F6F78")
GRID = colors.HexColor("#C9D7DC")


def register_fonts() -> None:
    """Register a CJK-capable TrueType font under the name "ArialUnicode".

    Tries REPORT_FONT_PATH and a list of common macOS/Linux/Windows font
    locations, skipping files that don't exist and files reportlab's
    TrueType parser cannot read (e.g. CFF-outline .otf/.ttc). Raises a clear,
    actionable error only if nothing usable was found.
    """
    tried: list[str] = []
    for candidate in FONT_CANDIDATES:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.exists():
            continue
        tried.append(str(path))
        try:
            pdfmetrics.registerFont(TTFont("ArialUnicode", str(path)))
            return
        except Exception:
            continue
    raise FileNotFoundError(
        "No usable CJK TrueType font was found. Checked: "
        + (", ".join(tried) if tried else "no candidate paths existed")
        + ". Install a CJK font (e.g. `sudo apt install fonts-wqy-zenhei` on "
        "Debian/Ubuntu, or Microsoft YaHei on Windows) or set the "
        "REPORT_FONT_PATH environment variable to a .ttf/.ttc file with "
        "TrueType (not PostScript/CFF) outlines."
    )


def load_one(pattern: str) -> dict[str, Any]:
    """Load the single results/summary/*.json file matching pattern."""
    matches = sorted(SUMMARY_DIR.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one summary file for {pattern!r}, found {matches}")
    return json.loads(matches[0].read_text(encoding="utf-8"))


def load_many(pattern: str) -> list[dict[str, Any]]:
    """Load every results/summary/*.json file matching pattern, sorted by name."""
    matches = sorted(SUMMARY_DIR.glob(pattern))
    if not matches:
        raise RuntimeError(f"No summary files matched {pattern!r}")
    return [json.loads(path.read_text(encoding="utf-8")) for path in matches]


def load_fault_timings() -> list[dict[str, str]]:
    path = SUMMARY_DIR / "extended_fault_timings.csv"
    with path.open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def agg_row(summary: dict[str, Any], config_id: str, model: str) -> dict[str, Any]:
    """Return the aggregate row (all seeds combined) for one config/model pair."""
    for row in summary["aggregates"]:
        if row["config_id"] == config_id and row["model"] == model:
            return row
    raise KeyError(f"No aggregate row for config={config_id!r} model={model!r}")


def fmt_int(value: int) -> str:
    return f"{value:,}"


def fmt_rate(violations: int, checks: int) -> str:
    return f"{violations / checks * 100:.2f}%" if checks else "n/a"


class ReportDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, lang: str, report_title: str, **kwargs):
        super().__init__(filename, **kwargs)
        self.lang = lang
        self.report_title = report_title
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="normal",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates(PageTemplate(id="report", frames=frame, onPage=self._page))

    def _page(self, canvas, doc):
        page = canvas.getPageNumber()
        canvas.saveState()
        if page > 1:
            canvas.setStrokeColor(GRID)
            canvas.setLineWidth(0.5)
            canvas.line(doc.leftMargin, A4[1] - 15 * mm, A4[0] - doc.rightMargin, A4[1] - 15 * mm)
            canvas.setFillColor(MUTED)
            canvas.setFont("ArialUnicode" if self.lang == "zh" else "Helvetica", 7.8)
            header = (
                "DSA5208 项目一｜MongoDB 客户端中心一致性"
                if self.lang == "zh"
                else "DSA5208 Project 1 | MongoDB Client-Centric Consistency"
            )
            canvas.drawString(doc.leftMargin, A4[1] - 11.5 * mm, header)
        canvas.setStrokeColor(GRID)
        canvas.line(doc.leftMargin, 13 * mm, A4[0] - doc.rightMargin, 13 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("ArialUnicode" if self.lang == "zh" else "Helvetica", 8)
        label = f"第 {page} 页" if self.lang == "zh" else f"Page {page}"
        canvas.drawCentredString(A4[0] / 2, 8.5 * mm, label)
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph):
            style = flowable.style.name
            if style.startswith("H1"):
                self.notify("TOCEntry", (0, flowable.getPlainText(), self.page))
            elif style.startswith("H2"):
                self.notify("TOCEntry", (1, flowable.getPlainText(), self.page))


class ArchitectureDiagram(Flowable):
    def __init__(self, lang: str, width: float = 170 * mm, height: float = 78 * mm):
        super().__init__()
        self.lang = lang
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        font = "ArialUnicode" if self.lang == "zh" else "Helvetica"
        bold = font if self.lang == "zh" else "Helvetica-Bold"
        c.setStrokeColor(BLUE)
        c.setFillColor(PALE2)
        c.roundRect(0, 0, self.width, self.height, 4 * mm, fill=1, stroke=1)
        c.setFillColor(NAVY)
        c.setFont(bold, 9.5)
        outer = "Google Cloud 新加坡区域｜单台 Compute Engine VM" if self.lang == "zh" else "Google Cloud Singapore region | one Compute Engine VM"
        c.drawString(5 * mm, self.height - 7 * mm, outer)

        net_x, net_y = 5 * mm, 8 * mm
        net_w, net_h = self.width - 10 * mm, self.height - 21 * mm
        c.setFillColor(colors.white)
        c.setStrokeColor(GRID)
        c.roundRect(net_x, net_y, net_w, net_h, 3 * mm, fill=1, stroke=1)
        c.setFillColor(MUTED)
        c.setFont(font, 7.5)
        net = "Docker 私有网络（数据库端口仅绑定 VM 回环地址）" if self.lang == "zh" else "Private Docker network (database ports bound to VM loopback only)"
        c.drawString(net_x + 4 * mm, net_y + net_h - 6 * mm, net)

        box_w, box_h, gap = 38 * mm, 24 * mm, 7 * mm
        start_x = net_x + 4 * mm
        y = net_y + 9 * mm
        labels = [
            ("mongo1\nPrimary / Secondary", TEAL),
            ("mongo2\nPrimary / Secondary", BLUE),
            ("mongo3\nPrimary / Secondary", ORANGE),
        ]
        centers = []
        for i, (label, color) in enumerate(labels):
            x = start_x + i * (box_w + gap)
            centers.append((x + box_w / 2, y + box_h / 2))
            c.setFillColor(colors.Color(color.red, color.green, color.blue, alpha=0.10))
            c.setStrokeColor(color)
            c.roundRect(x, y, box_w, box_h, 2.5 * mm, fill=1, stroke=1)
            c.setFillColor(INK)
            c.setFont(bold, 8.2)
            c.drawCentredString(x + box_w / 2, y + 15 * mm, label.split("\n")[0])
            c.setFont(font, 7)
            c.drawCentredString(x + box_w / 2, y + 10 * mm, label.split("\n")[1])
            c.setFillColor(MUTED)
            c.drawCentredString(x + box_w / 2, y + 4 * mm, "named volume")

        for a, b in [(centers[0], centers[1]), (centers[1], centers[2])]:
            c.setStrokeColor(GRID)
            c.line(a[0] + box_w / 2, a[1], b[0] - box_w / 2, b[1])

        rx = net_x + net_w - 31 * mm
        ry = y + 3 * mm
        c.setFillColor(PALE)
        c.setStrokeColor(BLUE)
        c.roundRect(rx, ry, 27 * mm, 18 * mm, 2.5 * mm, fill=1, stroke=1)
        c.setFillColor(INK)
        c.setFont(bold, 7.7)
        c.drawCentredString(rx + 13.5 * mm, ry + 11.5 * mm, "Python runner")
        c.setFont(font, 6.8)
        c.drawCentredString(rx + 13.5 * mm, ry + 6 * mm, "PyMongo 4.17.0")


def styles(lang: str):
    font = "ArialUnicode" if lang == "zh" else "Helvetica"
    bold = font if lang == "zh" else "Helvetica-Bold"
    mono = "Courier"
    s = getSampleStyleSheet()
    body = ParagraphStyle(
        "BodyZH" if lang == "zh" else "BodyEN",
        parent=s["BodyText"],
        fontName=font,
        fontSize=9.3,
        leading=14.2,
        textColor=INK,
        alignment=TA_JUSTIFY,
        spaceAfter=5.5,
        wordWrap="CJK" if lang == "zh" else None,
    )
    return {
        "body": body,
        "small": ParagraphStyle("Small" + lang, parent=body, fontSize=7.7, leading=10.8, textColor=MUTED),
        "caption": ParagraphStyle("Caption" + lang, parent=body, fontSize=7.8, leading=10.5, alignment=TA_CENTER, textColor=MUTED, spaceBefore=3, spaceAfter=8),
        "h1": ParagraphStyle("H1" + lang, parent=s["Heading1"], fontName=bold, fontSize=17, leading=21, textColor=NAVY, spaceBefore=8, spaceAfter=9, keepWithNext=True, wordWrap="CJK" if lang == "zh" else None),
        "h2": ParagraphStyle("H2" + lang, parent=s["Heading2"], fontName=bold, fontSize=12.5, leading=16, textColor=BLUE, spaceBefore=7, spaceAfter=5, keepWithNext=True, wordWrap="CJK" if lang == "zh" else None),
        "h3": ParagraphStyle("H3" + lang, parent=s["Heading3"], fontName=bold, fontSize=10.4, leading=14, textColor=TEAL, spaceBefore=5, spaceAfter=3, keepWithNext=True, wordWrap="CJK" if lang == "zh" else None),
        "title": ParagraphStyle("Title" + lang, parent=s["Title"], fontName=bold, fontSize=25, leading=31, textColor=NAVY, alignment=TA_LEFT, spaceAfter=8, wordWrap="CJK" if lang == "zh" else None),
        "subtitle": ParagraphStyle("Subtitle" + lang, parent=body, fontName=font, fontSize=13, leading=19, textColor=BLUE, alignment=TA_LEFT),
        "meta": ParagraphStyle("Meta" + lang, parent=body, fontName=font, fontSize=9.2, leading=15, textColor=MUTED),
        "callout": ParagraphStyle(
            "Callout" + lang,
            parent=body,
            fontName=bold,
            fontSize=9.3,
            leading=15.0,
            textColor=NAVY,
            leftIndent=7 * mm,
            rightIndent=7 * mm,
            borderColor=TEAL,
            borderWidth=0.8,
            borderPadding=10,
            backColor=PALE,
            spaceBefore=0,
            spaceAfter=0,
        ),
        "bullet": ParagraphStyle("Bullet" + lang, parent=body, leftIndent=5.5 * mm, firstLineIndent=-3.5 * mm, bulletIndent=0, spaceAfter=3),
        "code": ParagraphStyle(
            "Code" + lang,
            parent=body,
            fontName=mono,
            fontSize=7.1,
            leading=10.8,
            leftIndent=4 * mm,
            rightIndent=4 * mm,
            borderColor=GRID,
            borderWidth=0.5,
            borderPadding=10,
            backColor=PALE2,
            spaceBefore=0,
            spaceAfter=0,
        ),
        "table": ParagraphStyle("Table" + lang, parent=body, fontSize=7.1, leading=9.5, alignment=TA_LEFT, spaceAfter=0),
        "table_head": ParagraphStyle("TableHead" + lang, parent=body, fontName=bold, fontSize=7.2, leading=9.4, textColor=colors.white, alignment=TA_CENTER, spaceAfter=0),
        "ref": ParagraphStyle("Ref" + lang, parent=body, fontSize=7.5, leading=10.5, alignment=TA_LEFT, leftIndent=4 * mm, firstLineIndent=-4 * mm, spaceAfter=4),
    }


def p(text: str, st, **kwargs) -> Paragraph:
    return Paragraph(text, st, **kwargs)


def bullet(text: str, st) -> Paragraph:
    return Paragraph("• " + text, st)


def append_callout(story, text: str, st) -> None:
    """Add a bordered callout with explicit whitespace outside the border."""
    story.append(Spacer(1, 5 * mm))
    story.append(KeepTogether([p(text, st["callout"])]))
    story.append(Spacer(1, 5 * mm))


def append_code_block(story, text: str, st) -> None:
    """Add a code panel with explicit whitespace outside the border."""
    story.append(Spacer(1, 5 * mm))
    story.append(p(text, st["code"]))
    story.append(Spacer(1, 5 * mm))


def make_table(data, widths, st, header=True, aligns=None, font_size=7.0, padding=4):
    rows = []
    for r, row in enumerate(data):
        row_style = st["table_head"] if header and r == 0 else st["table"]
        rows.append([cell if isinstance(cell, Flowable) else p(str(cell), row_style) for cell in row])
    t = LongTable(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY if header else PALE2),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white if header else INK),
        ("GRID", (0, 0), (-1, -1), 0.35, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), padding),
        ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
    ]
    if header and len(rows) > 1:
        for i in range(1, len(rows)):
            if i % 2 == 0:
                commands.append(("BACKGROUND", (0, i), (-1, i), PALE2))
    if aligns:
        for col, align in enumerate(aligns):
            commands.append(("ALIGN", (col, 1 if header else 0), (col, -1), align))
    t.setStyle(TableStyle(commands))
    return t


def figure(path: Path, caption: str, st, width: float = 168 * mm):
    img = Image(str(path))
    ratio = img.imageHeight / img.imageWidth
    img.drawWidth = width
    img.drawHeight = width * ratio
    img.hAlign = "CENTER"
    return KeepTogether([img, p(caption, st["caption"])])


def section(story, title, st, level=1):
    story.append(p(title, st["h1"] if level == 1 else st["h2"] if level == 2 else st["h3"]))


def cover(story, lang: str, st):
    story.extend([Spacer(1, 30 * mm)])
    if lang == "zh":
        story.append(p("DSA5208 可扩展分布式数据科学计算", st["subtitle"]))
        story.append(Spacer(1, 5 * mm))
        story.append(p("MongoDB 可调一致性与<br/>客户端中心一致性实验", st["title"]))
        story.append(Spacer(1, 4 * mm))
        story.append(p("项目一 · 完整实验报告（中文版）", st["subtitle"]))
        meta = "作者：Pan Yuxiang、Hou Jiacheng、Wu Jiarui<br/>提交日期：2026 年 9 月 27 日<br/>实验平台：Google Cloud Compute Engine（新加坡）"
    else:
        story.append(p("DSA5208 Scalable Distributed Computing for Data Science", st["subtitle"]))
        story.append(Spacer(1, 5 * mm))
        story.append(p("Tunable Consistency and<br/>Client-Centric Guarantees in MongoDB", st["title"]))
        story.append(Spacer(1, 4 * mm))
        story.append(p("Project 1 · Complete Experimental Report", st["subtitle"]))
        meta = "Prepared by: Pan Yuxiang, Hou Jiacheng, and Wu Jiarui<br/>Experimental platform: Google Cloud Compute Engine (Singapore)"
    story.append(Spacer(1, 23 * mm))
    story.append(p(meta, st["meta"]))
    story.append(Spacer(1, 20 * mm))
    claim = (
        "核心结论：因果会话配合 majority 读写在成功操作中保持了四项保证；<br/>关闭因果会话后，即使 majority/majority 也会在受控复制延迟下成功返回旧值。"
        if lang == "zh"
        else "Main finding: causal sessions with majority reads and writes preserved all four guarantees for successful operations; without a causal session, even majority/majority returned successful stale reads under controlled replication lag."
    )
    append_callout(story, claim, st)
    story.append(p("Repository: github.com/Panyuxiang0830/DSA5208_project1", st["small"]))
    story.append(PageBreak())


def toc(story, lang, st):
    section(story, "目录" if lang == "zh" else "Table of Contents", st)
    toc_obj = TableOfContents()
    toc_obj.levelStyles = [
        ParagraphStyle(name="TOC1" + lang, fontName="ArialUnicode" if lang == "zh" else "Helvetica-Bold", fontSize=9.3, leading=15, leftIndent=0, firstLineIndent=0, textColor=NAVY),
        ParagraphStyle(name="TOC2" + lang, fontName="ArialUnicode" if lang == "zh" else "Helvetica", fontSize=8.3, leading=13, leftIndent=8 * mm, firstLineIndent=0, textColor=MUTED),
    ]
    story.append(toc_obj)
    story.append(PageBreak())


def load_report_data() -> dict[str, Any]:
    """Load every summary file the report needs and compute derived figures.

    This is the single place that reads results/summary/*.json and
    extended_fault_timings.csv. Every number that appears in the report body
    below is threaded through from here rather than retyped, so rerunning
    this script after new experiments updates the PDF automatically.
    """
    s0 = load_one("baseline-s0-formal-*.summary.json")
    s1 = load_one("s1-secondary-failure-formal-*.summary.json")
    s2 = load_one("s2-primary-failure-formal-*.summary.json")
    s3 = load_one("s3-primary-partition-formal-rerun-*.summary.json")
    s4 = load_one("s4-secondary-replication-lag-formal-*.summary.json")
    t1_runs = load_many("t1-primary-stop-transition-formal-rerun-*.summary.json")
    t2_runs = load_many("t2-primary-partition-transition-formal-rerun-*.summary.json")
    timings = load_fault_timings()

    # Controlled non-causal concern matrix. C3 already supplies the w:1/local
    # corner from the original GCP run, so the follow-up suite deliberately
    # executes only the three missing corners C5/C6/C8 on the same VM.
    s0_matrix = load_one("s0-normal-noncausal-remote-v2-????????T??????Z-*.summary.json")
    s1_matrix = load_one("s1-secondary-failure-noncausal-remote-v2-????????T??????Z-*.summary.json")
    s2_matrix = load_one("s2-primary-failure-noncausal-remote-v2-????????T??????Z-*.summary.json")
    s3_matrix = load_one("s3-primary-partition-noncausal-remote-v2-????????T??????Z-*.summary.json")
    s4_matrix = load_one("s4-secondary-replication-lag-noncausal-remote-v2-????????T??????Z-*.summary.json")
    t1_matrix_runs = load_many(
        "t1-primary-stop-transition-noncausal-remote-v2-seed-*-????????T??????Z-*.summary.json"
    )
    t2_matrix_runs = load_many(
        "t2-primary-partition-transition-noncausal-remote-v2-seed-*-????????T??????Z-*.summary.json"
    )

    def election_ms(scenario_label: str) -> list[float]:
        return [
            float(row["value_ms"])
            for row in timings
            if row["scenario"] == scenario_label and row["metric"] == "election duration"
        ]

    def combined_totals(runs: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "checks": sum(r["totals"]["check_count"] for r in runs),
            "violations": sum(r["totals"]["violation_count"] for r in runs),
            "errors": sum(r["totals"]["error_count"] for r in runs),
        }

    def phase_totals(runs: list[dict[str, Any]], config_id: str = "C3") -> dict[str, dict[str, int]]:
        totals = {
            phase: {"violations": 0, "checks": 0}
            for phase in ("pre-fault", "election", "post-election")
        }
        for run in runs:
            for row in run["phase_rows"]:
                if row["config_id"] != config_id:
                    continue
                totals[row["phase"]]["violations"] += int(row["violation_count"])
                totals[row["phase"]]["checks"] += int(row["check_count"])
        return totals

    lag = {row["metric"]: float(row["value_ms"]) for row in timings if row["scenario"] == "S4 replication lag"}

    def transition_totals_for_config(runs: list[dict[str, Any]], config_id: str) -> dict[str, int]:
        rows = [agg_row(run, config_id, "read-your-writes-transition") for run in runs]
        return {
            "checks": sum(r["check_count"] for r in rows),
            "violations": sum(r["violation_count"] for r in rows),
            "errors": sum(r["error_count"] for r in rows),
        }

    return {
        "s0": s0, "s1": s1, "s2": s2, "s3": s3, "s4": s4,
        "s0_matrix": s0_matrix, "s1_matrix": s1_matrix, "s2_matrix": s2_matrix,
        "s3_matrix": s3_matrix, "s4_matrix": s4_matrix,
        "t1_matrix_runs": t1_matrix_runs, "t2_matrix_runs": t2_matrix_runs,
        "t1_matrix_totals": {
            c: transition_totals_for_config(t1_matrix_runs, c) for c in ("C5", "C6", "C8")
        },
        "t2_matrix_totals": {
            c: transition_totals_for_config(t2_matrix_runs, c) for c in ("C5", "C6", "C8")
        },
        "t1_runs": t1_runs, "t2_runs": t2_runs,
        "t1_elections": election_ms("T1 Primary stopped"),
        "t2_elections": election_ms("T2 Primary partitioned"),
        "t1_totals": combined_totals(t1_runs),
        "t2_totals": combined_totals(t2_runs),
        "t1_phase": phase_totals(t1_runs),
        "t2_phase": phase_totals(t2_runs),
        "t1_errors_per_seed": [r["totals"]["error_count"] for r in t1_runs],
        "t2_errors_per_seed": [r["totals"]["error_count"] for r in t2_runs],
        "s4_lag_end_ms": lag.get("lag at workload end"),
        "s4_catchup_ms": lag.get("catch-up duration"),
    }


def report_content(lang: str, st, data: dict[str, Any]):
    z = lang == "zh"
    story = []
    cover(story, lang, st)
    toc(story, lang, st)

    s0, s1, s2, s3, s4 = data["s0"], data["s1"], data["s2"], data["s3"], data["s4"]
    s0_matrix, s1_matrix, s2_matrix, s3_matrix, s4_matrix = (
        data["s0_matrix"], data["s1_matrix"], data["s2_matrix"],
        data["s3_matrix"], data["s4_matrix"],
    )
    ryw, mr, mw, wfr = "read-your-writes", "monotonic-reads", "monotonic-writes", "writes-follow-reads"

    def matrix_agg(
        original_summary: dict[str, Any],
        followup_summary: dict[str, Any],
        config_id: str,
        model: str,
    ) -> dict[str, Any]:
        """Use the original GCP C3 row and follow-up GCP C5/C6/C8 rows."""
        source = original_summary if config_id == "C3" else followup_summary
        return agg_row(source, config_id, model)

    s0_c3_ryw = agg_row(s0, "C3", ryw)
    s0_c3_mr = agg_row(s0, "C3", mr)
    stable_c3_ryw_rates = [
        agg_row(summary, "C3", ryw)["violation_rate"] * 100 for summary in (s1, s2, s3)
    ]
    s4_ryw = agg_row(s4, "C3", ryw)
    s4_mr = agg_row(s4, "C3", mr)
    s4_wfr = agg_row(s4, "C3", wfr)
    s4_c8_ryw = matrix_agg(s4, s4_matrix, "C8", ryw)
    s4_c8_mr = matrix_agg(s4, s4_matrix, "C8", mr)
    s4_c8_wfr = matrix_agg(s4, s4_matrix, "C8", wfr)

    abstract_zh = (
        "本项目在单台 Google Cloud 虚拟机中使用 Docker Compose 部署三节点 MongoDB 8.0.29 副本集，并研究读写关注、读偏好与因果会话对四项客户端中心一致性保证的影响。实验覆盖正常运行、节点故障、网络分区、选举过渡窗口及受控复制延迟。正式基线与稳态故障矩阵对每个配置和模型运行 500 个序列及 3 个随机种子。C1、C2 与 C4 的成功检查未出现违例；弱配置 C3 在正常状态的读己之写违例率为 {s0_ryw_rate}，在 S1-S3 为 {stable_range}。选举窗口产生短暂操作错误，但未在强配置中引入新的成功读异常。S4 将 C3 的读己之写与单调读违例率放大到 {s4_ryw_rate} 与 {s4_mr_rate}；无因果会话且使用 majority/majority 的 C8 仍出现 {c8_ryw_rate} 的读己之写与 {c8_mr_rate} 的单调读违例。S4 中约 50% 的写跟随读标记主要来自被冻结副本返回空文档后代码赋值 -1，不能作为正式 WFR 违例率；本实验未验证后续写在已读版本之前执行。结果支持对会话顺序与副本可见性的区分，但零违例也不是对所有历史的形式证明。"
    ).format(
        s0_ryw_rate=fmt_rate(s0_c3_ryw["violation_count"], s0_c3_ryw["check_count"]),
        stable_range=f"{min(stable_c3_ryw_rates):.2f}%-{max(stable_c3_ryw_rates):.2f}%",
        s4_ryw_rate=fmt_rate(s4_ryw["violation_count"], s4_ryw["check_count"]),
        s4_mr_rate=fmt_rate(s4_mr["violation_count"], s4_mr["check_count"]),
        s4_wfr_rate=fmt_rate(s4_wfr["violation_count"], s4_wfr["check_count"]),
        c8_ryw_rate=fmt_rate(s4_c8_ryw["violation_count"], s4_c8_ryw["check_count"]),
        c8_mr_rate=fmt_rate(s4_c8_mr["violation_count"], s4_c8_mr["check_count"]),
        c8_wfr_rate=fmt_rate(s4_c8_wfr["violation_count"], s4_c8_wfr["check_count"]),
    )
    abstract_en = (
        "This project deploys a three-member MongoDB 8.0.29 replica set with Docker Compose on one Google Cloud virtual machine and studies how read/write concerns, read preference, and causal sessions affect four client-centric guarantees. The suite covers normal operation, node failures, a network partition, election windows, and controlled replication lag. Formal baseline and stable-fault runs use 500 sequences and three seeds per configuration-model pair. C1, C2, and C4 showed no violations in successful checks. Weak configuration C3 produced {s0_ryw_rate} read-your-writes violations in normal operation and {stable_range} under stable faults. Elections caused transient operation errors but no new successful-read anomaly in strong configurations. Under S4, C3 read-your-writes and monotonic-read violation rates rose to {s4_ryw_rate} and {s4_mr_rate}; non-causal C8 still showed {c8_ryw_rate} read-your-writes and {c8_mr_rate} monotonic-read violations despite majority/majority concerns. The approximately 50% writes-follow-reads (WFR) flags in S4 largely arise when a paused replica returns no document and the checker substitutes version -1. They are not a valid WFR violation rate: the experiment did not establish that a later write executed before a version actually read. The results distinguish session order from replica visibility, while zero observed violations are not a proof over all histories."
    ).format(
        s0_ryw_rate=fmt_rate(s0_c3_ryw["violation_count"], s0_c3_ryw["check_count"]),
        stable_range=f"{min(stable_c3_ryw_rates):.2f}%-{max(stable_c3_ryw_rates):.2f}%",
        s4_ryw_rate=fmt_rate(s4_ryw["violation_count"], s4_ryw["check_count"]),
        s4_mr_rate=fmt_rate(s4_mr["violation_count"], s4_mr["check_count"]),
        s4_wfr_rate=fmt_rate(s4_wfr["violation_count"], s4_wfr["check_count"]),
        c8_ryw_rate=fmt_rate(s4_c8_ryw["violation_count"], s4_c8_ryw["check_count"]),
        c8_mr_rate=fmt_rate(s4_c8_mr["violation_count"], s4_c8_mr["check_count"]),
        c8_wfr_rate=fmt_rate(s4_c8_wfr["violation_count"], s4_c8_wfr["check_count"]),
    )

    section(story, "摘要" if z else "Abstract", st)
    abstract = (
        abstract_zh
        if z else
        abstract_en
    )
    story.append(p(abstract, st["body"]))
    story.append(p(("关键词：MongoDB；副本集；可调一致性；因果一致性；故障注入；复制延迟" if z else "Keywords: MongoDB; replica sets; tunable consistency; causal consistency; fault injection; replication lag"), st["small"]))

    section(story, "1. 项目目标与研究问题" if z else "1. Objectives and Research Questions", st)
    story.append(p(
        "课程任务要求搭建一个支持可调一致性的复制型分布式数据库，在正常运行、节点故障和网络分区下预测并检验应用观察到的客户端中心一致性。本项目选择 MongoDB，因为其驱动层同时暴露会话、读关注、写关注和读偏好，能够把抽象一致性模型映射为可复现的客户端配置。" if z else
        "The assignment requires a replicated database with tunable consistency, predictions about client-observed guarantees, and experiments under normal operation, node failures, and a network partition. MongoDB was selected because its driver exposes sessions, read concern, write concern, and read preference, allowing abstract consistency models to be mapped to reproducible client configurations.", st["body"]))
    questions = [
        "不同配置是否保持读己之写（RYW）、单调读（MR）、单调写（MW）与写跟随读（WFR）？",
        "固定为无因果会话和相同的 Secondary 读取顺序时，read concern 与 write concern 各自如何改变可见异常？",
        "稳定故障状态与选举过渡窗口分别如何影响一致性和可用性？",
        "受控复制延迟能否把偶发的旧读放大为稳定、可解释的异常？",
    ] if z else [
        "Which configurations preserve read-your-writes (RYW), monotonic reads (MR), monotonic writes (MW), and writes-follow-reads (WFR)?",
        "With non-causal sessions and Secondary read order held fixed, how do read concern and write concern change the anomalies observed by the client?",
        "How do stable degraded states and election transition windows differ in their effects on consistency and availability?",
        "Can controlled replication lag amplify occasional stale reads into stable, explainable anomalies?",
    ]
    for item in questions:
        story.append(bullet(item, st["bullet"]))

    section(story, "2. 背景：四项客户端中心一致性" if z else "2. Background: Four Client-Centric Guarantees", st)
    story.append(p(
        "四项保证是同一因果一致性框架中的并列会话保证，并不是简单的单轴强弱排序。一个系统可能满足其中一项而不满足另一项；因果一致性通常要求四项共同成立。下表给出本项目的可执行判定。" if z else
        "The four guarantees are complementary session guarantees within causal consistency, not a simple one-dimensional strength ranking. A system may satisfy one while violating another; causal consistency is commonly characterized by all four together. The table gives the executable checks used here.", st["body"]))
    model_data = [[
        "模型" if z else "Model", "应用期望" if z else "Application expectation", "实验判定" if z else "Operational check"
    ],
    ["RYW", "客户端写入后应读到该写或更新版本。" if z else "After writing, the client reads that version or newer.", "observed_version < acknowledged_version"],
    ["MR", "同一客户端后续读取不能回到更旧版本。" if z else "Successive reads by one client never go backwards.", "later_version < earlier_version"],
    ["MW", "同一客户端的写入按发出顺序生效。" if z else "Writes from one client take effect in issue order.", "acknowledged history/final version out of order"],
    ["WFR", "读取后发出的依赖写必须建立在所读版本之上。" if z else "A dependent write is ordered after the version it read.", "parent missing/stale predicate/dependent write missing"],
    ]
    story.append(make_table(model_data, [20*mm, 68*mm, 79*mm], st))

    section(story, "3. 数据库与部署架构" if z else "3. Database and Deployment Architecture", st)
    section(story, "3.1 软件与云资源" if z else "3.1 Software and Cloud Resources", st, 2)
    env_data = [["项目项" if z else "Item", "采用配置" if z else "Configuration"],
        ["云平台" if z else "Cloud", ("Google Cloud Compute Engine；项目 nifty-pursuit-505911-n0" if z else "Google Cloud Compute Engine; project nifty-pursuit-505911-n0")],
        ["虚拟机" if z else "VM", ("dsa5208-mongodb；asia-southeast1-b（Singapore）；e2-standard-2；2 vCPU；8 GB RAM" if z else "dsa5208-mongodb; asia-southeast1-b (Singapore); e2-standard-2; 2 vCPU; 8 GB RAM")],
        ["系统" if z else "OS", ("Ubuntu 24.04.4 LTS；Linux 6.17.0-1022-gcp" if z else "Ubuntu 24.04.4 LTS; Linux 6.17.0-1022-gcp")],
        ["存储" if z else "Storage", ("30 GB balanced persistent disk；MongoDB named volumes" if z else "30 GB balanced persistent disk; MongoDB named volumes")],
        ["容器" if z else "Containers", ("Docker Engine 29.7.2；Docker Compose v5.5.0" if z else "Docker Engine 29.7.2; Docker Compose v5.5.0")],
        ["数据库" if z else "Database", ("MongoDB Community 8.0.29；three data-bearing voting members；no arbiter" if z else "MongoDB Community 8.0.29; three data-bearing voting members; no arbiter")],
        ["客户端" if z else "Client", ("Python 3.12-slim；PyMongo 4.17.0" if z else "Python 3.12-slim; PyMongo 4.17.0")],
        ["资源限制" if z else "Limits", "每个 mongod 容器 1536 MB RAM；WiredTiger cache 0.5 GB" if z else "1536 MB RAM per mongod container; 0.5 GB WiredTiger cache"],
    ]
    story.append(make_table(env_data, [38*mm, 129*mm], st))
    story.append(Spacer(1, 4*mm))
    story.append(ArchitectureDiagram(lang))
    story.append(p("图 1. 实验部署架构。三个 MongoDB 容器共享一台 VM，但具有独立容器、进程和持久卷。" if z else "Figure 1. Experimental deployment. The three MongoDB members use separate containers, processes, and persistent volumes, but share one VM.", st["caption"]))
    story.append(p(
        "该方案满足“复制型分布式数据库”的逻辑部署要求，并便于确定性注入容器停机与容器网络分区。数据库端口仅绑定虚拟机回环地址，外部网络不直接暴露 MongoDB。其主要代价是节点共享宿主机、磁盘与底层网络，因此不能代表跨主机故障独立性。" if z else
        "This design provides a logically replicated deployment and deterministic container-stop and container-network fault injection. Database ports are bound only to VM loopback and are not exposed directly to the public network. Its main trade-off is shared host, disk, and underlying network resources, so it does not model physical fault independence.", st["body"]))

    section(story, "3.2 安装与初始化" if z else "3.2 Installation and Initialization", st, 2)
    install = """git clone https://github.com/Panyuxiang0830/DSA5208_project1.git
cd DSA5208_project1
./scripts/bootstrap-ubuntu.sh
cp .env.example .env
docker compose pull
docker compose up -d --wait mongo1 mongo2 mongo3
docker compose run --rm mongo-init
./scripts/cluster_status.sh
docker compose build runner
docker compose run --rm --no-deps runner"""
    append_code_block(story, install.replace("\n", "<br/>"), st)
    story.append(p(
        "初始化脚本创建三名投票且存储数据的副本集成员。正常状态下一个节点为 Primary、两个节点为 Secondary；选举由 MongoDB 副本集协议负责。容器删除或重启不会删除 named volume，因此数据库文件在常规恢复流程中保留。" if z else
        "The initialization script creates three voting, data-bearing replica-set members. Under normal operation one member is Primary and two are Secondary; MongoDB's replica-set protocol controls elections. Removing or restarting containers does not remove named volumes, so database files survive normal recovery procedures.", st["body"]))

    section(story, "4. 一致性配置与预测" if z else "4. Consistency Configurations and Predictions", st)
    story.append(p(
        "MongoDB 的 write concern 决定写入在何种复制确认条件下返回；read concern 决定读取允许观察的数据可见性；read preference 决定读取路由到 Primary 还是 Secondary；因果会话则由驱动携带因果时间信息。MongoDB 文档说明，在因果一致会话中配合 majority 读写关注，可以跨成员提供 RYW、MR、MW 与 WFR。" if z else
        "MongoDB write concern controls when replication acknowledgment is sufficient, read concern controls the visibility level that reads may observe, read preference routes reads to primary or secondary members, and causal sessions carry causal time through the driver. MongoDB documents that causally consistent sessions combined with majority read and write concerns provide RYW, MR, MW, and WFR across members.", st["body"]))
    config_data = [[
        "配置" if z else "Config", "会话" if z else "Session", "写关注" if z else "Write concern", "读关注" if z else "Read concern", "读偏好" if z else "Read preference", "预测" if z else "Prediction"
    ],
    ["C1", "因果" if z else "Causal", "majority", "majority", "primary", "四项均成立" if z else "All four hold"],
    ["C2", "因果" if z else "Causal", "majority", "majority", "secondary", "四项均成立；可能等待副本" if z else "All four hold; may wait for replica"],
    ["C3", "无因果" if z else "Non-causal", "w: 1", "local", "secondaryPreferred / Secondary", "RYW、MR、WFR 可能违例；MW 通常成立" if z else "RYW/MR/WFR may fail; MW usually holds"],
    ["C4", "无因果" if z else "Non-causal", "majority", "majority", "primary", "本负载中预期四项成立；不等同通用因果会话" if z else "Expected to hold here; not equivalent to general causal session"],
    ["C5", "无因果" if z else "Non-causal", "w: 1", "majority", "定向交替 Secondary" if z else "Directed alternating Secondary", "检验 majority 读关注相对 C3 的作用" if z else "Tests majority read concern against C3"],
    ["C6", "无因果" if z else "Non-causal", "majority", "local", "定向交替 Secondary" if z else "Directed alternating Secondary", "检验 majority 写关注相对 C3 的作用" if z else "Tests majority write concern against C3"],
    ["C8", "无因果" if z else "Non-causal", "majority", "majority", "定向交替 Secondary" if z else "Directed alternating Secondary", "矩阵中最强关注组合；仍非因果会话" if z else "Strongest matrix concerns; still non-causal"],
    ]
    story.append(make_table(config_data, [13*mm, 22*mm, 24*mm, 24*mm, 38*mm, 46*mm], st))
    story.append(p(
        "配置分为两个相互衔接的实验组。C1-C4 是覆盖会话、路由与关注设置的代表性主实验；C3、C5、C6、C8 则构成受控的 2×2 矩阵。后四者都关闭因果会话，并按固定次序在可达 Secondary 间交替读取，只改变 write concern（w:1/majority）与 read concern（local/majority）。C3 同时属于两组，直接复用原正式数据而不重复实验。该矩阵用于归因关注设置对本负载中可见异常的影响，而不把 majority 误写成通用会话保证。" if z else
        "The configurations form two connected experimental groups. C1-C4 are representative main configurations spanning session, routing, and concern choices. C3, C5, C6, and C8 form a controlled 2x2 matrix: all disable causal consistency and alternate reads across reachable Secondaries in the same deterministic order, while only write concern (w:1/majority) and read concern (local/majority) vary. C3 belongs to both groups, so its existing formal data is reused rather than rerun. The matrix attributes workload-visible differences to concern settings without treating majority as a general session guarantee.", st["body"]))

    section(story, "5. 实验设计" if z else "5. Experimental Design", st)
    section(story, "5.1 工作负载与测量" if z else "5.1 Workloads and Measurement", st, 2)
    story.append(p(
        "每个测试文档包含单调递增的版本号、写入者/运行标识和依赖字段。运行器记录每次数据库操作的开始时间、结束时间、结果、错误、读取成员与模型判定，并输出原始 JSONL、汇总 JSON 和 Markdown 摘要。每次正式基线/稳态故障实验对每个配置-模型组合运行 500 个序列，使用随机种子 20260830、20260831 与 20260832，共 1,500 次主要检查。所有数据库操作错误与一致性违例分开统计：错误表示请求未成功完成，违例只针对可判定的成功历史。" if z else
        "Each test document carries a monotonically increasing version, writer/run identifiers, and dependency fields. The runner records operation start/end times, results, errors, serving member, and model verdicts, then emits raw JSONL, summary JSON, and Markdown. Every formal baseline/stable-fault run executes 500 sequences per configuration-model pair for seeds 20260830, 20260831, and 20260832, yielding 1,500 principal checks. Database operation errors are counted separately from consistency violations: an error is an unavailable request, while a violation is evaluated only on a successful, decidable history.", st["body"]))
    scenario_data = [["场景" if z else "Scenario", "故障/控制" if z else "Fault or control", "测量目的" if z else "Purpose"],
        ["S0", "无故障" if z else "No fault", "建立正常运行基线" if z else "Normal-operation baseline"],
        ["S1", "停止一个 Secondary" if z else "Stop one Secondary", "验证多数派仍存活时的稳态行为" if z else "Stable behavior with a live majority"],
        ["S2", "停止原 Primary，等待选举完成" if z else "Stop old Primary; wait for election", "选举后两节点拓扑" if z else "Post-election two-member topology"],
        ["S3", "将原 Primary 与多数派及客户端断开" if z else "Disconnect old Primary from majority and client", "Primary 侧网络分区后的稳态" if z else "Stable state after a primary-side partition"],
        ["T1", "停止 Primary 时持续发送 RYW" if z else "Continuous RYW during Primary stop", "测量选举窗口的一致性与可用性" if z else "Consistency and availability during election"],
        ["T2", "分区 Primary 时持续发送 RYW" if z else "Continuous RYW during Primary partition", "测量网络分区选举窗口" if z else "Partition-triggered election window"],
        ["S4", "冻结一个可读 Secondary 的复制应用" if z else "Freeze apply on one readable Secondary", "放大可解释的旧读" if z else "Amplify explainable stale reads"],
    ]
    story.append(make_table(scenario_data, [14*mm, 73*mm, 80*mm], st))

    section(story, "5.2 对照逻辑与避免重复" if z else "5.2 Controlled Comparisons and Reuse", st, 2)
    story.append(p(
        "代表性组回答“实际组合整体表现如何”，受控矩阵回答“只改变读/写关注时发生什么”。矩阵的四个角分别为 C3（w:1/local）、C5（w:1/majority）、C6（majority/local）与 C8（majority/majority）。所有矩阵配置使用相同的无因果会话与定向交替 Secondary 路由，因此可以比较关注设置；C2 虽是有价值的因果强基线，但由驱动选择 Secondary，不能与 C8 宣称为严格的单变量会话消融。新增远程套件只运行 C5、C6、C8，C3 在分析时与它们合并。" if z else
        "The representative group asks how realistic configuration bundles behave; the controlled matrix asks what changes when only read/write concern changes. Its corners are C3 (w:1/local), C5 (w:1/majority), C6 (majority/local), and C8 (majority/majority). Every matrix configuration uses a non-causal session and the same directed alternating-Secondary route, making concern comparisons valid. C2 remains a useful strong causal reference, but its Secondary is selected by the driver, so it is not presented as a strict one-variable session ablation against C8. The follow-up remote suite runs only C5, C6, and C8; C3 is merged at analysis time.", st["body"]))

    section(story, "5.3 故障注入与恢复" if z else "5.3 Fault Injection and Recovery", st, 2)
    story.append(p(
        "S1 与 S2 使用 Docker 停止指定角色的容器。S3 使用 docker network disconnect 将故障前 Primary 从副本集网络断开，使剩余两节点形成多数派并选出新 Primary。T1/T2 在故障前启动所选配置的并发循环，把请求按开始时间标注为 pre、election 或 post。S4 仅在测试专用 compose 覆盖中启用 enableTestCommands=1，并对一个 Secondary 执行 rsSyncApplyStop。非因果矩阵仍按固定次序访问两个 Secondary，因此每个配置在同一调度下交替命中被冻结与正常节点；这是一项受控复制延迟实验，但不是“所有读取都固定到同一节点”。完成后恢复应用、等待追平并重新创建普通容器。每个故障场景结束后均验证三节点健康。" if z else
        "S1 and S2 stop the container holding the selected role. S3 uses docker network disconnect to isolate the pre-fault Primary from the replica-set network; the remaining two members retain a majority and elect a new Primary. T1/T2 start concurrent loops for the selected configurations before fault injection and label requests by operation start time as pre, election, or post. S4 enables enableTestCommands=1 only in a test-specific Compose override and runs rsSyncApplyStop on one Secondary. The non-causal matrix still follows its fixed alternation across two Secondaries, so each configuration encounters the paused and current members under the same schedule; this is controlled replication lag, not a claim that every read is pinned to one node. Apply processing is then resumed, catch-up verified, and normal containers recreated. Every scenario ends with a healthy-three-member check.", st["body"]))
    append_callout(story,
        "设计理由：S0-S3 区分稳态一致性，T1/T2 捕获常被“等待选举完成”掩盖的短暂不可用窗口，S4 则提供可控因果机制，以验证 C3 的异常确实来自副本落后而非测试噪声。" if z else
        "Rationale: S0-S3 isolate stable-state consistency, T1/T2 expose the transient unavailability hidden by waiting for election completion, and S4 provides a controlled causal mechanism showing that C3 anomalies arise from replica lag rather than test noise.", st)

    def other_c3_models(summary: dict[str, Any]) -> str:
        parts = []
        for label, model in (("MR", mr), ("MW", mw), ("WFR", wfr)):
            row = agg_row(summary, "C3", model)
            v, c = row["violation_count"], row["check_count"]
            parts.append(f"{label} 0" if v == 0 else f"{label} {fmt_int(v)}/{fmt_int(c)} ({fmt_rate(v, c)})")
        return "; ".join(parts)

    def strong_violations(summary: dict[str, Any]) -> int:
        return sum(
            agg_row(summary, cfg, model)["violation_count"]
            for cfg in ("C1", "C2", "C4")
            for model in (ryw, mr, mw, wfr)
        )

    def stable_row(label: str, summary: dict[str, Any]) -> list[str]:
        row = agg_row(summary, "C3", ryw)
        return [
            label,
            f"{fmt_int(row['violation_count'])} / {fmt_int(row['check_count'])}",
            fmt_rate(row["violation_count"], row["check_count"]),
            other_c3_models(summary),
            fmt_int(strong_violations(summary)),
        ]

    s0_totals, s1_totals, s2_totals, s3_totals = (
        s0["totals"], s1["totals"], s2["totals"], s3["totals"]
    )

    section(story, "6. 结果" if z else "6. Results", st)
    section(story, "6.1 S0-S3：稳态矩阵" if z else "6.1 S0-S3: Stable-State Matrix", st, 2)
    story.append(p(
        (
            "S0 共完成 {s0_ops} 次数据库操作、{s0_checks} 次一致性检查，错误为 {s0_err}。S1、S2、S3 各完成 {s1_checks}、{s2_checks}、{s3_checks} 次检查，数据库操作错误分别为 {s1_err}、{s2_err}、{s3_err}。C1、C2、C4 在全部场景和四个模型中共有 {strong_total} 次违例；C3 的稳定异常只出现在 RYW。"
            if z else
            "S0 completed {s0_ops} database operations and {s0_checks} consistency checks with {s0_err} errors. S1, S2, and S3 completed {s1_checks}, {s2_checks}, and {s3_checks} checks respectively, with {s1_err}, {s2_err}, and {s3_err} database-operation errors. C1, C2, and C4 recorded {strong_total} violations combined across every model and scenario; the only stable C3 anomaly was RYW."
        ).format(
            s0_ops=fmt_int(s0_totals["operation_count"]), s0_checks=fmt_int(s0_totals["check_count"]), s0_err=s0_totals["error_count"],
            s1_checks=fmt_int(s1_totals["check_count"]), s2_checks=fmt_int(s2_totals["check_count"]), s3_checks=fmt_int(s3_totals["check_count"]),
            s1_err=s1_totals["error_count"], s2_err=s2_totals["error_count"], s3_err=s3_totals["error_count"],
            strong_total=sum(strong_violations(s) for s in (s0, s1, s2, s3)),
        ), st["body"]))
    stable_data = [
        ["场景" if z else "Scenario", "C3 RYW", "违例率" if z else "Rate", "其他 C3 模型" if z else "Other C3 models", "C1/C2/C4"],
        stable_row("S0", s0),
        stable_row("S1", s1),
        stable_row("S2", s2),
        stable_row("S3", s3),
    ]
    story.append(make_table(stable_data, [18*mm, 34*mm, 25*mm, 62*mm, 28*mm], st))
    story.append(Spacer(1, 4*mm))
    story.append(figure(FIG / "01_consistency_violation_matrix.png", "图 2. S0-S4 原始判定率；S4 的 WFR 50% 是无效代理标记，不代表正式违例。" if z else "Figure 2. Raw checker rates for S0-S4; the S4 WFR 50% is an invalid proxy, not an established violation rate.", st))
    story.append(p(
        "S1-S3 的 C3 RYW 率略低于 S0，不代表故障提高了弱配置的一致性。副本数量、被选择的 Secondary 和运行时调度改变了旧副本被抽中的概率；这些率描述的是该部署中的经验频率，而不是协议保证。" if z else
        "The slightly lower C3 RYW rates in S1-S3 do not mean faults strengthened C3. The number of available replicas, the selected Secondary, and runtime scheduling changed the chance of choosing a stale member. These rates are empirical frequencies in this deployment, not protocol guarantees.", st["body"]))

    section(story, "6.2 非因果读写关注矩阵" if z else "6.2 Non-Causal Read/Write Concern Matrix", st, 2)

    def matrix_model_cell(
        original_summary: dict[str, Any],
        followup_summary: dict[str, Any],
        config_id: str,
        *,
        s4: bool = False,
    ) -> str:
        parts = []
        for label, model in (("RYW", ryw), ("MR", mr), ("MW", mw), ("WFR", wfr)):
            row = matrix_agg(original_summary, followup_summary, config_id, model)
            if row["violation_count"]:
                flag = "*" if s4 and model == wfr else ""
                parts.append(f"{label}{flag} {fmt_rate(row['violation_count'], row['check_count'])}")
        return "; ".join(parts) if parts else ("零违例" if z else "No violations")

    def matrix_stable_cell(config_id: str) -> str:
        cells = []
        for label, original_summary, followup_summary in (
            ("S1", s1, s1_matrix), ("S2", s2, s2_matrix), ("S3", s3, s3_matrix)
        ):
            observed = matrix_model_cell(original_summary, followup_summary, config_id)
            if observed not in ("零违例", "No violations"):
                cells.append(f"{label}: {observed}")
        return "; ".join(cells) if cells else ("S1-S3 零违例" if z else "No violations in S1-S3")

    matrix_result_data = [[
        "配置" if z else "Config", "读/写关注" if z else "Read/write concern",
        "S0 观察" if z else "S0 observation", "S1-S3 观察" if z else "S1-S3 observation",
        "S4 观察" if z else "S4 observation",
    ]]
    matrix_settings = {
        "C3": "local / w:1", "C5": "majority / w:1",
        "C6": "local / majority", "C8": "majority / majority",
    }
    for config_id in ("C3", "C5", "C6", "C8"):
        matrix_result_data.append([
            config_id,
            matrix_settings[config_id],
            matrix_model_cell(s0, s0_matrix, config_id),
            matrix_stable_cell(config_id),
            matrix_model_cell(s4, s4_matrix, config_id, s4=True),
        ])
    story.append(p(
        "本组比较不是在主实验之后临时追加一组不同逻辑的配置，而是用 C3 作为桥梁补齐三个缺失的关注组合。四项配置均为无因果会话、相同的定向交替 Secondary 路由；因此表格按场景直接比较 read concern 与 write concern 的经验影响。" if z else
        "This comparison is not a separate experiment with a new logic bolted onto the main study. C3 is the bridge that completes the matrix with three missing concern combinations. All four configurations are non-causal and use the same directed alternating-Secondary route, so the table compares the empirical effect of read and write concern directly across scenarios.", st["body"]))
    story.append(make_table(matrix_result_data, [13*mm, 31*mm, 37*mm, 49*mm, 37*mm], st))
    story.append(Spacer(1, 4*mm))
    story.append(figure(
        FIG / "05_extended_concern_matrix.png",
        "图 3. 非因果 2×2 关注矩阵的原始判定率；S4 WFR 色块是无效代理标记，不代表正式违例。" if z else
        "Figure 3. Raw checker rates for the non-causal 2x2 matrix; S4 WFR cells are invalid proxy flags, not established violations.",
        st,
    ))
    story.append(p(
        "* S4 WFR 的约 50% 源于冻结 Secondary 在文档创建前已暂停复制，空读取被编码为 parent_version = -1 并直接计数；此值仅保留为原始程序输出，不纳入 WFR 一致性结论。" if z else
        "* In S4, the paused Secondary can return no document because replication stopped before document creation. The checker encodes this as parent_version = -1 and counts it directly. The near-50% WFR value is retained only as raw output, not used for a WFR consistency conclusion.",
        st["small"],
    ))

    c3_s4_ryw = matrix_agg(s4, s4_matrix, "C3", ryw)
    c5_s4_ryw = matrix_agg(s4, s4_matrix, "C5", ryw)
    c6_s4_ryw = matrix_agg(s4, s4_matrix, "C6", ryw)
    c8_s4_ryw = matrix_agg(s4, s4_matrix, "C8", ryw)
    story.append(p(
        (
            "S4 的 RYW 违例率依次为 C3 {c3}、C5 {c5}、C6 {c6}、C8 {c8}。C3→C5 与 C6→C8 分别隔离把 read concern 从 local 提升为 majority 的效果；C3→C6 与 C5→C8 则隔离把 write concern 从 w:1 提升为 majority 的效果。无论差异大小，解释边界相同：majority 写关注解决确认耐久性，majority 读关注限制可见数据，但在无因果会话且读取落后 Secondary 时，两者单独或组合都不是 RYW/MR/WFR 的通用保证。" if z else
            "Under S4, RYW violation rates were C3 {c3}, C5 {c5}, C6 {c6}, and C8 {c8}. C3→C5 and C6→C8 isolate raising read concern from local to majority; C3→C6 and C5→C8 isolate raising write concern from w:1 to majority. Whatever the measured magnitude, the interpretation boundary is the same: majority write concern addresses acknowledged durability and majority read concern restricts visibility, but without a causal session neither alone nor together is a general RYW/MR/WFR guarantee when reads can reach a lagging Secondary."
        ).format(
            c3=fmt_rate(c3_s4_ryw["violation_count"], c3_s4_ryw["check_count"]),
            c5=fmt_rate(c5_s4_ryw["violation_count"], c5_s4_ryw["check_count"]),
            c6=fmt_rate(c6_s4_ryw["violation_count"], c6_s4_ryw["check_count"]),
            c8=fmt_rate(c8_s4_ryw["violation_count"], c8_s4_ryw["check_count"]),
        ), st["body"]))

    section(story, "6.3 延迟" if z else "6.3 Latency", st, 2)

    def latency_row(config: str) -> list[str]:
        cells = [config]
        for summary in (s0, s1, s2, s3):
            lat = agg_row(summary, config, ryw)["latency_ms"]
            cells.append(f"{lat['p50']:.2f} / {lat['p95']:.2f}")
        return cells

    latency_data = [
        ["配置" if z else "Config", "S0 p50 / p95 (ms)", "S1 p50 / p95", "S2 p50 / p95", "S3 p50 / p95"],
        latency_row("C1"), latency_row("C2"), latency_row("C3"), latency_row("C4"),
    ]
    story.append(make_table(latency_data, [23*mm, 36*mm, 36*mm, 36*mm, 36*mm], st))
    c1_wfr_p95 = agg_row(s0, "C1", wfr)["latency_ms"]["p95"]
    c2_wfr_p95 = agg_row(s0, "C2", wfr)["latency_ms"]["p95"]
    story.append(p(
        (
            "表中为 RYW 单次“写后读”对的端到端延迟。C3 延迟最低，与 w:1/local 不等待多数确认相符；这也是其更弱可见性的代价。C2 的 WFR 基线 p95 为 {c2:.2f} ms，高于 C1 的 {c1:.2f} ms，显示跨 Secondary 因果读取可能等待满足 afterClusterTime。不同故障场景的较低中位数受容器、缓存和运行时波动影响，不应解释为故障优化。"
            if z else
            "The table reports end-to-end latency for one RYW write-read pair. C3 is fastest, consistent with w:1/local avoiding majority waits, but this accompanies weaker visibility. C2's baseline WFR p95 was {c2:.2f} ms versus {c1:.2f} ms for C1, consistent with a causal secondary read sometimes waiting to satisfy afterClusterTime. Lower medians in some fault scenarios reflect container, cache, and runtime variation and should not be interpreted as fault-induced optimization."
        ).format(c1=c1_wfr_p95, c2=c2_wfr_p95), st["body"]))

    section(story, "6.4 T1/T2：选举过渡窗口" if z else "6.4 T1/T2: Election Transition Windows", st, 2)
    t1_totals, t2_totals = data["t1_totals"], data["t2_totals"]
    t1_election_mean = mean(data["t1_elections"])
    t2_election_mean = mean(data["t2_elections"])
    t1_strong = sum(
        row["violation_count"] for run in data["t1_runs"] for row in run["aggregates"] if row["config_id"] in ("C1", "C2", "C4")
    )
    t2_strong = sum(
        row["violation_count"] for run in data["t2_runs"] for row in run["aggregates"] if row["config_id"] in ("C1", "C2", "C4")
    )
    transition_data = [
        ["场景" if z else "Scenario", "检查" if z else "Checks", "违例" if z else "Violations", "操作错误" if z else "Op. errors", "平均选举时间" if z else "Mean election", "强配置成功操作" if z else "Strong successful ops"],
        ["T1", fmt_int(t1_totals["checks"]), f"{fmt_int(t1_totals['violations'])} (all C3)", f"{t1_totals['errors']} (all election)", f"{t1_election_mean:,.0f} ms", f"{t1_strong} violations"],
        ["T2", fmt_int(t2_totals["checks"]), f"{fmt_int(t2_totals['violations'])} (all C3)", f"{t2_totals['errors']} (all election)", f"{t2_election_mean:,.0f} ms", f"{t2_strong} violations"],
    ]
    story.append(make_table(transition_data, [17*mm, 25*mm, 38*mm, 38*mm, 27*mm, 30*mm], st))
    story.append(Spacer(1, 4*mm))
    story.append(figure(FIG / "02_transition_window_outcomes.png", "图 4. T1/T2 中各配置的成功检查、违例和操作错误。" if z else "Figure 4. Successful checks, violations, and operation errors by configuration in T1/T2.", st))
    story.append(figure(FIG / "03_fault_timing.png", "图 5. S2、S3、T1 与 T2 的选举时间。T1/T2 显示三个随机种子。" if z else "Figure 5. Election timing for S2, S3, T1, and T2. T1/T2 show all three seeds.", st))

    def phase_cell(totals: dict[str, dict[str, int]], phase: str) -> str:
        v, c = totals[phase]["violations"], totals[phase]["checks"]
        return f"{fmt_int(v)}/{fmt_int(c)} = {fmt_rate(v, c)}"

    phase_data = [
        ["场景" if z else "Scenario", "pre", "election", "post"],
        ["T1 C3", phase_cell(data["t1_phase"], "pre-fault"), phase_cell(data["t1_phase"], "election"), phase_cell(data["t1_phase"], "post-election")],
        ["T2 C3", phase_cell(data["t2_phase"], "pre-fault"), phase_cell(data["t2_phase"], "election"), phase_cell(data["t2_phase"], "post-election")],
    ]
    story.append(make_table(phase_data, [28*mm, 46*mm, 46*mm, 47*mm], st))
    t1_err_range = f"{min(data['t1_errors_per_seed'])}-{max(data['t1_errors_per_seed'])}"
    t2_err_range = f"{min(data['t2_errors_per_seed'])}-{max(data['t2_errors_per_seed'])}"
    story.append(p(
        (
            "过渡实验给出两个互补结论。第一，C1、C2、C4 的成功 RYW 对仍然共 {strong} 次违例；第二，选举阶段出现 {t1_err} 与 {t2_err} 次操作错误，说明强一致设置在无法立即找到可写 Primary 时牺牲了短暂可用性。C3 在故障前已经很弱，其 pre 与 election 违例率接近，因此选举没有创造一种新的 C3 一致性缺陷，主要新增的是暂时失败。三个种子之间的选举期错误数并不稳定（T1：{t1_range} 次；T2：{t2_range} 次），这在单 VM 部署下更可能反映资源调度噪声而非协议行为的差异，报告没有把它当作可复现的定量结果。"
            if z else
            "The transition tests give two complementary conclusions. First, successful RYW pairs under C1, C2, and C4 recorded {strong} violations combined. Second, {t1_err} and {t2_err} operation errors occurred during elections, showing a temporary availability cost when no writable Primary could be selected immediately. C3 was already weak before each fault, with similar pre and election violation rates; the election did not create a new C3 consistency defect, but mainly added transient failures. The per-seed election-window error count varied noticeably (T1: {t1_range}; T2: {t2_range}), which on a single shared VM more likely reflects scheduling noise than a real difference in protocol behaviour, so it is reported here rather than treated as a stable quantitative result."
        ).format(strong=t1_strong + t2_strong, t1_err=t1_totals["errors"], t2_err=t2_totals["errors"], t1_range=t1_err_range, t2_range=t2_err_range), st["body"]))

    matrix_transition_parts = []
    for config_id in ("C5", "C6", "C8"):
        t1_row = data["t1_matrix_totals"][config_id]
        t2_row = data["t2_matrix_totals"][config_id]
        matrix_transition_parts.append(
            f"{config_id}: T1 {fmt_int(t1_row['violations'])}/{fmt_int(t1_row['checks'])}, "
            f"T2 {fmt_int(t2_row['violations'])}/{fmt_int(t2_row['checks'])}"
        )
    story.append(p(
        (
            "受控矩阵新增三角在相同远程环境中的过渡窗口 RYW 违例/成功检查为：{parts}。C3 的原过渡数据已经在上表和图中呈现，因此没有重复运行。该结果用于观察选举期间 concern 组合是否改变成功历史中的旧读；操作错误仍与一致性违例分开解释。" if z else
            "For the three new matrix corners in the same remote environment, transition-window RYW violations/successful checks were: {parts}. C3's original transition data is already included above and was not rerun. These results test whether concern combinations change stale successful histories during elections; operation errors remain separate from consistency violations."
        ).format(parts="; ".join(matrix_transition_parts)), st["body"]))

    section(story, "6.5 S4：受控复制延迟" if z else "6.5 S4: Controlled Replication Lag", st, 2)
    s4_ryw, s4_mr, s4_mw, s4_wfr = (agg_row(s4, "C3", m) for m in (ryw, mr, mw, wfr))
    s4_data = [
        ["模型" if z else "Model", "违例 / 检查" if z else "Violations / checks", "违例率" if z else "Rate", "解释" if z else "Interpretation"],
        ["RYW", f"{fmt_int(s4_ryw['violation_count'])} / {fmt_int(s4_ryw['check_count'])}", fmt_rate(s4_ryw["violation_count"], s4_ryw["check_count"]), "写后命中被冻结 Secondary，读到旧版本。" if z else "Post-write read hits the frozen Secondary."],
        ["MR", f"{fmt_int(s4_mr['violation_count'])} / {fmt_int(s4_mr['check_count'])}", fmt_rate(s4_mr["violation_count"], s4_mr["check_count"]), "交替访问当前与冻结 Secondary，后读倒退。" if z else "Alternation between current and frozen secondaries."],
        ["MW", f"{fmt_int(s4_mw['violation_count'])} / {s4_mw['check_count']} validations", fmt_rate(s4_mw["violation_count"], s4_mw["check_count"]), "Primary 接收顺序写；最终版本有序。" if z else "Primary accepts ordered writes; final state remains ordered."],
        ["WFR*", f"{fmt_int(s4_wfr['violation_count'])} / {fmt_int(s4_wfr['check_count'])}", fmt_rate(s4_wfr["violation_count"], s4_wfr["check_count"]), "空读取记为 -1；原始标记，非有效违例。" if z else "Null read encoded as -1; raw flags, not valid violations."],
    ]
    story.append(make_table(s4_data, [23*mm, 39*mm, 25*mm, 80*mm], st))
    story.append(Spacer(1, 4*mm))
    story.append(figure(FIG / "04_s4_model_violation_rates.png", "图 6. C3 的 S4 原始判定率；WFR 50% 是无效代理标记，不能用作违例率。" if z else "Figure 6. C3 raw S4 checker rates; WFR 50% is an invalid proxy flag, not a violation rate.", st))
    s4_totals = s4["totals"]
    story.append(p(
        (
            "S4 原始汇总共 {checks} 次检查、{err} 次数据库操作错误、{viol} 个程序标记（{rate}）；其中 750 个 C3 WFR 标记不能计为有效一致性违例，因此总数与总率也不能视为正式违例统计。冻结节点在测试结束时落后 {lag:.0f} 秒；恢复复制后连续三次状态检查均在 1 秒内追平，完整恢复过程耗时 {catchup:,.0f} ms。MR 接近 50% 与两个 Secondary 交替读取相吻合；WFR 接近 50% 则主要反映空读取被赋值 -1 的判定规则。"
            if z else
            "The S4 raw summary contains {checks} checks, {err} database-operation errors, and {viol} checker flags ({rate}). Of these, 750 C3 WFR flags are not valid consistency violations, so the combined count and rate are not formal violation statistics. The frozen member was {lag:.0f} seconds behind at test end; after apply resumed, three consecutive checks found lag within one second and full recovery took {catchup:,.0f} ms. MR near 50% fits alternating Secondary reads; WFR near 50% mainly reflects the checker assigning -1 to a null read."
        ).format(
            checks=fmt_int(s4_totals["check_count"]), err=s4_totals["error_count"], viol=fmt_int(s4_totals["violation_count"]),
            rate=fmt_rate(s4_totals["violation_count"], s4_totals["check_count"]),
            lag=(data["s4_lag_end_ms"] or 0) / 1000, catchup=data["s4_catchup_ms"] or 0,
        ), st["body"]))

    section(story, "7. 预测与观察对照" if z else "7. Predictions Versus Observations", st)
    section(story, "7.1 代表性配置" if z else "7.1 Representative Configurations", st, 2)
    pred_data = [["配置" if z else "Config", "预测" if z else "Prediction", "观察" if z else "Observation", "结论" if z else "Assessment"],
        ["C1", "四项成立" if z else "All four hold", "所有 S0-S3 检查与 T1/T2 成功 RYW 均零违例" if z else "Zero violations in S0-S3 and successful T1/T2 RYW", "一致" if z else "Agrees"],
        ["C2", "跨副本因果会话仍成立" if z else "Cross-member causal session holds", "读取 Secondary 时仍零违例；部分尾延迟较高" if z else "Zero violations on Secondary reads; some higher tail latency", "一致" if z else "Agrees"],
        ["C3", "RYW/MR/WFR 可能违例，MW 通常成立" if z else "RYW/MR/WFR may fail; MW usually holds", "S0 观察 RYW/MR；S4 观察 RYW/MR；WFR 标记无效" if z else "S0 exposed RYW/MR; S4 exposed RYW/MR; WFR flags invalid", "RYW/MR 一致；WFR 未判定" if z else "RYW/MR agree; WFR inconclusive"],
        ["C4", "本负载中成立，但不是通用因果保证" if z else "Holds here, not a general causal guarantee", "本实验零违例" if z else "Zero violations in this workload", "有限支持" if z else "Supported within scope"],
    ]
    story.append(make_table(pred_data, [18*mm, 48*mm, 72*mm, 29*mm], st))
    append_callout(story,
        "最重要的区分是安全性与可用性。强配置没有把选举期间的失败请求伪装成一致性违例：它们拒绝或重试无法安全完成的操作，而成功完成的历史继续满足 RYW。相反，C3 提供低延迟和较高可用读取，但允许成功返回旧版本。" if z else
        "The key distinction is safety versus availability. The strong configurations did not convert election-time failures into consistency anomalies: unsafe operations failed or retried, while successful histories continued to satisfy RYW. C3 instead offered low-latency, highly available reads that could successfully return stale versions.", st)

    section(story, "7.2 受控关注矩阵" if z else "7.2 Controlled Concern Matrix", st, 2)
    matrix_prediction_data = [[
        "配置" if z else "Config", "隔离比较" if z else "Isolated comparison",
        "理论边界" if z else "Theoretical boundary", "观察（S0 / S4）" if z else "Observation (S0 / S4)",
    ],
    ["C3", "矩阵基准：local + w:1" if z else "Matrix baseline: local + w:1",
     "无因果会话，四项均无通用保证；本负载 MW 预期有序" if z else "No general session guarantees; workload likely preserves MW",
     f"{matrix_model_cell(s0, s0_matrix, 'C3')} / {matrix_model_cell(s4, s4_matrix, 'C3', s4=True)}"],
    ["C5", "对 C3 仅提升 read concern" if z else "Only read concern raised from C3",
     "majority 读不等于读到客户端最新写" if z else "Majority read does not mean the client's latest write",
     f"{matrix_model_cell(s0, s0_matrix, 'C5')} / {matrix_model_cell(s4, s4_matrix, 'C5', s4=True)}"],
    ["C6", "对 C3 仅提升 write concern" if z else "Only write concern raised from C3",
     "majority 写保证确认耐久性，不保证目标 Secondary 已应用" if z else "Majority write protects durability, not Secondary apply recency",
     f"{matrix_model_cell(s0, s0_matrix, 'C6')} / {matrix_model_cell(s4, s4_matrix, 'C6', s4=True)}"],
    ["C8", "C5/C6 的 majority/majority 交点" if z else "Majority/majority intersection of C5/C6",
     "关注组合仍不能替代因果会话" if z else "Concern combination still does not replace a causal session",
     f"{matrix_model_cell(s0, s0_matrix, 'C8')} / {matrix_model_cell(s4, s4_matrix, 'C8', s4=True)}"],
    ]
    story.append(make_table(matrix_prediction_data, [14*mm, 42*mm, 58*mm, 53*mm], st))
    story.append(p("* S4 WFR 数字是原始程序标记，并非有效违例率；预测与观察对照仅依据 RYW、MR 和 MW。" if z else "* S4 WFR values are raw checker flags, not valid violation rates; the prediction-observation comparison relies on RYW, MR, and MW.", st["small"]))
    story.append(p(
        "矩阵的价值不在于期待四行一定呈现四种完全不同结果，而在于排除会话和路由变化后判断 concern 是否足以改变客户端看到的历史。若 majority/majority 仍出现成功旧读，这正是结论：耐久性与提交可见性参数不能自动提供跨副本会话顺序。" if z else
        "The matrix is valuable even if its four rows do not produce four radically different outcomes. By holding session and routing constant, it tests whether concern alone changes the histories visible to the client. If majority/majority still returns a successful stale read, that is the result: durability and committed visibility do not automatically provide cross-replica session ordering.", st["body"]))

    section(story, "8. 局限性与有效性威胁" if z else "8. Limitations and Threats to Validity", st)
    limits = [
        "三个节点位于同一 VM，共享硬件、磁盘与底层网络；容器隔离不能替代三台物理或虚拟主机。",
        "S1-S3 在选举完成后运行完整矩阵；T1/T2 只在过渡窗口测试 RYW，其他三项模型尚未持续压测。",
        "S3 将旧 Primary 同时与副本和客户端隔离，并未模拟分区两侧各有客户端的 split-client 历史。",
        "S4 使用 enableTestCommands 和 rsSyncApplyStop，是为了因果诊断而设计的极端失效点，不代表真实网络延迟分布。",
        "每项仅使用三个种子；工作负载、驱动服务器选择与本机调度会改变经验违例率。零违例不是数学证明。",
        "阶段以操作开始时间分类；跨越选举边界的单次操作仍只属于一个阶段。",
        "MW 运行了每个配置每种子 500 次顺序写，但汇总中的主要判定分母是每种子的最终历史验证，因此表中显示 3 次验证。",
        "C3 来自主实验的较早远程运行，C5/C6/C8 来自同一 GCP 虚拟机上的后续运行。软件与部署配置一致，但采集时间不同，缓存和宿主机调度仍可能影响绝对延迟；因此矩阵对违例模式的比较比微小延迟差更可靠。",
        "S4 暂停一个 Secondary，但矩阵配置按固定次序交替读取两个 Secondary；各配置接受相同路由调度，然而这不是每个操作都读取同一冻结节点的严格配对试验。",
        "S4 的 WFR 判定存在测量有效性缺陷：冻结 Secondary 在测试文档创建前已停止复制，命中它时可能返回空结果；代码将空读取写为 parent_version = -1，并仅凭这个负值判为违例。空读取并未给出可比较的已读版本，也不能证明后续写在更旧状态上执行。因此图表中约 50% 的 WFR 是无效代理统计，不能用于正式结论；单 Primary 下的后续写通常发往不比已读 Secondary 更旧的 Primary，预期不会观察到真实 WFR 违例，但本实验没有有效验证这一预期。",
    ] if z else [
        "All members share one VM, hardware, disk, and underlying network; container isolation is not equivalent to three physical or virtual hosts.",
        "S1-S3 run the full matrix after election completion. T1/T2 cover only RYW continuously during the transition; the other three models were not stressed through elections.",
        "S3 isolates the old Primary from both peers and the client. It does not create split-client histories with clients on both partition sides.",
        "S4 uses enableTestCommands and rsSyncApplyStop as an extreme diagnostic failpoint, not as a realistic latency distribution.",
        "Only three seeds are used. Workload shape, driver selection, and local scheduling influence empirical rates. Zero observed violations is not a mathematical proof.",
        "Phases are assigned by operation start time; an operation crossing an election boundary still belongs to one phase.",
        "MW performs 500 sequential writes per configuration and seed, but the summary denominator counts one final history validation per seed; therefore the table reports three validations.",
        "C3 comes from the earlier main-suite remote run, while C5/C6/C8 come from a later run on the same GCP VM. Software and deployment settings match, but cache and host scheduling can still affect absolute latency across collection times; violation patterns are therefore more reliable than small latency differences.",
        "S4 pauses one Secondary while matrix configurations alternate reads across two Secondaries in a fixed order. Every configuration receives the same routing schedule, but this is not a strict operation-by-operation pairing in which every read targets the paused member.",
        "The S4 WFR checker has a measurement-validity defect. The paused Secondary stopped applying oplog entries before the test document was created, so a read there can return no document. The code maps that null read to parent_version = -1 and flags a violation solely because the value is negative. A null read provides no observed version to order a later write against and does not show that the write executed on an older state. Thus the approximately 50% WFR figure is an invalid proxy, not a formal violation rate. With writes routed to a single Primary that is normally no older than a version read from a Secondary, true WFR violations are not expected in this workload, but this experiment did not validly test that expectation.",
    ]
    for item in limits:
        story.append(bullet(item, st["bullet"]))

    section(story, "9. 可复现性" if z else "9. Reproducibility", st)
    section(story, "9.1 主要命令" if z else "9.1 Main Commands", st, 2)
    commands = """# Baseline S0
docker compose run --rm --no-deps runner python -m experiments.run_baseline \
  --iterations 500 --seeds 20260830,20260831,20260832 --label formal

# Stable fault scenarios (replace the scenario name for S2/S3)
./scripts/run_fault_scenario.sh S1-secondary-failure 500 \
  20260830,20260831,20260832 formal

# Transition windows; repeat for seeds 20260830-20260832
./scripts/run_transition_scenario.sh T1-primary-stop-transition 20260830 formal 35 3
./scripts/run_transition_scenario.sh T2-primary-partition-transition 20260830 formal 35 3

# Controlled replication lag for the original representative suite
./scripts/run_replication_lag_scenario.sh 500 \
  20260830,20260831,20260832 formal

# Complete the non-causal concern matrix on the same remote VM.
# This resumable suite runs only C5/C6/C8 and reuses the existing C3 data.
./scripts/run_noncausal_concern_matrix.sh noncausal-remote-v2 500 \
  20260830,20260831,20260832

# Recovery and report figures
./scripts/restore_cluster.sh
./scripts/cluster_status.sh
python3 -m analysis.generate_report_figures"""
    append_code_block(story, commands.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br/>"), st)
    story.append(p(
        "仓库保存 compose 配置、初始化脚本、故障注入脚本、Python 工作负载、正式 summary JSON、汇总说明和生成图表的代码。原始 JSONL 可由上述命令重新生成。为避免意外计费，实验结束后应在 Google Cloud 控制台停止 VM，并确认实例状态为 TERMINATED；持久磁盘仍可能持续计费。" if z else
        "The repository contains Compose configuration, initialization and fault scripts, Python workloads, formal summary JSON, result narratives, and chart-generation code. Raw JSONL can be regenerated with the commands above. To avoid unintended compute charges, stop the VM in Google Cloud after experiments and verify TERMINATED status; persistent disk may continue to incur storage charges.", st["body"]))

    section(story, "9.2 正式运行标识" if z else "9.2 Formal Run Identifiers", st, 2)

    def run_suffix(run_id: str) -> str:
        return run_id.rsplit("-", 1)[-1]

    run_ids = [
        ["S0", s0["run_id"]],
        ["S1", s1["run_id"]],
        ["S2", s2["run_id"]],
        ["S3", s3["run_id"]],
        ["S4", s4["run_id"]],
        ["T1", "; ".join(run_suffix(r["run_id"]) for r in data["t1_runs"])],
        ["T2", "; ".join(run_suffix(r["run_id"]) for r in data["t2_runs"])],
        ["S0 (C5/C6/C8)", s0_matrix["run_id"]],
        ["S1 (C5/C6/C8)", s1_matrix["run_id"]],
        ["S2 (C5/C6/C8)", s2_matrix["run_id"]],
        ["S3 (C5/C6/C8)", s3_matrix["run_id"]],
        ["S4 (C5/C6/C8)", s4_matrix["run_id"]],
        ["T1 (C5/C6/C8)", "; ".join(run_suffix(r["run_id"]) for r in data["t1_matrix_runs"])],
        ["T2 (C5/C6/C8)", "; ".join(run_suffix(r["run_id"]) for r in data["t2_matrix_runs"])],
    ]
    story.append(make_table([["场景" if z else "Scenario", "Selected formal run ID / suffix"]] + run_ids, [26*mm, 141*mm], st, padding=2))

    section(story, "10. 结论" if z else "10. Conclusion", st)
    story.append(p(
        "实验完成了从理论预测、复制集部署、可调配置、四模型工作负载到故障注入和机制验证的闭环。代表性配置展示了因果会话、路由和关注设置共同作用下的端到端行为；C3/C5/C6/C8 非因果矩阵进一步固定会话与 Secondary 访问顺序，使 read concern 与 write concern 的影响能够被单独比较而不重复 C3。结果区分了耐久性、提交可见性、会话顺序和可用性：majority 参数并不自动等价于跨副本客户端中心保证，选举最直接的影响是短暂不可用，而 S4 则把成功旧读放大为可解释的机制证据。" if z else
        "The project completes a full cycle from theoretical prediction through replica-set deployment, tunable configurations, four executable model workloads, fault injection, and mechanistic validation. The representative configurations show the end-to-end interaction of causal sessions, routing, and concern settings. The non-causal C3/C5/C6/C8 matrix then holds session and Secondary order fixed, allowing read and write concern to be compared without rerunning C3. The results separate durability, committed visibility, session ordering, and availability: majority settings do not automatically equal cross-replica client-centric guarantees, elections primarily caused temporary unavailability, and S4 amplified successful stale reads into mechanistic evidence.", st["body"]))

    section(story, "参考文献" if z else "References", st)
    refs = [
        ("[1]", "MongoDB Manual, Read Isolation, Consistency, and Recency.", "https://www.mongodb.com/docs/manual/core/read-isolation-consistency-recency/"),
        ("[2]", "MongoDB Manual, Read Concern.", "https://www.mongodb.com/docs/manual/reference/read-concern/"),
        ("[3]", "MongoDB Manual, Write Concern.", "https://www.mongodb.com/docs/manual/reference/write-concern/"),
        ("[4]", "MongoDB Manual, Read Preference.", "https://www.mongodb.com/docs/manual/core/read-preference/"),
        ("[5]", "MongoDB Manual, Self-Managed Replica Set Configuration.", "https://www.mongodb.com/docs/manual/reference/replica-configuration/"),
        ("[6]", "MongoDB PyMongo Driver Documentation, Transactions and Causal Consistency.", "https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/transactions/#causal-consistency"),
        ("[7]", "Docker Documentation, Docker Compose.", "https://docs.docker.com/compose/"),
        ("[8]", "Docker CLI Documentation, docker network disconnect.", "https://docs.docker.com/reference/cli/docker/network/disconnect/"),
        ("[9]", "Google Cloud Documentation, Compute Engine Instances.", "https://cloud.google.com/compute/docs/instances"),
        ("[10]", "DSA5208 Lecture 3: Replication and Consistency (course material supplied by the instructor).", ""),
    ]
    for num, title, url in refs:
        suffix = (f' <link href="{url}" color="#1F6F8B">{url}</link>' if url else "")
        story.append(p(f"{num} {title}{suffix}", st["ref"]))
    story.append(p("以上在线文档最后访问日期：2026-08-31。" if z else "All online documentation was last accessed on 31 August 2026.", st["small"]))

    section(story, "AI 使用声明" if z else "AI Usage Statement", st)
    story.append(p(
        "本项目使用 OpenAI ChatGPT/Codex 协助解释课程概念、规划与审阅实验、修改脚本、组织结果、生成图表和润色中英文报告。Anthropic Claude（Claude Code）曾用于审查可复现性、修复跨平台字体与数据驱动报告代码，并实现和运行较早的 C5-C8 因果会话扩展；该扩展经复核后因变量控制与运行环境不符合最终研究设计而被保留为历史记录、不用于本文结论。最终的 C3/C5/C6/C8 非因果关注矩阵由 Codex 协助重构，并在与主实验相同的 GCP 虚拟机上重新运行缺失的 C5/C6/C8 组合。所有云资源操作、故障注入、输出检查与结论均由项目成员监督；报告数据来自仓库中的真实运行输出，并非由 AI 生成。" if z else
        "OpenAI ChatGPT/Codex supported concept explanation, experiment planning, script and report editing, result checks, and figure generation. Anthropic Claude (Claude Code) earlier reviewed reproducibility and helped implement a causal-session C5-C8 extension; this historical output was excluded because its controls and environment differed from the final design. Codex then helped build the non-causal C3/C5/C6/C8 matrix and run the missing C5/C6/C8 combinations on the main GCP VM. Project members supervised cloud operations, fault injection, validation, and interpretation. All reported measurements are stored experimental outputs, not AI-generated.", st["small"]))

    return story


def build(lang: str, filename: str, data: dict[str, Any]):
    st = styles(lang)
    title = (
        "MongoDB 可调一致性与客户端中心一致性实验"
        if lang == "zh"
        else "Tunable Consistency and Client-Centric Guarantees in MongoDB"
    )
    path = OUT / filename
    doc = ReportDocTemplate(
        str(path),
        lang=lang,
        report_title=title,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="Pan Yuxiang; Hou Jiacheng; Wu Jiarui",
        subject="DSA5208 Project 1 experimental report",
    )
    doc.multiBuild(report_content(lang, st, data))
    return path


def main() -> None:
    register_fonts()
    OUT.mkdir(parents=True, exist_ok=True)
    data = load_report_data()
    outputs = [
        build("zh", "DSA5208_Project1_Report_ZH.pdf", data),
        build("en", "DSA5208_Project1_Report_EN.pdf", data),
    ]
    for src in outputs:
        print(src)
    if USER_OUT is not None:
        USER_OUT.mkdir(parents=True, exist_ok=True)
        for src in outputs:
            shutil.copy2(src, USER_OUT / src.name)
            print(USER_OUT / src.name)


if __name__ == "__main__":
    main()
