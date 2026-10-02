"""Create structure-aware, tokenizer-bounded chunks from extracted sources."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MAX_TOKENS = 220
PROSE_OVERLAP = 40
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=\S)")
_PERFORMANCE_CONTEXT = re.compile(
    r"\b(?:performance|(?:scheme|benchmark|fund)\s+returns?|value of investment)\b",
    re.IGNORECASE,
)
_RETURNS_LABEL = re.compile(r"^(?:scheme\s+)?returns?\s*:?$", re.IGNORECASE)
_RETURN_VALUE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)\s*%$")
_SIP_MINIMUM_LABEL = re.compile(r"^min(?:imum)?\s+sip$", re.IGNORECASE)
_SIP_MINIMUM_VALUE = re.compile(
    r"^(?:\u20b9\s*|INR\s*|Rs\.?\s*)?\d[\d,]*(?:\.\d+)?(?:\s*/-)?$",
    re.IGNORECASE,
)


class ChunkingError(ValueError):
    """Raised when source data cannot be chunked without losing structure."""


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    text: str
    metadata: dict[str, str | int]


def load_tokenizer() -> Any:
    """Load the tokenizer paired with the required embedding model."""
    try:
        from transformers import AutoTokenizer
    except ImportError as error:
        raise RuntimeError(
            "Install the requirements to load the all-MiniLM-L6-v2 tokenizer"
        ) from error

    return AutoTokenizer.from_pretrained(MODEL_NAME, use_fast=True)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _with_scheme_context(text: str, scheme_or_scope: str) -> str:
    if scheme_or_scope.casefold() in text.casefold():
        return text
    return f"{scheme_or_scope} - {text}"


def _encode(tokenizer: Any, text: str) -> list[int]:
    tokenize = getattr(tokenizer, "tokenize", None)
    convert_tokens_to_ids = getattr(tokenizer, "convert_tokens_to_ids", None)
    if callable(tokenize) and callable(convert_tokens_to_ids):
        return list(convert_tokens_to_ids(tokenize(text)))
    return list(tokenizer.encode(text, add_special_tokens=False))


def _decode(tokenizer: Any, token_ids: list[int]) -> str:
    return tokenizer.decode(
        token_ids,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    ).strip()


def _token_count(tokenizer: Any, text: str) -> int:
    return len(_encode(tokenizer, text))


def _token_windows(
    text: str,
    tokenizer: Any,
    max_tokens: int,
    overlap_tokens: int,
    prefix: str = "",
) -> list[str]:
    token_ids = _encode(tokenizer, text)
    if not token_ids:
        return []

    available_tokens = max_tokens - _token_count(tokenizer, prefix)
    if available_tokens <= 0 or overlap_tokens >= available_tokens:
        raise ChunkingError("Chunk context leaves no room for source text")

    chunks: list[str] = []
    start = 0
    while start < len(token_ids):
        end = min(start + available_tokens, len(token_ids))
        while end > start:
            body = _decode(tokenizer, token_ids[start:end])
            candidate = f"{prefix}{body}"
            if body and _token_count(tokenizer, candidate) <= max_tokens:
                break
            end -= 1
        if end <= start:
            raise ChunkingError("Tokenizer could not produce a non-empty bounded chunk")

        chunks.append(candidate)
        if end == len(token_ids):
            break
        start = end - overlap_tokens

    return chunks


def _split_prose(
    text: str,
    tokenizer: Any,
    max_tokens: int,
    overlap_tokens: int,
    prefix: str = "",
) -> list[str]:
    text = _normalize_text(text)
    if not text:
        return []
    if _token_count(tokenizer, f"{prefix}{text}") <= max_tokens:
        return [f"{prefix}{text}"]

    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]
    if not sentences:
        return _token_windows(text, tokenizer, max_tokens, overlap_tokens, prefix)

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if _token_count(tokenizer, f"{prefix}{candidate}") <= max_tokens:
            current = candidate
            continue

        if current:
            previous_chunk = f"{prefix}{current}"
            chunks.append(previous_chunk)
            if overlap_tokens:
                previous_ids = _encode(tokenizer, current)
                overlap_text = _decode(tokenizer, previous_ids[-overlap_tokens:])
                overlapped = f"{overlap_text} {sentence}".strip()
                if _token_count(tokenizer, f"{prefix}{overlapped}") <= max_tokens:
                    current = overlapped
                    continue
            current = ""

        if _token_count(tokenizer, f"{prefix}{sentence}") > max_tokens:
            chunks.extend(
                _token_windows(
                    sentence,
                    tokenizer,
                    max_tokens,
                    overlap_tokens,
                    prefix,
                )
            )
        else:
            current = sentence

    if current:
        chunks.append(f"{prefix}{current}")
    return chunks


def _document_content_hash(document: dict[str, Any]) -> str:
    normalized_sections = []
    for section in document.get("sections", []):
        normalized_blocks = []
        for block in section.get("blocks", []):
            normalized_blocks.append(
                {
                    "kind": block.get("kind", ""),
                    "text": _normalize_text(block.get("text") or ""),
                    "question": _normalize_text(block.get("question") or ""),
                    "label": _normalize_text(block.get("label") or ""),
                    "value": _normalize_text(block.get("value") or ""),
                    "title": _normalize_text(block.get("title") or ""),
                    "rows": [
                        [_normalize_text(cell or "") for cell in row]
                        for row in block.get("rows", [])
                    ],
                    "page_number": block.get("page_number"),
                }
            )
        normalized_sections.append(
            {
                "section_path": [
                    _normalize_text(part) for part in section.get("section_path", [])
                ],
                "blocks": normalized_blocks,
            }
        )
    serialized = json.dumps(
        normalized_sections,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _table_chunks(
    block: dict[str, Any],
    tokenizer: Any,
    max_tokens: int,
) -> list[str]:
    rows = [
        [_normalize_text(cell or "") for cell in row]
        for row in block.get("rows", [])
        if any(_normalize_text(cell or "") for cell in row)
    ]
    if not rows:
        return []

    title = _normalize_text(block.get("title") or "")
    first_row_headers = (
        len(rows) > 1
        and len(rows[0]) > 1
        and sum(bool(cell) for cell in rows[0]) > 1
        and all(
            not cell or _token_count(tokenizer, cell) <= 12
            for cell in rows[0]
        )
    )
    header_count = 1 if first_row_headers else 0
    if (
        len(rows) > 2
        and header_count == 1
        and len(rows[1]) == len(rows[0])
        and not rows[1][0]
        and any(rows[1][1:])
    ):
        header_count = 2

    context_lines = []
    if title:
        context_lines.append(f"Table: {title}")
    if header_count:
        headers = [" | ".join(row) for row in rows[:header_count]]
        context_lines.append("Column headings: " + " / ".join(headers))
    context_lines.append("Rows:")
    prefix = "\n".join(context_lines) + "\n"
    if _token_count(tokenizer, prefix) > max_tokens:
        raise ChunkingError("Table title and column headings exceed the chunk limit")

    data_rows = rows[header_count:]
    if not data_rows:
        return [prefix.rstrip()]

    chunks: list[str] = []
    current_rows: list[str] = []
    for row in data_rows:
        row_text = " | ".join(row)
        candidate_rows = current_rows + [row_text]
        candidate = prefix + "\n".join(candidate_rows)
        if _token_count(tokenizer, candidate) <= max_tokens:
            current_rows = candidate_rows
            continue
        if current_rows:
            chunks.append(prefix + "\n".join(current_rows))
            current_rows = []
            candidate = prefix + row_text
        if _token_count(tokenizer, candidate) > max_tokens:
            raise ChunkingError("A complete table row exceeds the chunk limit")
        current_rows = [row_text]

    if current_rows:
        chunks.append(prefix + "\n".join(current_rows))
    return chunks


def _is_performance_table(block: dict[str, Any]) -> bool:
    searchable = " ".join(
        [
            _normalize_text(block.get("title") or ""),
            *(
                _normalize_text(cell or "")
                for row in block.get("rows", [])
                for cell in row
            ),
        ]
    )
    return bool(_PERFORMANCE_CONTEXT.search(searchable))


def chunk_documents(
    manifest_path: str | Path,
    extracted_dir: str | Path,
    tokenizer: Any | None = None,
    max_tokens: int = MAX_TOKENS,
    overlap_tokens: int = PROSE_OVERLAP,
) -> list[TextChunk]:
    """Chunk every successful extracted source, preserving citation metadata."""
    if max_tokens <= 0 or overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError("Token limit must be positive and overlap smaller than the limit")
    if tokenizer is None:
        tokenizer = load_tokenizer()

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ChunkingError("Ingestion manifest contains no source records")
    failed = [
        str(source.get("source_id", "?"))
        for source in sources
        if source.get("status") != "ok"
    ]
    if failed:
        raise ChunkingError(
            "Cannot chunk sources that did not ingest successfully: " + ", ".join(failed)
        )

    extraction_root = Path(extracted_dir)
    chunks: list[TextChunk] = []
    for source in sources:
        source_id = str(source.get("source_id", ""))
        document_path = extraction_root / f"source-{source_id}.json"
        if not document_path.is_file():
            raise ChunkingError(f"Missing extracted source file: {document_path}")
        document = json.loads(document_path.read_text(encoding="utf-8"))
        source_url = source.get("canonical_url") or source.get("url")
        if not source_url or document.get("source_url") != source_url:
            raise ChunkingError(f"Source URL mismatch for source {source_id}")

        source_fields = (
            "source_type",
            "publisher",
            "scheme_or_scope",
            "fetched_at",
        )
        if any(not source.get(field) for field in source_fields):
            raise ChunkingError(f"Source {source_id} is missing required manifest metadata")

        source_title = _normalize_text(document.get("title") or "") or (
            f"{source['scheme_or_scope']} - {source['source_type']}"
        )
        document_date = document.get("document_date") or source.get("document_date")
        content_hash = _document_content_hash(document)
        source_chunk_index = 0

        def append_chunk(text: str, section_path: list[str], page_number: int | None) -> None:
            nonlocal source_chunk_index
            token_count = _token_count(tokenizer, text)
            if token_count > max_tokens:
                raise ChunkingError(
                    f"Source {source_id} produced a {token_count}-token chunk"
                )
            chunk_signature = "\0".join(
                (source_id, content_hash, str(source_chunk_index), text)
            )
            chunk_id = f"source-{source_id}-{hashlib.sha256(chunk_signature.encode('utf-8')).hexdigest()[:16]}"
            metadata: dict[str, str | int] = {
                "chunk_id": chunk_id,
                "source_id": source_id,
                "source_url": source_url,
                "source_title": source_title,
                "source_type": str(source["source_type"]),
                "publisher": str(source["publisher"]),
                "scheme_or_scope": str(source["scheme_or_scope"]),
                "section_path": " > ".join(section_path),
                "fetched_at": str(source["fetched_at"]),
                "content_hash": content_hash,
                "chunk_index": source_chunk_index,
                "token_count": token_count,
            }
            if page_number is not None:
                metadata["page_number"] = int(page_number)
            if document_date:
                metadata["document_date"] = str(document_date)
            chunks.append(TextChunk(chunk_id=chunk_id, text=text, metadata=metadata))
            source_chunk_index += 1

        for section in document.get("sections", []):
            base_path = [
                _normalize_text(part)
                for part in section.get("section_path", [])
                if _normalize_text(part)
            ]
            if any(_PERFORMANCE_CONTEXT.search(part) for part in base_path):
                continue
            prose: list[str] = []
            prose_page: int | None = None
            pending_return_value = False
            first_content_block = True

            def flush_prose() -> None:
                nonlocal prose, prose_page
                if not prose:
                    return
                text = "\n\n".join(prose)
                for part in _split_prose(
                    text, tokenizer, max_tokens, overlap_tokens
                ):
                    append_chunk(part, base_path, prose_page)
                prose = []
                prose_page = None

            blocks = section.get("blocks", [])
            consumed_fact_values: set[int] = set()
            for block_index, block in enumerate(blocks):
                if block_index in consumed_fact_values:
                    continue
                kind = block.get("kind", "paragraph")
                page_number = block.get("page_number")
                text = _normalize_text(block.get("text") or "")

                is_scheme_root = base_path == [str(source["scheme_or_scope"])]
                if (
                    first_content_block
                    and is_scheme_root
                    and kind == "paragraph"
                    and text.casefold() in {"equity", "hybrid"}
                ):
                    flush_prose()
                    category_text = (
                        f"Scheme: {source['scheme_or_scope']}\n"
                        f"Scheme category: {text}"
                    )
                    append_chunk(category_text, base_path, page_number)
                    first_content_block = False
                    continue

                if text or block.get("rows"):
                    first_content_block = False

                if (
                    source["source_type"] == "Consolidated Account Statement"
                    and base_path == ["Download Statement"]
                    and kind == "paragraph"
                    and text.casefold() == "or"
                ):
                    continue

                label = _normalize_text(block.get("label") or "")
                if kind == "fact" and _RETURNS_LABEL.fullmatch(label or text):
                    flush_prose()
                    pending_return_value = True
                    continue
                if pending_return_value:
                    pending_return_value = False
                    if _RETURN_VALUE.fullmatch(text):
                        flush_prose()
                        continue
                if kind == "table" and _is_performance_table(block):
                    flush_prose()
                    continue
                if _PERFORMANCE_CONTEXT.search(text):
                    flush_prose()
                    continue
                if kind in {"paragraph", "list_item", "page_text"} and _RETURNS_LABEL.fullmatch(text):
                    flush_prose()
                    pending_return_value = True
                    continue

                if (
                    kind in {"paragraph", "list_item", "page_text"}
                    and _SIP_MINIMUM_LABEL.fullmatch(text)
                    and block_index + 1 < len(blocks)
                ):
                    value_block = blocks[block_index + 1]
                    value_text = _normalize_text(value_block.get("text") or "")
                    if (
                        value_block.get("kind", "paragraph")
                        in {"paragraph", "list_item", "page_text"}
                        and _SIP_MINIMUM_VALUE.fullmatch(value_text)
                    ):
                        flush_prose()
                        fact_text = _with_scheme_context(
                            f"{text}: {value_text}", str(source["scheme_or_scope"])
                        )
                        append_chunk(fact_text, base_path, page_number)
                        consumed_fact_values.add(block_index + 1)
                        continue

                if kind in {"paragraph", "list_item", "page_text"} or (
                    kind not in {"fact", "faq", "table"} and text
                ):
                    if not text:
                        continue
                    if prose and prose_page != page_number:
                        flush_prose()
                    prose_page = page_number
                    prose.append(text)
                    continue

                flush_prose()
                if kind == "fact":
                    fact_text = text or ": ".join(
                        part
                        for part in (
                            _normalize_text(block.get("label") or ""),
                            _normalize_text(block.get("value") or ""),
                        )
                        if part
                    )
                    if fact_text:
                        fact_text = _with_scheme_context(
                            fact_text, str(source["scheme_or_scope"])
                        )
                        if _token_count(tokenizer, fact_text) > max_tokens:
                            raise ChunkingError(
                                f"Fact in source {source_id} exceeds the chunk limit"
                            )
                        append_chunk(fact_text, base_path, page_number)
                elif kind == "faq":
                    question = _normalize_text(block.get("question") or "")
                    if not question:
                        raise ChunkingError(f"FAQ in source {source_id} has no question")
                    prefix = f"Question: {question}\nAnswer: "
                    faq_path = [*base_path, question]
                    for part in _split_prose(
                        text,
                        tokenizer,
                        max_tokens,
                        overlap_tokens=0,
                        prefix=prefix,
                    ):
                        append_chunk(part, faq_path, page_number)
                elif kind == "table":
                    table_title = _normalize_text(block.get("title") or "")
                    table_path = [*base_path, table_title] if table_title else base_path
                    for part in _table_chunks(block, tokenizer, max_tokens):
                        append_chunk(part, table_path, page_number)

            flush_prose()

    return chunks


def write_chunk_dump(chunks: list[TextChunk], output_path: str | Path) -> None:
    """Write a readable text artifact with metadata before each chunk."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for index, chunk in enumerate(chunks, start=1):
            stream.write("=" * 80 + "\n")
            stream.write(f"CHUNK {index} of {len(chunks)}\n")
            for key, value in chunk.metadata.items():
                stream.write(f"{key}: {value}\n")
            stream.write("-" * 80 + "\n")
            stream.write(chunk.text + "\n\n")


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Chunk cleaned Phase 1 source extractions.")
    parser.add_argument("--input-dir", type=Path, default=project_root / "data")
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "data" / "processed" / "chunks.txt",
    )
    args = parser.parse_args()

    chunks = chunk_documents(
        args.input_dir / "manifest.json",
        args.input_dir / "extracted",
    )
    write_chunk_dump(chunks, args.output)
    print(f"Chunking complete: {len(chunks)} chunks written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())