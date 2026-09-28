"""Extract structured text from approved HTML pages and PDFs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from io import BytesIO
import re
from typing import Any

from bs4 import BeautifulSoup, Tag


@dataclass
class ContentBlock:
    kind: str
    text: str = ""
    rows: list[list[str]] = field(default_factory=list)
    page_number: int | None = None


@dataclass
class ContentSection:
    section_path: list[str]
    blocks: list[ContentBlock] = field(default_factory=list)


@dataclass
class ExtractedDocument:
    source_url: str
    title: str
    document_date: str | None
    sections: list[ContentSection]
    page_count: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _html_document_date(soup: BeautifulSoup) -> str | None:
    selectors = (
        'meta[property="article:published_time"]',
        'meta[name="datePublished"]',
        'meta[name="date"]',
        "time[datetime]",
    )
    for selector in selectors:
        element = soup.select_one(selector)
        raw_date = element.get("content") or element.get("datetime") if element else None
        if raw_date:
            match = re.search(r"\d{4}-\d{2}-\d{2}", str(raw_date))
            if match:
                try:
                    return date.fromisoformat(match.group()).isoformat()
                except ValueError:
                    continue
    return None


def _table_rows(table: Tag) -> list[list[str]]:
    rows = []
    for row in table.find_all("tr"):
        cells = [_clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"], recursive=False)]
        if cells:
            rows.append(cells)
    return rows


def extract_html(payload: bytes, source_url: str) -> ExtractedDocument:
    """Extract headings, text blocks, and table rows while dropping page chrome/forms."""
    soup = BeautifulSoup(payload, "html.parser")
    title = _clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    document_date = _html_document_date(soup)

    for element in soup.select(
        "script, style, noscript, nav, header, footer, aside, form, button, input, select, textarea"
    ):
        element.decompose()
    for element in soup.select('[role="navigation"], [aria-hidden="true"]'):
        element.decompose()

    content = soup.find("main") or soup.find(id="content") or soup.find("article") or soup.body or soup
    sections: list[ContentSection] = []
    heading_stack: list[tuple[int, str]] = []
    current_section: ContentSection | None = None

    for element in content.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"]):
        if element.name == "li" and element.find_parent("li"):
            continue
        if element.name == "table" and element.find_parent("table"):
            continue
        if element.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            heading_level = int(element.name[1])
            heading_text = _clean_text(element.get_text(" ", strip=True))
            if not heading_text:
                continue
            while heading_stack and heading_stack[-1][0] >= heading_level:
                heading_stack.pop()
            heading_stack.append((heading_level, heading_text))
            current_section = ContentSection(section_path=[text for _, text in heading_stack])
            sections.append(current_section)
            continue

        if current_section is None:
            current_section = ContentSection(section_path=[title] if title else [])
            sections.append(current_section)

        if element.name == "table":
            rows = _table_rows(element)
            if rows:
                current_section.blocks.append(ContentBlock(kind="table", rows=rows))
        else:
            text = _clean_text(element.get_text(" ", strip=True))
            if text:
                kind = "list_item" if element.name == "li" else "paragraph"
                current_section.blocks.append(ContentBlock(kind=kind, text=text))

    return ExtractedDocument(
        source_url=source_url,
        title=title,
        document_date=document_date,
        sections=[section for section in sections if section.blocks],
    )


def extract_pdf(payload: bytes, source_url: str) -> ExtractedDocument:
    """Extract per-page text and table cells using pdfplumber's layout-aware API."""
    import pdfplumber

    sections: list[ContentSection] = []
    with pdfplumber.open(BytesIO(payload)) as pdf:
        title = _clean_text(str(pdf.metadata.get("Title") or ""))
        for page_number, page in enumerate(pdf.pages, start=1):
            blocks: list[ContentBlock] = []
            text = page.extract_text(layout=True) or page.extract_text() or ""
            text = text.strip()
            if text:
                blocks.append(
                    ContentBlock(kind="page_text", text=text, page_number=page_number)
                )
            for table in page.extract_tables() or []:
                rows = [
                    [_clean_text(cell or "") for cell in row]
                    for row in table
                    if row and any(cell and str(cell).strip() for cell in row)
                ]
                if rows:
                    blocks.append(
                        ContentBlock(kind="table", rows=rows, page_number=page_number)
                    )
            if blocks:
                sections.append(
                    ContentSection(section_path=[f"Page {page_number}"], blocks=blocks)
                )

        return ExtractedDocument(
            source_url=source_url,
            title=title,
            document_date=None,
            sections=sections,
            page_count=len(pdf.pages),
        )


def extract_document(payload: bytes, source_url: str, content_type: str) -> ExtractedDocument:
    """Choose an extractor from the file signature, rejecting unsupported content."""
    if payload.startswith(b"%PDF-"):
        return extract_pdf(payload, source_url)
    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_type in {"text/html", "application/xhtml+xml"}:
        return extract_html(payload, source_url)
    raise ValueError(f"Unsupported source content type: {content_type or '(missing)'}")