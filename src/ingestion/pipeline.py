"""Run Phase 1 source fetching and extraction, recording per-source outcomes."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from ingestion.extract import extract_document
from ingestion.fetch import SourceFetchError, fetch_source
from ingestion.manifest import SourceRecord, load_source_manifest


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary_path, path)


def _source_status(source: SourceRecord, status: str, attempted_at: str) -> dict[str, Any]:
    return {
        **source.as_dict(),
        "canonical_url": source.url,
        "status": status,
        "fetched_at": attempted_at,
    }


def ingest_sources(
    manifest_path: str | Path,
    output_dir: str | Path,
    timeout_seconds: float = 20,
    max_bytes: int = 30 * 1024 * 1024,
) -> list[dict[str, Any]]:
    """Fetch and extract each source, continuing after per-source errors."""
    sources = load_source_manifest(manifest_path)
    root = Path(output_dir)
    snapshots_dir = root / "sources"
    extracted_dir = root / "extracted"
    results: list[dict[str, Any]] = []

    for source in sources:
        attempted_at = datetime.now(timezone.utc).isoformat()
        try:
            fetched = fetch_source(source, timeout_seconds, max_bytes)
        except SourceFetchError as error:
            result = _source_status(source, "fetch_failed", attempted_at)
            result["http_status"] = error.status_code
            result["error"] = str(error)
            results.append(result)
            continue

        extension = "pdf" if fetched.content_type == "application/pdf" else "html"
        snapshot_path = snapshots_dir / f"source-{source.source_id}.{extension}"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_bytes(fetched.content)

        try:
            document = extract_document(fetched.content, source.url, fetched.content_type)
        except Exception as error:
            result = _source_status(source, "parse_failed", fetched.fetched_at)
            result.update(
                {
                    "content_type": fetched.content_type,
                    "content_sha256": fetched.content_sha256,
                    "snapshot_path": str(snapshot_path),
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            results.append(result)
            continue

        extracted_path = extracted_dir / f"source-{source.source_id}.json"
        _write_json(extracted_path, document.as_dict())
        result = _source_status(source, "ok", fetched.fetched_at)
        result.update(
            {
                "content_type": fetched.content_type,
                "content_sha256": fetched.content_sha256,
                "snapshot_path": str(snapshot_path),
                "extracted_path": str(extracted_path),
                "title": document.title,
                "document_date": document.document_date,
                "page_count": document.page_count,
                "extraction_warnings": document.warnings,
            }
        )
        results.append(result)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_manifest": str(Path(manifest_path)),
        "sources": results,
        "summary": {
            "total": len(results),
            "ok": sum(result["status"] == "ok" for result in results),
            "fetch_failed": sum(result["status"] == "fetch_failed" for result in results),
            "parse_failed": sum(result["status"] == "parse_failed" for result in results),
        },
    }
    _write_json(root / "manifest.json", manifest)
    return results