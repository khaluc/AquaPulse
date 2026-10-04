"""Render editable SVG and high-resolution PNG project-story diagrams.

Uses existing Pillow and Windows Arial fonts. No external service is required.
Run: backend/.venv/Scripts/python.exe docs/project-story-figures/render_figures.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
INK = "#1C283B"
MUTED = "#56647B"
PURPLE = "#7766DF"
PALE = "#F5F3FF"
LINE = "#647187"
BORDER = "#D6DCE6"
SCALE = 2


class Diagram:
    def __init__(self, number: int, title: str, subtitle: str, height: int):
        self.width = 1800
        self.height = height
        self.number = number
        self.title = title
        self.image = Image.new("RGB", (self.width * SCALE, height * SCALE), "white")
        self.draw = ImageDraw.Draw(self.image)
        self.svg = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="{height}" '
            f'viewBox="0 0 1800 {height}" role="img" aria-labelledby="title desc">',
            f"<title id=\"title\">{escape(title)}</title>",
            f"<desc id=\"desc\">{escape(subtitle)}</desc>",
            '<rect width="100%" height="100%" fill="white"/>',
        ]
        self.boxes: list[dict] = []
        self.texts: list[str] = []
        self.rect(80, 55, 1640, 87, fill=PURPLE, stroke=PURPLE, radius=0)
        self.text(110, 75, title, size=43, bold=True, fill="white")
        self.text(1652, 73, f"{number:02}", size=44, bold=True, fill="white")
        self.text(82, 164, subtitle, size=27, fill=MUTED)

    def font(self, size: int, bold: bool = False):
        filename = "arialbd.ttf" if bold else "arial.ttf"
        return ImageFont.truetype(str(Path("C:/Windows/Fonts") / filename), size * SCALE)

    def width_of(self, text: str, size: int, bold: bool = False):
        return self.draw.textlength(text, font=self.font(size, bold)) / SCALE

    def wrap(self, text: str, width: float, size: int, bold: bool = False):
        lines: list[str] = []
        for paragraph in text.split("\n"):
            line = ""
            for word in paragraph.split():
                candidate = f"{line} {word}".strip()
                if self.width_of(candidate, size, bold) <= width:
                    line = candidate
                else:
                    if not line:
                        raise ValueError(f"Word exceeds text box: {word}")
                    lines.append(line)
                    line = word
            lines.append(line)
        return lines

    def text(self, x, y, text, *, size=28, bold=False, fill=INK, align="left", max_width=None):
        width = self.width_of(text, size, bold)
        if max_width is not None and width > max_width + 0.1:
            raise ValueError(f"Text overflow ({width:.1f} > {max_width}): {text}")
        left = x - width / 2 if align == "center" else x
        if left < 0 or left + width > self.width:
            raise ValueError(f"Text exceeds canvas: {text}")
        self.draw.text((left * SCALE, y * SCALE), text, font=self.font(size, bold), fill=fill, anchor="lt")
        weight = "700" if bold else "400"
        self.svg.append(
            f'<text x="{left:.2f}" y="{y:.2f}" font-family="Arial, sans-serif" '
            f'font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'dominant-baseline="text-before-edge">{escape(text)}</text>'
        )
        self.texts.append(text)

    def rect(self, x, y, width, height, *, fill="white", stroke=INK, radius=8, line_width=2):
        bbox = tuple(round(v * SCALE) for v in (x, y, x + width, y + height))
        self.draw.rounded_rectangle(bbox, radius=radius * SCALE, fill=fill, outline=stroke,
                                    width=max(1, round(line_width * SCALE)))
        self.svg.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" '
            f'rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="{line_width}"/>'
        )

    def box(self, x, y, width, height, title, body="", *, accent=False, title_size=32, body_size=28):
        self.rect(x, y, width, height, fill=PALE if accent else "white",
                  stroke=PURPLE if accent else INK, line_width=2.4)
        while True:
            title_lines = self.wrap(title, width - 48, title_size, True)
            body_lines = self.wrap(body, width - 48, body_size) if body else []
            title_step = title_size * 1.15
            body_step = body_size * 1.20
            content_height = len(title_lines) * title_step + (10 if body_lines else 0) + len(body_lines) * body_step
            if content_height <= height - 20:
                break
            if title_size <= 28 or body_size <= 24:
                raise ValueError(f"Box text overflows {title}: {content_height:.1f} > {height - 20}")
            title_size -= 1
            body_size -= 1
        cursor_y = y + (height - content_height) / 2
        for line in title_lines:
            self.text(x + width / 2, cursor_y, line, size=title_size, bold=True,
                      align="center", max_width=width - 48)
            cursor_y += title_step
        if body_lines:
            cursor_y += 10
        for line in body_lines:
            self.text(x + width / 2, cursor_y, line, size=body_size, fill=MUTED,
                      align="center", max_width=width - 48)
            cursor_y += body_step
        item = {"title": title, "body": body, "bounds": [x, y, x + width, y + height],
                "title_size": title_size, "body_size": body_size}
        self.boxes.append(item)
        return item

    def group(self, x, y, width, height, label):
        self.rect(x, y, width, height, fill="#FBFCFE", stroke=BORDER, radius=12, line_width=2)
        self.text(x + 24, y + 20, label, size=26, bold=True, fill=MUTED)

    def line(self, points, *, color=LINE, width=2.8):
        coords = [(round(x * SCALE), round(y * SCALE)) for x, y in points]
        self.draw.line(coords, fill=color, width=round(width * SCALE), joint="curve")
        self.svg.append(f'<polyline points="{" ".join(f"{x},{y}" for x, y in points)}" '
                        f'fill="none" stroke="{color}" stroke-width="{width}" '
                        'stroke-linejoin="round" stroke-linecap="round"/>')

    def arrowhead(self, previous, end, color=LINE):
        angle = math.atan2(end[1] - previous[1], end[0] - previous[0])
        length, half_width = 14, 6
        back = (end[0] - length * math.cos(angle), end[1] - length * math.sin(angle))
        points = [end,
                  (back[0] + half_width * math.sin(angle), back[1] - half_width * math.cos(angle)),
                  (back[0] - half_width * math.sin(angle), back[1] + half_width * math.cos(angle))]
        self.draw.polygon([(round(x * SCALE), round(y * SCALE)) for x, y in points], fill=color)
        self.svg.append(f'<polygon points="{" ".join(f"{x:.2f},{y:.2f}" for x, y in points)}" fill="{color}"/>')

    def arrow(self, points, *, color=LINE, both=False):
        self.line(points, color=color)
        self.arrowhead(points[-2], points[-1], color)
        if both:
            self.arrowhead(points[1], points[0], color)

    def footer(self, text):
        self.line([(80, self.height - 74), (1720, self.height - 74)], color=BORDER, width=1.5)
        self.text(82, self.height - 49, "AQUAPULSE", size=22, bold=True, fill=PURPLE)
        self.text(300, self.height - 49, text, size=22, fill=MUTED, max_width=1400)

    def save(self, filename):
        png_path = HERE / f"{filename}.png"
        svg_path = HERE / f"{filename}.svg"
        self.image.save(png_path, optimize=True)
        svg_path.write_text("\n".join(self.svg + ["</svg>"]), encoding="utf-8")
        return {"file": png_path.name, "svg": svg_path.name,
                "title": self.title, "size": list(self.image.size),
                "bytes": png_path.stat().st_size, "boxes": self.boxes, "labels": self.texts}


def observation_pipeline():
    d = Diagram(1, "Citizen observation to community action",
                "A photograph starts a workflow: analysis, evidence, verification and follow-up.", 1680)
    d.group(95, 560, 1610, 410, "ANALYSIS MODES")
    d.arrow([(900, 342), (900, 402)])
    d.arrow([(900, 520), (900, 550), (465, 550), (465, 606)])
    d.arrow([(900, 520), (900, 550), (1335, 550), (1335, 606)])
    d.arrow([(465, 724), (465, 774)])
    d.arrow([(1335, 724), (1335, 774)])
    d.arrow([(465, 942), (465, 982), (900, 982), (900, 1020)])
    d.arrow([(1335, 942), (1335, 982), (900, 982), (900, 1020)])
    d.arrow([(900, 1160), (900, 1210)])
    d.arrow([(900, 1340), (900, 1378), (330, 1378), (330, 1425)])
    d.arrow([(900, 1340), (900, 1425)])
    d.arrow([(900, 1340), (900, 1378), (1470, 1378), (1470, 1425)])
    d.box(590, 226, 620, 116, "Photo + field observations", "Reporter answers, location and time")
    d.box(590, 402, 620, 118, "Image quality gate", "Resolution, brightness and sharpness")
    d.box(140, 606, 650, 118, "Containers / standing water", "Use models trained for container scenes")
    d.box(1010, 606, 650, 118, "River surface / other signs", "Use scene description and field answers")
    d.box(140, 774, 650, 168, "Local models + Kimi", "YOLO11n: container boxes\nYOLO11s-seg: in-container water\nKimi description + reporter answers")
    d.box(1010, 774, 650, 168, "Kimi + reporter answers", "Describe visible environmental signs\nContainer models are skipped\nMissing evidence remains unavailable")
    d.box(500, 1020, 800, 140, "Combine evidence and calculate indicators",
          "Keep risk and confidence separate\nExplain findings, conflicts and missing data", accent=True)
    d.box(500, 1210, 800, 130, "Store the report and supporting evidence",
          "Location linking, duplicate handling and alerts")
    d.box(80, 1425, 500, 150, "Maps + canal passports", "Location summaries\nHistory and evidence", title_size=30)
    d.box(650, 1425, 500, 150, "Human verification", "Volunteer / expert review\nFindings and follow-up photos", title_size=30)
    d.box(1220, 1425, 500, 150, "Missions + dashboard", "Community activities\nRecorded workflow progress", title_size=30)
    d.footer("Preliminary indicators support review; water safety requires appropriate sampling.")
    return d.save("01-observation-pipeline")


def training_and_evaluation():
    d = Diagram(2, "Data preparation, training and evaluation",
                "Locally fine-tuned YOLO models; saved detector results from the clean test split.", 1900)
    d.arrow([(900, 332), (900, 382)])
    d.arrow([(900, 536), (900, 562), (490, 562), (490, 602)])
    d.arrow([(900, 536), (900, 562), (1310, 562), (1310, 602)])
    d.arrow([(490, 762), (490, 814)])
    d.arrow([(1310, 762), (1310, 814)])
    d.arrow([(490, 1016), (490, 1080)])
    d.arrow([(1310, 1016), (1310, 1080)])
    d.arrow([(490, 1224), (490, 1260), (900, 1260), (900, 1300)])
    d.arrow([(1310, 1224), (1310, 1260), (900, 1260), (900, 1300)])
    d.box(380, 226, 1040, 106, "VisText-Mosquito V2", "Mendeley Data • dataset attribution: CC BY 4.0")
    d.box(200, 382, 1400, 154, "Clean data and split by scene group",
          "Remove identified stock previews, augmented copies and duplicates\nRemap labels • group similar scenes and burst photos • split seed 42")
    d.box(150, 602, 680, 160, "Container detection • 1,640 images",
          "1,132 train / 341 validation / 167 test\nTire, plastic container, pot, coconut shell, drain", title_size=31, body_size=27)
    d.box(970, 602, 680, 160, "Water masks • 141 images",
          "89 train / 33 validation / 19 test\nOne water class • water inside containers", title_size=31)
    d.box(150, 814, 680, 202, "Fine-tune pretrained detectors",
          "YOLO11n: 45 completed / 50 max epochs\nYOLO11s: 50 completed / 50 max epochs\n640 px input • PyTorch + CUDA • seed 0", body_size=27)
    d.box(970, 814, 680, 202, "Fine-tune pretrained segmenters",
          "YOLO11n-seg: 62 / 100 max epochs\nYOLO11s-seg: 200 / 200 max epochs\n640 px input • PyTorch + CUDA • seed 0", body_size=27)
    d.box(150, 1080, 680, 144, "Select threshold, then test",
          "Validation target: 80% box recall\nTest match: same class, IoU >= 0.5", title_size=31)
    d.box(970, 1080, 680, 144, "Keep segmentation scope visible",
          "Small, container-only training dataset\nWater masks serve as supporting evidence", title_size=31)
    d.box(250, 1300, 1300, 142, "ONNX exports → CPU inference in FastAPI",
          "Default detector: clean YOLO11n • default water model: YOLO11s-seg\nONNX Runtime + OpenCV + NumPy", accent=True, body_size=27)
    d.rect(100, 1500, 1600, 228, stroke=BORDER, fill="#FBFCFE")
    d.text(130, 1520, "DETECTOR TEST RESULTS • SAME 167 CLEAN TEST IMAGES / 316 OBJECTS", size=26, bold=True)
    columns = [195, 450, 720, 1000, 1260, 1505]
    for x, label in zip(columns, ["Model", "Threshold", "Precision", "Box recall", "mAP50", "mAP50–95"]):
        d.text(x, 1568, label, size=26, bold=True, align="center")
    d.line([(130, 1607), (1660, 1607)], color=BORDER, width=1.5)
    for y, row in [(1624, ["YOLO11n", "0.35", "75.43%", "82.59%", "0.7834", "0.5057"]),
                   (1675, ["YOLO11s", "0.25", "76.33%", "81.65%", "0.7550", "0.5325"])]:
        for x, cell in zip(columns, row):
            d.text(x, y, cell, size=28, align="center", fill=PURPLE if x >= 1260 else INK)
    d.text(900, 1760, "Tire class: only 3 test objects. No background-only test images for false-alarm estimation.",
           size=25, align="center")
    d.footer("Kimi is an external API model; the detector and segmenters are the fine-tuned models.")
    return d.save("02-training-and-evaluation")


def system_architecture():
    d = Diagram(3, "Web application and deployment architecture",
                "AWS EC2 deployment with Docker Compose, local ONNX inference and external data services.", 1440)
    d.group(80, 354, 1140, 958, "AMAZON LINUX / EC2")
    d.group(1290, 474, 450, 796, "EXTERNAL SERVICES")
    d.arrow([(650, 320), (650, 424)], both=True)
    d.arrow([(650, 530), (650, 592)], both=True)
    d.arrow([(400, 768), (400, 850)], both=True)
    d.arrow([(900, 768), (900, 850)], both=True)
    d.arrow([(900, 768), (1180, 768), (1180, 1166), (1130, 1166)], both=True)
    d.arrow([(1110, 660), (1320, 660)], both=True, color=PURPLE)
    d.arrow([(1110, 706), (1250, 706), (1250, 1010), (1320, 1010)], both=True)
    d.box(270, 226, 760, 94, "Browser • Vietnamese / English", "HTML, CSS, JavaScript and Leaflet", body_size=27)
    d.box(340, 424, 620, 106, "Caddy reverse proxy", "HTTPS • public ports 80 / 443", body_size=27)
    d.box(190, 592, 920, 176, "FastAPI application container",
          "Analysis, report storage and scoring\nMaps, passports, verification, missions and dashboard\nHTTPX API adapters • protected reviewer routes", accent=True, body_size=27)
    d.box(130, 850, 490, 202, "Local model runtime",
          "ONNX Runtime • CPU\nYOLO11n container detector\nYOLO11s-seg water masks\nOpenCV + NumPy", title_size=30, body_size=26)
    d.box(670, 850, 460, 202, "PostgreSQL + PostGIS",
          "Reports and review events\nAlerts, missions and points\nSpatial queries + canal links\nPersistent database volume", title_size=29, body_size=26)
    d.box(670, 1100, 460, 132, "Photo storage volume",
          "Re-encoded report images\nReviewer access", title_size=30, body_size=26)
    d.box(1320, 574, 390, 172, "Kimi API",
          "kimi-k3 • Model Studio\nProcessed image + prompt\nStructured scene description", accent=True, title_size=30, body_size=25)
    d.box(1320, 890, 390, 270, "Reference / context",
          "OneAquaHealth API\nOpen-Meteo rainfall\nGoogle News RSS\nOpenStreetMap geometry\nImported / synced data", title_size=29, body_size=25)
    d.text(126, 1261, "Database and model runtime stay inside the deployment.", size=25, fill=MUTED)
    d.footer("Published measurements and news remain separate from citizen-report risk scores.")
    return d.save("03-system-architecture")


def evidence_and_verification():
    d = Diagram(4, "Evidence fusion and human verification",
                "Model outputs help prepare a report; rules and reviewers control what happens next.", 1760)
    d.arrow([(346, 440), (346, 482), (900, 482), (900, 530)])
    d.arrow([(900, 440), (900, 530)])
    d.arrow([(1454, 440), (1454, 482), (900, 482), (900, 530)])
    d.arrow([(900, 698), (900, 746), (505, 746), (505, 788)])
    d.arrow([(900, 698), (900, 746), (1295, 746), (1295, 788)])
    d.arrow([(505, 970), (505, 1010), (900, 1010), (900, 1060)])
    d.arrow([(1295, 970), (1295, 1010), (900, 1010), (900, 1060)])
    d.arrow([(900, 1250), (900, 1320)])
    d.text(935, 1277, "When verification is required", size=24, fill=MUTED)
    d.arrow([(900, 1476), (900, 1540)])
    d.box(96, 236, 500, 204, "Local model evidence",
          "Containers + in-container water\nBase source weight: 0.5\nIncluded only when models ran", title_size=30, body_size=26)
    d.box(650, 236, 500, 204, "Kimi scene description",
          "Visible signs + stated certainty\nBase source weight: 0.3\nAPI suggestions may need review", title_size=30, body_size=26)
    d.box(1204, 236, 500, 204, "Reporter observations",
          "Field answers + recorded reliability\nBase source weight: 0.2\nWeight adjusted by reliability", title_size=30, body_size=26)
    d.box(380, 530, 1040, 168, "Combine the available evidence for each sign",
          "Renormalize source weights • record conflicts and unknowns\nA vision-only suggestion can trigger a question without confirming the sign", accent=True, body_size=27)
    d.box(180, 788, 650, 182, "Risk / ecology / human impact",
          "Rule-based indicators from available reports\nA photograph does not establish water safety", title_size=30, body_size=27)
    d.box(970, 788, 650, 182, "Confidence — shown separately",
          "0.5 × agreement + 0.3 × coverage\n+ 0.2 × image quality\nApplication indicator; not disease probability", title_size=30, body_size=26)
    d.box(390, 1060, 1020, 190, "Choose the next step",
          "Serious signs / conflicts / low confidence: verification\nOther uncertain cases: ask the reporter to confirm\nOtherwise: show the preliminary result", title_size=32, body_size=27)
    d.box(380, 1320, 1040, 156, "Human verification controls river alert escalation",
          "Yellow: unverified report • Orange: on-site volunteer confirmation\nRed: expert confirmation", title_size=31, body_size=27)
    d.box(380, 1540, 1040, 116, "Keep the evidence and decision history",
          "Update reports, alerts, missions and documented follow-up", accent=True, title_size=31, body_size=27)
    d.footer("Source weights and confidence are application rules, not laboratory measurements.")
    return d.save("04-evidence-and-verification")


def main():
    results = [observation_pipeline(), training_and_evaluation(), system_architecture(), evidence_and_verification()]
    (HERE / "manifest.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    (HERE / "preview.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>AquaPulse project figures</title>'
        '<style>body{font:16px Arial;background:#f2f3f7;color:#1c283b;margin:0;padding:36px}'
        'main{max-width:1120px;margin:auto}article{background:white;padding:24px;margin:24px 0;'
        'border:1px solid #d6dce6;border-radius:12px}img{width:100%;height:auto}a{color:#6654c8}</style>'
        '<main><h1>AquaPulse — Project Story figures</h1>'
        '<p>Four diagrams. PNG files are ready to upload; SVG files are editable.</p>'
        + ''.join(f'<article><h2>{escape(r["title"])}</h2><p><a href="{r["file"]}">PNG</a> · '
                  f'<a href="{r["svg"]}">SVG</a></p><img src="{r["file"]}" '
                  f'alt="{escape(r["title"])}"></article>' for r in results)
        + '</main></html>', encoding="utf-8")
    (HERE / "README.md").write_text(
        '# AquaPulse project-story figures\n\n'
        'Four English diagrams, with a white background, purple title bars and flowchart connectors.\n\n'
        '| File | Place in the story |\n| --- | --- |\n'
        '| 01-observation-pipeline.png | After What it does |\n'
        '| 02-training-and-evaluation.png | After detector evaluation |\n'
        '| 03-system-architecture.png | After deployment |\n'
        '| 04-evidence-and-verification.png | After Combining the evidence |\n\n'
        'Use the PNGs when adding images to the project submission. SVGs are editable originals. '
        'Each PNG is 3600 pixels wide and under 1 MB. Open preview.html to see all four.\n\n'
        'The full story is in ../project-story.en.md and includes relative image links. '
        'Those local links need to be replaced by uploaded image URLs in an online form.\n\n'
        'Regenerate locally with the repository Python environment and render_figures.py.\n', encoding="utf-8")
    zip_path = HERE / "AquaPulse-Project-Story-Figures.zip"
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for result in results:
            for key in ("file", "svg"):
                archive.write(HERE / result[key], result[key])
        archive.write(HERE / "preview.html", "preview.html")
        archive.write(HERE / "manifest.json", "manifest.json")
        archive.write(HERE / "README.md", "README.md")
    print(json.dumps({"figures": [{k: r[k] for k in ("file", "svg", "size", "bytes")} for r in results],
                      "zip": zip_path.name}, indent=2))


if __name__ == "__main__":
    from engineering_figures import main as render_engineering_figures
    render_engineering_figures()
