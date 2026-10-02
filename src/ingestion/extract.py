"""Extract structured text from approved HTML pages and PDFs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
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
    question: str | None = None
    label: str | None = None
    value: str | None = None
    title: str | None = None


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
    warnings: list[str] = field(default_factory=list)

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


def _class_has_suffix(element: Tag, suffix: str) -> bool:
    return any(str(class_name).endswith(f"__{suffix}") for class_name in element.get("class", []))


def _sensitive_workflow_text(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:SMS\s+to\s+be\s+sent\s+as|enter\s+your\s+folio\s+number|"
            r"folio\s+number.{0,100}\bpassword\b)\b",
            text,
            re.IGNORECASE,
        )
    )


def _pdf_document_date(page_texts: list[str]) -> str | None:
    front_matter = "\n".join(page_texts[:2])
    month = (
        r"January|February|March|April|May|June|July|August|September|October|"
        r"November|December"
    )
    dated = re.search(
        rf"\bdated\s+({month})\s+(\d{{1,2}}),?\s+(\d{{4}})\b",
        front_matter,
        re.IGNORECASE,
    )
    if dated:
        parsed = datetime.strptime(
            f"{dated.group(1)} {dated.group(2)} {dated.group(3)}", "%B %d %Y"
        )
        return parsed.date().isoformat()

    month_year = re.search(rf"\b({month})\s+(\d{{4}})\b", front_matter, re.IGNORECASE)
    if month_year:
        parsed_month = datetime.strptime(month_year.group(1), "%B").month
        return f"{month_year.group(2)}-{parsed_month:02d}"

    full_date = re.search(
        rf"\b({month})\s+(\d{{1,2}}),?\s+(\d{{4}})\b",
        front_matter,
        re.IGNORECASE,
    )
    if full_date:
        parsed = datetime.strptime(
            f"{full_date.group(1)} {full_date.group(2)} {full_date.group(3)}",
            "%B %d %Y",
        )
        return parsed.date().isoformat()
    return None


def extract_html(payload: bytes, source_url: str) -> ExtractedDocument:
    """Extract headings, text blocks, and table rows while dropping page chrome/forms."""
    soup = BeautifulSoup(payload, "html.parser")
    title = _clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    document_date = _html_document_date(soup)

    for element in soup.select(
        "script, style, noscript, nav, header, footer, aside, form, input, select, textarea"
    ):
        element.decompose()
    for element in soup.select('[role="navigation"], [aria-hidden="true"]'):
        element.decompose()

    content = soup.find("main") or soup.find(id="content") or soup.find("article") or soup.body or soup
    faq_blocks: dict[int, ContentBlock] = {}
    faq_roots: dict[int, Tag] = {}
    for button in content.find_all("button"):
        question = _clean_text(button.get_text(" ", strip=True))
        question = re.sub(r"^\d+[.)]\s*", "", question)
        faq_item = button.find_parent("li")
        answer_panel = button.find_next_sibling()
        if not question.endswith("?") or not faq_item or not isinstance(answer_panel, Tag):
            continue
        answer = _clean_text(answer_panel.get_text(" ", strip=True))
        if not answer or _sensitive_workflow_text(answer):
            continue
        faq_blocks[id(faq_item)] = ContentBlock(
            kind="faq", text=answer, question=question
        )
        faq_roots[id(faq_item)] = faq_item

    for button in soup.find_all("button"):
        button.decompose()

    fact_blocks: dict[int, ContentBlock] = {}
    fact_value_ids: set[int] = set()
    for label_node in content.find_all(["p", "div", "dt"]):
        if label_node.name == "div" and _class_has_suffix(label_node, "exitload"):
            label = "Exit Load"
            value = _clean_text(label_node.get_text(" ", strip=True))
            value = re.sub(r"^Exit Load\s*", "", value, flags=re.IGNORECASE)
            if value and not _sensitive_workflow_text(value):
                fact_blocks[id(label_node)] = ContentBlock(
                    kind="fact", text=f"{label}: {value}", label=label, value=value
                )
                fact_value_ids.update(
                    id(descendant)
                    for descendant in label_node.find_all(["p", "li", "dt", "dd"])
                )
            continue
        if label_node.name == "dt":
            value_node = label_node.find_next_sibling("dd")
        elif _class_has_suffix(label_node, "title"):
            value_node = next(
                (
                    sibling
                    for sibling in label_node.next_siblings
                    if isinstance(sibling, Tag)
                    and _class_has_suffix(sibling, "description")
                ),
                None,
            )
        else:
            continue
        if not isinstance(value_node, Tag):
            continue

        if label_node.name == "div":
            label = _clean_text(
                " ".join(str(text) for text in label_node.find_all(string=True, recursive=False))
            )
        else:
            label = _clean_text(label_node.get_text(" ", strip=True))
        value = _clean_text(value_node.get_text(" ", strip=True))
        if not label or not value or _sensitive_workflow_text(f"{label} {value}"):
            continue
        fact_blocks[id(label_node)] = ContentBlock(
            kind="fact", text=f"{label}: {value}", label=label, value=value
        )
        fact_value_ids.add(id(value_node))

    sections: list[ContentSection] = []
    heading_stack: list[tuple[int, str]] = []
    current_section: ContentSection | None = None
    seen_blocks: set[tuple[Any, ...]] = set()

    def add_block(block: ContentBlock) -> None:
        nonlocal current_section
        if current_section is None:
            current_section = ContentSection(section_path=[title] if title else [])
            sections.append(current_section)
        key = (
            tuple(current_section.section_path),
            block.text,
            block.question,
            block.label,
            block.value,
            tuple(tuple(row) for row in block.rows),
        )
        if key not in seen_blocks:
            current_section.blocks.append(block)
            seen_blocks.add(key)

    block_names = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table", "dt", "dd", "div"}
    for element in content.find_all(
        lambda candidate: candidate.name in block_names or candidate.get("role") == "heading"
    ):
        if any(id(parent) in faq_roots for parent in element.parents):
            continue
        if element.name == "div":
            fact = fact_blocks.get(id(element))
            if not fact or (fact.label or "").casefold() not in {
                "ter",
                "riskometer",
                "exit load",
            }:
                continue
        if id(element) in faq_roots:
            add_block(faq_blocks[id(element)])
            continue
        if element.name == "li" and element.find_parent("li"):
            continue
        if element.name == "table" and element.find_parent("table"):
            continue
        is_heading = element.name in {"h1", "h2", "h3", "h4", "h5", "h6"} or element.get("role") == "heading"
        if is_heading:
            heading_level = (
                int(element.name[1])
                if element.name in {"h1", "h2", "h3", "h4", "h5", "h6"}
                else int(element.get("aria-level") or 2)
            )
            heading_text = _clean_text(element.get_text(" ", strip=True))
            if not heading_text:
                continue
            while heading_stack and heading_stack[-1][0] >= heading_level:
                heading_stack.pop()
            heading_stack.append((heading_level, heading_text))
            current_section = ContentSection(section_path=[text for _, text in heading_stack])
            sections.append(current_section)
            continue

        if id(element) in fact_blocks:
            add_block(fact_blocks[id(element)])
            continue
        if id(element) in fact_value_ids:
            continue

        if element.name == "dt":
            continue

        if element.name == "table":
            rows = _table_rows(element)
            if rows:
                caption = element.find("caption", recursive=False)
                add_block(
                    ContentBlock(
                        kind="table",
                        rows=rows,
                        title=_clean_text(caption.get_text(" ", strip=True)) if caption else None,
                    )
                )
        else:
            text = _clean_text(element.get_text(" ", strip=True))
            if text and not _sensitive_workflow_text(text):
                kind = "list_item" if element.name in {"li", "dd"} else "paragraph"
                add_block(ContentBlock(kind=kind, text=text))

    return ExtractedDocument(
        source_url=source_url,
        title=title,
        document_date=document_date,
        sections=[section for section in sections if section.blocks],
    )


def _pdf_table_title(page: Any, table: Any) -> str | None:
    bounds = getattr(table, "bbox", None)
    if not bounds or len(bounds) != 4:
        return None
    try:
        preceding_page = page.crop((0, 0, page.width, float(bounds[1])))
        text = preceding_page.extract_text() or ""
    except (AttributeError, TypeError, ValueError):
        return None
    preceding_lines = [_clean_text(line) for line in text.splitlines() if _clean_text(line)]
    if not preceding_lines:
        return None
    title = preceding_lines[-1]
    return title if len(title) <= 160 else None


def extract_pdf(payload: bytes, source_url: str) -> ExtractedDocument:
    """Extract per-page text and table cells using pdfplumber's layout-aware API."""
    import pdfplumber

    sections: list[ContentSection] = []
    warnings: list[str] = []
    with pdfplumber.open(BytesIO(payload)) as pdf:
        title = _clean_text(str(pdf.metadata.get("Title") or ""))
        original_page_texts = [
            (page.extract_text(layout=True) or page.extract_text() or "").strip()
            for page in pdf.pages
        ]
        document_date = _pdf_document_date(original_page_texts)
        for page_number, page in enumerate(pdf.pages, start=1):
            blocks: list[ContentBlock] = []
            table_blocks: list[ContentBlock] = []
            table_bounds: list[tuple[float, float, float, float]] = []
            find_tables = getattr(page, "find_tables", None)
            try:
                table_objects = find_tables() if callable(find_tables) else []
            except Exception as error:
                warnings.append(
                    f"Page {page_number}: table detection failed ({type(error).__name__})"
                )
                table_objects = []

            if table_objects:
                for table_index, table_object in enumerate(table_objects, start=1):
                    try:
                        rows = [
                            [_clean_text(cell or "") for cell in row]
                            for row in table_object.extract()
                            if row and any(cell and str(cell).strip() for cell in row)
                        ]
                    except Exception as error:
                        warnings.append(
                            f"Page {page_number}: skipped unreadable table {table_index} "
                            f"({type(error).__name__})"
                        )
                        continue
                    if not rows:
                        continue
                    widths = {len(row) for row in rows}
                    if len(widths) > 1:
                        warnings.append(
                            f"Page {page_number}: skipped table {table_index} with inconsistent row widths"
                        )
                        continue
                    bounds = getattr(table_object, "bbox", None)
                    if bounds and len(bounds) == 4:
                        table_bounds.append(tuple(float(value) for value in bounds))
                    table_blocks.append(
                        ContentBlock(
                            kind="table",
                            rows=rows,
                            page_number=page_number,
                            title=_pdf_table_title(page, table_object),
                        )
                    )
            else:
                for table_index, table in enumerate(page.extract_tables() or [], start=1):
                    rows = [
                        [_clean_text(cell or "") for cell in row]
                        for row in table
                        if row and any(cell and str(cell).strip() for cell in row)
                    ]
                    if rows:
                        widths = {len(row) for row in rows}
                        if len(widths) > 1:
                            warnings.append(
                                f"Page {page_number}: skipped table {table_index} with inconsistent row widths"
                            )
                            continue
                        table_blocks.append(
                            ContentBlock(kind="table", rows=rows, page_number=page_number)
                        )

            text = original_page_texts[page_number - 1]
            if table_bounds and callable(getattr(page, "filter", None)):
                try:
                    filtered_page = page.filter(
                        lambda character: character.get("object_type") != "char"
                        or not any(
                            left <= (character["x0"] + character["x1"]) / 2 <= right
                            and top <= (character["top"] + character["bottom"]) / 2 <= bottom
                            for left, top, right, bottom in table_bounds
                        )
                    )
                    text = (filtered_page.extract_text(layout=True) or filtered_page.extract_text() or "").strip()
                except (KeyError, TypeError, ValueError, AttributeError):
                    warnings.append(f"Page {page_number}: could not remove table regions from page text")

            if text:
                blocks.append(
                    ContentBlock(kind="page_text", text=text, page_number=page_number)
                )
            blocks.extend(table_blocks)
            if blocks:
                sections.append(
                    ContentSection(section_path=[f"Page {page_number}"], blocks=blocks)
                )

        return ExtractedDocument(
            source_url=source_url,
            title=title,
            document_date=document_date,
            sections=sections,
            page_count=len(pdf.pages),
            warnings=warnings,
        )


def extract_document(payload: bytes, source_url: str, content_type: str) -> ExtractedDocument:
    """Choose an extractor from the file signature, rejecting unsupported content."""
    if payload.startswith(b"%PDF-"):
        return extract_pdf(payload, source_url)
    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_type in {"text/html", "application/xhtml+xml"}:
        return extract_html(payload, source_url)
    raise ValueError(f"Unsupported source content type: {content_type or '(missing)'}")