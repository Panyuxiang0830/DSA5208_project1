#!/usr/bin/env python3
"""Generate the Chinese and English final project reports as polished PDFs."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

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
USER_OUT = Path(
    "/Users/panyuxiang/Documents/Codex/2026-08-30/"
    "1-project-description-in-this-project/outputs"
)
FIG = ROOT / "results" / "figures"
FONT = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")

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
    if not FONT.exists():
        raise FileNotFoundError(f"Required Unicode font not found: {FONT}")
    pdfmetrics.registerFont(TTFont("ArialUnicode", str(FONT)))


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
        "callout": ParagraphStyle("Callout" + lang, parent=body, fontName=bold, fontSize=10.2, leading=15.2, textColor=NAVY, leftIndent=7 * mm, rightIndent=7 * mm, borderColor=TEAL, borderWidth=0.8, borderPadding=8, backColor=PALE, spaceBefore=7, spaceAfter=9),
        "bullet": ParagraphStyle("Bullet" + lang, parent=body, leftIndent=5.5 * mm, firstLineIndent=-3.5 * mm, bulletIndent=0, spaceAfter=3),
        "code": ParagraphStyle("Code" + lang, parent=body, fontName=mono, fontSize=7.1, leading=10.2, leftIndent=4 * mm, rightIndent=4 * mm, borderColor=GRID, borderWidth=0.5, borderPadding=6, backColor=PALE2, spaceBefore=4, spaceAfter=6),
        "table": ParagraphStyle("Table" + lang, parent=body, fontSize=7.1, leading=9.5, alignment=TA_LEFT, spaceAfter=0),
        "table_head": ParagraphStyle("TableHead" + lang, parent=body, fontName=bold, fontSize=7.2, leading=9.4, textColor=colors.white, alignment=TA_CENTER, spaceAfter=0),
        "ref": ParagraphStyle("Ref" + lang, parent=body, fontSize=7.5, leading=10.5, alignment=TA_LEFT, leftIndent=4 * mm, firstLineIndent=-4 * mm, spaceAfter=4),
    }


def p(text: str, st, **kwargs) -> Paragraph:
    return Paragraph(text, st, **kwargs)


def bullet(text: str, st) -> Paragraph:
    return Paragraph("• " + text, st)


def make_table(data, widths, st, header=True, aligns=None, font_size=7.0):
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
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
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
        meta = "作者：Panyuxiang、Hou Jiacheng、Wu Jiarui<br/>提交日期：2026 年 9 月 27 日<br/>实验平台：Google Cloud Compute Engine（新加坡）"
    else:
        story.append(p("DSA5208 Scalable Distributed Computing for Data Science", st["subtitle"]))
        story.append(Spacer(1, 5 * mm))
        story.append(p("Tunable Consistency and<br/>Client-Centric Guarantees in MongoDB", st["title"]))
        story.append(Spacer(1, 4 * mm))
        story.append(p("Project 1 · Complete Experimental Report (English Edition)", st["subtitle"]))
        meta = "Prepared by: Panyuxiang, Hou Jiacheng, and Wu Jiarui<br/>Submission date: 27 September 2026<br/>Experimental platform: Google Cloud Compute Engine (Singapore)"
    story.append(Spacer(1, 23 * mm))
    story.append(p(meta, st["meta"]))
    story.append(Spacer(1, 20 * mm))
    claim = (
        "核心结论：因果会话配合 majority 读写在成功操作中保持了四项保证；<br/>无因果会话的 w:1 + local + Secondary 读取在受控复制延迟下暴露了全部三类读因果异常。"
        if lang == "zh"
        else "Main finding: causal sessions with majority reads and writes preserved all four guarantees for successful operations; weak reads exposed all three read-related anomalies under controlled replication lag."
    )
    story.append(p(claim, st["callout"]))
    story.append(Spacer(1, 6 * mm))
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


def report_content(lang: str, st):
    z = lang == "zh"
    story = []
    cover(story, lang, st)
    toc(story, lang, st)

    section(story, "摘要" if z else "Abstract", st)
    abstract = (
        "本项目在单台 Google Cloud 虚拟机中使用 Docker Compose 部署三节点 MongoDB 8.0.29 副本集，并系统研究读关注级别、写关注级别、读偏好与因果一致会话如何影响应用观察到的四项客户端中心一致性保证：读己之写、单调读、单调写和写跟随读。实验由正常运行、Secondary 停机、Primary 停机、Primary 网络分区、选举过渡窗口以及受控复制延迟六类场景组成。正式基线与稳态故障矩阵对每个配置和模型运行 500 个序列及 3 个随机种子；过渡窗口持续 35 秒；复制延迟实验冻结一个可读 Secondary 的应用线程。结果显示，C1、C2 与 C4 在所有成功检查中均未出现一致性违例；弱配置 C3 在正常状态的读己之写违例率为 76.07%，在 S1-S3 为 64.60%-69.93%。选举窗口产生短暂操作错误，但没有在强配置中引入新的成功读异常。S4 将弱配置的读己之写、单调读和写跟随读违例率分别放大到 83.33%、49.80% 和 50.00%，而单调写仍未违例。结果支持 MongoDB 文档对因果一致会话与 majority 读写关注级别的描述，同时说明“未观察到违例”是特定实验负载下的证据，而非对所有执行历史的形式证明。"
        if z else
        "This project deploys a three-member MongoDB 8.0.29 replica set with Docker Compose on one Google Cloud virtual machine and studies how read concern, write concern, read preference, and causally consistent sessions affect four client-centric guarantees: read-your-writes, monotonic reads, monotonic writes, and writes-follow-reads. The experiment suite covers normal operation, a stopped secondary, a stopped primary, a primary-side network partition, continuous requests during elections, and controlled replication lag. Each formal baseline and stable-fault matrix uses 500 sequences and three random seeds for every configuration-model pair; transition tests run for 35 seconds; the lag test freezes apply processing on one readable secondary. C1, C2, and C4 showed no consistency violations in successful checks. Weak configuration C3 produced a 76.07% read-your-writes violation rate in normal operation and 64.60%-69.93% under stable faults. Election windows caused transient operation errors but no new successful-read anomaly in the strong configurations. Under S4, C3 violation rates rose to 83.33% for read-your-writes, 49.80% for monotonic reads, and 50.00% for writes-follow-reads, while monotonic writes remained intact. These observations support MongoDB's documented causal-consistency behavior, while the absence of observed violations remains experimental evidence rather than a proof over all histories."
    )
    story.append(p(abstract, st["body"]))
    story.append(p(("关键词：MongoDB；副本集；可调一致性；因果一致性；故障注入；复制延迟" if z else "Keywords: MongoDB; replica sets; tunable consistency; causal consistency; fault injection; replication lag"), st["small"]))

    section(story, "1. 项目目标与研究问题" if z else "1. Objectives and Research Questions", st)
    story.append(p(
        "课程任务要求搭建一个支持可调一致性的复制型分布式数据库，在正常运行、节点故障和网络分区下预测并检验应用观察到的客户端中心一致性。本项目选择 MongoDB，因为其驱动层同时暴露会话、读关注、写关注和读偏好，能够把抽象一致性模型映射为可复现的客户端配置。" if z else
        "The assignment requires a replicated database with tunable consistency, predictions about client-observed guarantees, and experiments under normal operation, node failures, and a network partition. MongoDB was selected because its driver exposes sessions, read concern, write concern, and read preference, allowing abstract consistency models to be mapped to reproducible client configurations.", st["body"]))
    questions = [
        "不同配置是否保持读己之写（RYW）、单调读（MR）、单调写（MW）与写跟随读（WFR）？",
        "稳定故障状态与选举过渡窗口分别如何影响一致性和可用性？",
        "受控复制延迟能否把偶发的旧读放大为稳定、可解释的异常？",
    ] if z else [
        "Which configurations preserve read-your-writes (RYW), monotonic reads (MR), monotonic writes (MW), and writes-follow-reads (WFR)?",
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
    story.append(p(install.replace("\n", "<br/>"), st["code"]))
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
    ]
    story.append(make_table(config_data, [13*mm, 22*mm, 24*mm, 24*mm, 38*mm, 46*mm], st))
    story.append(p(
        "C3 是主动选择的弱配置：w:1 只要求单个 mongod 确认，local 读取不保证数据已被多数节点提交，而 Secondary 读取可能落后于 Primary。C4 用于分离“majority + Primary”与“因果会话”各自的作用；它在本实验的单客户端、Primary 定向负载中很强，但不应外推为所有跨客户端因果历史的保证。" if z else
        "C3 is intentionally weak: w:1 requires acknowledgment from one mongod, local reads need not be majority committed, and a secondary may lag the primary. C4 separates the effect of majority/primary access from causal sessions. It is strong for this single-client, primary-directed workload but should not be generalized to every cross-client causal history.", st["body"]))

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

    section(story, "5.2 故障注入与恢复" if z else "5.2 Fault Injection and Recovery", st, 2)
    story.append(p(
        "S1 与 S2 使用 Docker 停止指定角色的容器。S3 使用 docker network disconnect 将故障前 Primary 从副本集网络断开，使剩余两节点形成多数派并选出新 Primary。T1/T2 在故障前启动四种配置的并发循环，把请求按开始时间标注为 pre、election 或 post。S4 仅在测试专用 compose 覆盖中启用 enableTestCommands=1，并对一个 Secondary 执行 rsSyncApplyStop；完成后执行 rsSyncApplyStop 的逆操作、等待追平，并重新创建普通容器。每个故障场景结束后均运行 restore_cluster.sh 和 cluster_status.sh 验证三节点健康。" if z else
        "S1 and S2 stop the container holding the selected role. S3 uses docker network disconnect to isolate the pre-fault Primary from the replica-set network; the remaining two members retain a majority and elect a new Primary. T1/T2 start concurrent loops for all four configurations before fault injection and label requests by operation start time as pre, election, or post. S4 enables enableTestCommands=1 only in a test-specific Compose override and runs rsSyncApplyStop on one Secondary; afterward, apply processing is resumed, catch-up is verified, and normal containers are recreated. Every scenario ends with restore_cluster.sh and cluster_status.sh to confirm a healthy three-member set.", st["body"]))
    story.append(p(
        "设计理由：S0-S3 区分稳态一致性，T1/T2 捕获常被“等待选举完成”掩盖的短暂不可用窗口，S4 则提供可控因果机制，以验证 C3 的异常确实来自副本落后而非测试噪声。" if z else
        "Rationale: S0-S3 isolate stable-state consistency, T1/T2 expose the transient unavailability hidden by waiting for election completion, and S4 provides a controlled causal mechanism showing that C3 anomalies arise from replica lag rather than test noise.", st["callout"]))

    # Start the results on a clean page so the rationale callout and next
    # chapter heading do not compete for the final lines of the design page.
    story.append(PageBreak())

    section(story, "6. 结果" if z else "6. Results", st)
    section(story, "6.1 S0-S3：稳态矩阵" if z else "6.1 S0-S3: Stable-State Matrix", st, 2)
    story.append(p(
        "S0 共完成 60,012 次数据库操作、18,012 次一致性检查，错误为 0。S1、S2、S3 各完成 18,012 次检查且数据库操作错误均为 0。C1、C2、C4 在全部场景和四个模型中均为零违例；C3 的稳定异常只出现在 RYW。" if z else
        "S0 completed 60,012 database operations and 18,012 consistency checks with zero errors. S1, S2, and S3 each completed 18,012 checks with zero database-operation errors. C1, C2, and C4 had zero violations for every model and scenario; the only stable C3 anomaly was RYW.", st["body"]))
    stable_data = [["场景" if z else "Scenario", "C3 RYW" , "违例率" if z else "Rate", "其他 C3 模型" if z else "Other C3 models", "C1/C2/C4"],
        ["S0", "1,141 / 1,500", "76.07%", "MR 109/1,500 (7.27%); MW 0; WFR 0", "0"],
        ["S1", "1,035 / 1,500", "69.00%", "MR 0; MW 0; WFR 0", "0"],
        ["S2", "969 / 1,500", "64.60%", "MR 0; MW 0; WFR 0", "0"],
        ["S3", "1,049 / 1,500", "69.93%", "MR 0; MW 0; WFR 0", "0"],
    ]
    story.append(make_table(stable_data, [18*mm, 34*mm, 25*mm, 62*mm, 28*mm], st))
    story.append(Spacer(1, 4*mm))
    story.append(figure(FIG / "01_consistency_violation_matrix.png", "图 2. S0-S4 的一致性违例矩阵。颜色表示每 1,500 次主要检查的违例率。" if z else "Figure 2. Consistency-violation matrix for S0-S4. Color encodes the violation rate among 1,500 principal checks.", st))
    story.append(p(
        "S1-S3 的 C3 RYW 率略低于 S0，不代表故障提高了弱配置的一致性。副本数量、被选择的 Secondary 和运行时调度改变了旧副本被抽中的概率；这些率描述的是该部署中的经验频率，而不是协议保证。" if z else
        "The slightly lower C3 RYW rates in S1-S3 do not mean faults strengthened C3. The number of available replicas, the selected Secondary, and runtime scheduling changed the chance of choosing a stale member. These rates are empirical frequencies in this deployment, not protocol guarantees.", st["body"]))

    section(story, "6.2 延迟" if z else "6.2 Latency", st, 2)
    latency_data = [["配置" if z else "Config", "S0 p50 / p95", "S1 p50 / p95", "S2 p50 / p95", "S3 p50 / p95"],
        ["C1", "3.19 / 9.24 ms", "2.09 / 5.84", "2.23 / 7.09", "2.05 / 6.07"],
        ["C2", "3.43 / 9.11 ms", "2.21 / 6.62", "2.84 / 9.73", "2.15 / 7.04"],
        ["C3", "1.48 / 5.00 ms", "1.01 / 3.35", "1.07 / 3.14", "0.88 / 2.85"],
        ["C4", "3.22 / 9.13 ms", "2.25 / 6.79", "2.24 / 6.65", "2.17 / 6.45"],
    ]
    story.append(make_table(latency_data, [23*mm, 36*mm, 36*mm, 36*mm, 36*mm], st))
    story.append(p(
        "表中为 RYW 单次“写后读”对的端到端延迟。C3 延迟最低，与 w:1/local 不等待多数确认相符；这也是其更弱可见性的代价。C2 的 WFR 基线 p95 为 42.27 ms，高于 C1 的 19.37 ms，显示跨 Secondary 因果读取可能等待满足 afterClusterTime。不同故障场景的较低中位数受容器、缓存和运行时波动影响，不应解释为故障优化。" if z else
        "The table reports end-to-end latency for one RYW write-read pair. C3 is fastest, consistent with w:1/local avoiding majority waits, but this accompanies weaker visibility. C2's baseline WFR p95 was 42.27 ms versus 19.37 ms for C1, consistent with a causal secondary read sometimes waiting to satisfy afterClusterTime. Lower medians in some fault scenarios reflect container, cache, and runtime variation and should not be interpreted as fault-induced optimization.", st["body"]))

    section(story, "6.3 T1/T2：选举过渡窗口" if z else "6.3 T1/T2: Election Transition Windows", st, 2)
    transition_data = [["场景" if z else "Scenario", "检查" if z else "Checks", "违例" if z else "Violations", "操作错误" if z else "Op. errors", "平均选举时间" if z else "Mean election", "强配置成功操作" if z else "Strong successful ops"],
        ["T1", "9,635", "2,420 (all C3)", "34 (all election)", "11,334 ms", "0 violations"],
        ["T2", "10,974", "2,532 (all C3)", "60 (all election)", "15,041 ms", "0 violations"],
    ]
    story.append(make_table(transition_data, [17*mm, 25*mm, 38*mm, 38*mm, 27*mm, 30*mm], st))
    story.append(Spacer(1, 4*mm))
    story.append(figure(FIG / "02_transition_window_outcomes.png", "图 3. T1/T2 中各配置的成功检查、违例和操作错误。" if z else "Figure 3. Successful checks, violations, and operation errors by configuration in T1/T2.", st))
    story.append(figure(FIG / "03_fault_timing.png", "图 4. S2、S3、T1 与 T2 的选举时间。T1/T2 显示三个随机种子。" if z else "Figure 4. Election timing for S2, S3, T1, and T2. T1/T2 show all three seeds.", st))
    phase_data = [["场景" if z else "Scenario", "pre", "election", "post"],
        ["T1 C3", "771/993 = 77.64%", "537/701 = 76.60%", "1,112/1,728 = 64.35%"],
        ["T2 C3", "849/1,075 = 78.98%", "413/550 = 75.09%", "1,270/2,003 = 63.40%"],
    ]
    story.append(make_table(phase_data, [28*mm, 46*mm, 46*mm, 47*mm], st))
    story.append(p(
        "过渡实验给出两个互补结论。第一，C1、C2、C4 的成功 RYW 对仍然零违例；第二，选举阶段出现 34 与 60 次操作错误，说明强一致设置在无法立即找到可写 Primary 时牺牲了短暂可用性。C3 在故障前已经很弱，其 pre 与 election 违例率接近，因此选举没有创造一种新的 C3 一致性缺陷，主要新增的是暂时失败。" if z else
        "The transition tests give two complementary conclusions. First, successful RYW pairs under C1, C2, and C4 still had zero violations. Second, 34 and 60 operation errors occurred during elections, showing a temporary availability cost when no writable Primary could be selected immediately. C3 was already weak before each fault, with similar pre and election violation rates; the election did not create a new C3 consistency defect, but mainly added transient failures.", st["body"]))

    section(story, "6.4 S4：受控复制延迟" if z else "6.4 S4: Controlled Replication Lag", st, 2)
    s4_data = [["模型" if z else "Model", "违例 / 检查" if z else "Violations / checks", "违例率" if z else "Rate", "解释" if z else "Interpretation"],
        ["RYW", "1,250 / 1,500", "83.33%", "写后命中被冻结 Secondary，读到旧版本。" if z else "Post-write read hits the frozen Secondary."],
        ["MR", "747 / 1,500", "49.80%", "交替访问当前与冻结 Secondary，后读倒退。" if z else "Alternation between current and frozen secondaries."],
        ["MW", "0 / 3 validations", "0%", "Primary 接收顺序写；最终版本有序。" if z else "Primary accepts ordered writes; final state remains ordered."],
        ["WFR", "750 / 1,500", "50.00%", "依赖写基于旧 Secondary 的父版本。" if z else "Dependent write is based on a stale parent read."],
    ]
    story.append(make_table(s4_data, [23*mm, 39*mm, 25*mm, 80*mm], st))
    story.append(Spacer(1, 4*mm))
    story.append(figure(FIG / "04_s4_model_violation_rates.png", "图 5. S4 中弱配置 C3 的各模型违例率。" if z else "Figure 5. Per-model violation rates for weak configuration C3 under S4.", st))
    story.append(p(
        "S4 共 4,503 次检查、0 次数据库操作错误、2,747 次违例（61.00%）。冻结节点在测试结束时落后 38 秒；恢复复制后，连续三次状态检查均在 1 秒内追平，完整恢复过程耗时 27,051 ms。MR 与 WFR 接近 50% 与测试在“冻结/当前”两个 Secondary 之间交替选择相吻合，提供了强机制证据。" if z else
        "S4 completed 4,503 checks with zero database-operation errors and 2,747 violations (61.00%). The frozen member was 38 seconds behind at test end. After apply resumed, three consecutive status checks each found lag within one second; the full recovery took 27,051 ms. MR and WFR near 50% match alternating selection between one frozen and one current Secondary, providing strong mechanistic evidence.", st["body"]))

    section(story, "7. 预测与观察对照" if z else "7. Predictions Versus Observations", st)
    pred_data = [["配置" if z else "Config", "预测" if z else "Prediction", "观察" if z else "Observation", "结论" if z else "Assessment"],
        ["C1", "四项成立" if z else "All four hold", "所有 S0-S3 检查与 T1/T2 成功 RYW 均零违例" if z else "Zero violations in S0-S3 and successful T1/T2 RYW", "一致" if z else "Agrees"],
        ["C2", "跨副本因果会话仍成立" if z else "Cross-member causal session holds", "读取 Secondary 时仍零违例；部分尾延迟较高" if z else "Zero violations on Secondary reads; some higher tail latency", "一致" if z else "Agrees"],
        ["C3", "RYW/MR/WFR 可能违例，MW 通常成立" if z else "RYW/MR/WFR may fail; MW usually holds", "S0 观察 RYW/MR；S4 观察 RYW/MR/WFR；MW 为零" if z else "S0 exposed RYW/MR; S4 exposed RYW/MR/WFR; MW zero", "一致；S4 补足机制" if z else "Agrees; S4 completes mechanism"],
        ["C4", "本负载中成立，但不是通用因果保证" if z else "Holds here, not a general causal guarantee", "本实验零违例" if z else "Zero violations in this workload", "有限支持" if z else "Supported within scope"],
    ]
    story.append(make_table(pred_data, [18*mm, 48*mm, 72*mm, 29*mm], st))
    story.append(p(
        "最重要的区分是安全性与可用性。强配置没有把选举期间的失败请求伪装成一致性违例：它们拒绝或重试无法安全完成的操作，而成功完成的历史继续满足 RYW。相反，C3 提供低延迟和较高可用读取，但允许成功返回旧版本。" if z else
        "The key distinction is safety versus availability. The strong configurations did not convert election-time failures into consistency anomalies: unsafe operations failed or retried, while successful histories continued to satisfy RYW. C3 instead offered low-latency, highly available reads that could successfully return stale versions.", st["callout"]))

    # Give the conclusion callout enough breathing room before the limitations.
    story.append(Spacer(1, 5 * mm))

    section(story, "8. 局限性与有效性威胁" if z else "8. Limitations and Threats to Validity", st)
    limits = [
        "三个节点位于同一 VM，共享硬件、磁盘与底层网络；容器隔离不能替代三台物理或虚拟主机。",
        "S1-S3 在选举完成后运行完整矩阵；T1/T2 只在过渡窗口测试 RYW，其他三项模型尚未持续压测。",
        "S3 将旧 Primary 同时与副本和客户端隔离，并未模拟分区两侧各有客户端的 split-client 历史。",
        "S4 使用 enableTestCommands 和 rsSyncApplyStop，是为了因果诊断而设计的极端失效点，不代表真实网络延迟分布。",
        "每项仅使用三个种子；工作负载、驱动服务器选择与本机调度会改变经验违例率。零违例不是数学证明。",
        "阶段以操作开始时间分类；跨越选举边界的单次操作仍只属于一个阶段。",
        "MW 运行了每个配置每种子 500 次顺序写，但汇总中的主要判定分母是每种子的最终历史验证，因此表中显示 3 次验证。",
        "云账单存在报告延迟。实验结束时 VM 已停止；控制台显示本月总成本 0.14 美元、抵扣 0.14 美元、净成本 0，50 美元额度剩余 49.64 美元（约 99%）。",
    ] if z else [
        "All members share one VM, hardware, disk, and underlying network; container isolation is not equivalent to three physical or virtual hosts.",
        "S1-S3 run the full matrix after election completion. T1/T2 cover only RYW continuously during the transition; the other three models were not stressed through elections.",
        "S3 isolates the old Primary from both peers and the client. It does not create split-client histories with clients on both partition sides.",
        "S4 uses enableTestCommands and rsSyncApplyStop as an extreme diagnostic failpoint, not as a realistic latency distribution.",
        "Only three seeds are used. Workload shape, driver selection, and local scheduling influence empirical rates. Zero observed violations is not a mathematical proof.",
        "Phases are assigned by operation start time; an operation crossing an election boundary still belongs to one phase.",
        "MW performs 500 sequential writes per configuration and seed, but the summary denominator counts one final history validation per seed; therefore the table reports three validations.",
        "Cloud billing has reporting lag. The VM was stopped after experimentation. The console showed USD 0.14 gross month cost, USD 0.14 credits, zero net cost, and USD 49.64 of the USD 50 credit remaining (about 99%).",
    ]
    for item in limits:
        story.append(bullet(item, st["bullet"]))

    section(story, "9. 可复现性" if z else "9. Reproducibility", st)
    section(story, "9.1 主要命令" if z else "9.1 Main Commands", st, 2)
    commands = """# Baseline S0
docker compose run --rm --no-deps runner python -m experiments.run_baseline \\
  --iterations 500 --seeds 20260830,20260831,20260832 --label formal

# Stable fault scenarios (replace the scenario name for S2/S3)
./scripts/run_fault_scenario.sh S1-secondary-failure 500 \\
  20260830,20260831,20260832 formal

# Transition windows; repeat for seeds 20260830-20260832
./scripts/run_transition_scenario.sh T1-primary-stop-transition 20260830 formal 35 3
./scripts/run_transition_scenario.sh T2-primary-partition-transition 20260830 formal 35 3

# Controlled replication lag
./scripts/run_replication_lag_scenario.sh 500 \\
  20260830,20260831,20260832 formal

# Recovery and report figures
./scripts/restore_cluster.sh
./scripts/cluster_status.sh
python3 -m analysis.generate_report_figures"""
    story.append(p(commands.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br/>"), st["code"]))
    story.append(p(
        "仓库保存 compose 配置、初始化脚本、故障注入脚本、Python 工作负载、正式 summary JSON、汇总说明和生成图表的代码。原始 JSONL 可由上述命令重新生成。为避免意外计费，实验结束后应在 Google Cloud 控制台停止 VM，并确认实例状态为 TERMINATED；持久磁盘仍可能持续计费。" if z else
        "The repository contains Compose configuration, initialization and fault scripts, Python workloads, formal summary JSON, result narratives, and chart-generation code. Raw JSONL can be regenerated with the commands above. To avoid unintended compute charges, stop the VM in Google Cloud after experiments and verify TERMINATED status; persistent disk may continue to incur storage charges.", st["body"]))

    section(story, "9.2 正式运行标识" if z else "9.2 Formal Run Identifiers", st, 2)
    run_ids = [
        ["S0", "baseline-s0-formal-20260830T154711Z-3c931c32"],
        ["S1", "s1-secondary-failure-formal-20260830T181846Z-8e657452"],
        ["S2", "s2-primary-failure-formal-20260830T182320Z-f604f5eb"],
        ["S3", "s3-primary-partition-formal-rerun-20260830T183455Z-59f3d378"],
        ["S4", "s4-secondary-replication-lag-formal-20260831T081523Z-85b1e3b3"],
        ["T1", "6cad906c; 867b572c; ae94f015"],
        ["T2", "0609280f; b9f2cd1b; ceb526e5"],
    ]
    story.append(make_table([["场景" if z else "Scenario", "Selected formal run ID / suffix"]] + run_ids, [26*mm, 141*mm], st))

    section(story, "10. 结论" if z else "10. Conclusion", st)
    story.append(p(
        "实验完成了从理论预测、复制集部署、可调配置、四模型工作负载到故障注入和机制验证的闭环。结果表明，MongoDB 的强会话配置在本实验所有成功历史中保持四项客户端中心保证；弱 Secondary 读取能以更低延迟返回，但在正常复制、选举前后以及受控滞后下会返回旧版本。节点停机与网络分区最直接的过渡影响是短暂不可用，而不是强配置成功操作的一致性退化。最终，S4 把 RYW、MR 与 WFR 的弱行为同时放大，并保留 MW，从而说明四项会话保证是并列且可独立观察的。" if z else
        "The project completes a full cycle from theoretical prediction through replica-set deployment, tunable configurations, four executable model workloads, fault injection, and mechanistic validation. Strong MongoDB session configurations preserved all four client-centric guarantees in every successful history observed. Weak secondary reads returned faster but could return older versions during normal replication, around elections, and under controlled lag. The most direct transition effect of node failure and partition was temporary unavailability rather than degradation of successful operations under strong configurations. Finally, S4 amplified RYW, MR, and WFR failures while preserving MW, demonstrating that these session guarantees are complementary and independently observable.", st["body"]))

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
        "本项目使用 OpenAI ChatGPT/Codex 协助解释课程概念、规划实验、起草和审阅脚本、组织结果、生成图表与润色报告。所有云资源创建、命令执行、故障注入、结果文件检查、参考文献核对及最终结论均由项目成员监督和验证。报告中的实验数据来自仓库中保存的真实运行输出，不由 AI 虚构。项目成员对提交内容、实验解释和任何错误承担最终责任。" if z else
        "OpenAI ChatGPT/Codex was used to help explain course concepts, plan experiments, draft and review scripts, organize results, generate charts, and edit the report. Cloud-resource creation, command execution, fault injection, result-file inspection, source verification, and final conclusions were supervised and checked by the project member. Experimental values in this report come from the stored run outputs and were not fabricated by AI. The project member remains responsible for the submitted content, interpretation, and any errors.", st["body"]))

    return story


def build(lang: str, filename: str):
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
        author="Panyuxiang; Hou Jiacheng; Wu Jiarui",
        subject="DSA5208 Project 1 experimental report",
    )
    doc.multiBuild(report_content(lang, st))
    return path


def main() -> None:
    register_fonts()
    OUT.mkdir(parents=True, exist_ok=True)
    USER_OUT.mkdir(parents=True, exist_ok=True)
    outputs = [
        build("zh", "DSA5208_Project1_Report_ZH.pdf"),
        build("en", "DSA5208_Project1_Report_EN.pdf"),
    ]
    for src in outputs:
        shutil.copy2(src, USER_OUT / src.name)
        print(src)
        print(USER_OUT / src.name)


if __name__ == "__main__":
    main()
