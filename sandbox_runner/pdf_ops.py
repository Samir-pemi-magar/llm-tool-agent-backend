"""
    The actual pypdf logic. This file lives ONLY inside the sandbox image —
    it never runs in the main app process.
"""

from datetime import datetime

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

# --- shared report styling -------------------------------------------------
BRAND_NAVY = colors.HexColor("#1f2d3d")
BRAND_ACCENT = colors.HexColor("#3f6fb5")
BRAND_LIGHT = colors.HexColor("#f4f6f9")
BRAND_ROW_ALT = colors.HexColor("#eef1f6")
BRAND_GREY_TEXT = colors.HexColor("#5b6472")

# Any field value longer than this reads as prose, not a table cell.
LONG_TEXT_THRESHOLD = 60


def _footer(canvas, doc):
    """Page-number + generation-date footer, drawn on every page."""
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#d9dde3"))
    canvas.setLineWidth(0.5)
    canvas.line(0.5 * inch, 0.6 * inch, doc.pagesize[0] - 0.5 * inch, 0.6 * inch)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(BRAND_GREY_TEXT)
    canvas.drawString(0.5 * inch, 0.4 * inch, datetime.now().strftime("Generated %B %d, %Y"))
    canvas.drawRightString(doc.pagesize[0] - 0.5 * inch, 0.4 * inch, f"Page {doc.page}")
    canvas.restoreState()


def _is_narrative(data: list[dict]) -> bool:
    """True when records read as prose (long text values) rather than
    short tabular fields -- e.g. a model dumping a written summary into
    dict values instead of returning real rows."""
    values = [v for record in data for v in record.values() if v is not None]
    if not values:
        return False
    long_values = [v for v in values if len(str(v)) > LONG_TEXT_THRESHOLD]
    return len(long_values) >= max(1, len(values) // 2)


def read_pdf_text(file_path: str, page_number: int | None = None) -> dict:
    reader = PdfReader(file_path)
    if page_number is not None:
        if page_number < 1 or page_number > len(reader.pages):
            return {"error": f"page_number out of range. Document has {len(reader.pages)} pages."}
        text = reader.pages[page_number - 1].extract_text() or ""
        return {"page": page_number, "text": text}

    pages = [p.extract_text() or "" for p in reader.pages]
    return {"num_pages": len(pages), "pages": pages}


def get_pdf_metadata(file_path: str) -> dict:
    reader = PdfReader(file_path)
    meta = reader.metadata or {}
    return {
        "num_pages": len(reader.pages),
        "title": meta.get("/Title"),
        "author": meta.get("/Author"),
        "subject": meta.get("/Subject"),
        "creator": meta.get("/Creator"),
    }


def search_pdf_text(file_path: str, query: str) -> dict:
    reader = PdfReader(file_path)
    matches = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if query.lower() in text.lower():
            matches.append({"page": i, "snippet": text[:500]})
    return {"query": query, "matches": matches}


def _letterhead(story, title, subtitle_style):
    story.append(Paragraph(title or "Report", ParagraphStyle(
        "doc_title", fontName="Helvetica-Bold", fontSize=20, leading=24,
        textColor=BRAND_NAVY, spaceAfter=6,
    )))
    story.append(Paragraph(
        datetime.now().strftime("%B %d, %Y"), subtitle_style,
    ))
    story.append(Spacer(1, 0.08 * inch))
    story.append(HRFlowable(width="100%", thickness=1.2, color=BRAND_ACCENT, spaceAfter=0.25 * inch))


def _build_report(data: list[dict], title: str | None) -> tuple[list, tuple]:
    """Narrative layout: one styled section per record, key/value pairs
    rendered as labeled paragraphs instead of squeezed table cells."""
    styles = getSampleStyleSheet()
    subtitle_style = ParagraphStyle(
        "subtitle", fontName="Helvetica", fontSize=9, textColor=BRAND_GREY_TEXT,
    )
    label_style = ParagraphStyle(
        "label", fontName="Helvetica-Bold", fontSize=10.5, textColor=BRAND_ACCENT,
        spaceBefore=10, spaceAfter=3,
    )
    body_style = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=10, leading=14.5,
        textColor=colors.HexColor("#232830"), alignment=TA_LEFT,
    )

    story = []
    _letterhead(story, title, subtitle_style)

    for record in data:
        for key, value in record.items():
            if value is None or str(value).strip() == "":
                continue
            story.append(Paragraph(str(key), label_style))
            story.append(Paragraph(str(value), body_style))
        story.append(Spacer(1, 0.15 * inch))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e3e6ec")))
        story.append(Spacer(1, 0.05 * inch))

    return story, letter


def _build_table(data: list[dict], title: str | None) -> tuple[list, tuple]:
    """Genuine tabular layout for short, structured field values."""
    headers = list(data[0].keys())
    num_cols = len(headers)

    pagesize = landscape(letter) if num_cols > 5 else letter
    page_width = pagesize[0] - 1.0 * inch

    if num_cols <= 6:
        font_size = 9
    elif num_cols <= 10:
        font_size = 7.5
    else:
        font_size = 6.5

    cell_style = ParagraphStyle(
        "cell", fontName="Helvetica", fontSize=font_size, leading=font_size + 3,
        textColor=colors.HexColor("#232830"),
    )
    header_style = ParagraphStyle(
        "header", fontName="Helvetica-Bold", fontSize=font_size,
        leading=font_size + 3, textColor=colors.white,
    )
    subtitle_style = ParagraphStyle(
        "subtitle", fontName="Helvetica", fontSize=9, textColor=BRAND_GREY_TEXT,
    )

    def _cell(value) -> Paragraph:
        return Paragraph(str(value) if value is not None else "", cell_style)

    header_row = [Paragraph(h, header_style) for h in headers]
    body_rows = [[_cell(record.get(h, "")) for h in headers] for record in data]
    rows = [header_row] + body_rows

    col_width = page_width / num_cols
    table = Table(rows, colWidths=[col_width] * num_cols, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, BRAND_ACCENT),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#e3e6ec")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_ROW_ALT]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    story = []
    _letterhead(story, title, subtitle_style)
    story.append(table)
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph(f"{len(data)} record{'s' if len(data) != 1 else ''}", subtitle_style))

    return story, pagesize


def create_pdf_from_data(data: list[dict], output_path: str, title: str | None = None) -> dict:
    """
    Render a list of flat records into a polished PDF with a letterhead,
    accent styling, and a page-number/date footer.

    Records with short field values (numbers, model names, prices) render
    as a proper table. Records that look like prose -- long text values,
    e.g. a written summary handed back as a single dict -- render instead
    as titled report sections, since jamming a paragraph into a table
    cell is what made earlier PDFs look like a cramped spreadsheet.
    """
    if not data:
        return {"error": "no_data", "detail": "data must be a non-empty list of records"}

    if _is_narrative(data):
        story, pagesize = _build_report(data, title)
    else:
        story, pagesize = _build_table(data, title)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=pagesize,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.75 * inch,
    )
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)

    return {"created": output_path, "rows": len(data)}


REGISTRY = {
    "read_pdf_text": read_pdf_text,
    "get_pdf_metadata": get_pdf_metadata,
    "search_pdf_text": search_pdf_text,
    "create_pdf_from_data": create_pdf_from_data,
}