"""Relevance-filtered access to the Phase 2B Chroma collection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from embeddings import EmbeddingModel
from ingestion.manifest import is_approved_url
from vector_store import PROJECT_ROOT, retrieve_similar


PERSIST_DIRECTORY = PROJECT_ROOT / "data" / "chroma"
MAX_COSINE_DISTANCE = 0.58


def retrieve_evidence(
    question: str,
    persist_directory: str | Path = PERSIST_DIRECTORY,
    n_results: int = 5,
    embedder: Any | None = None,
) -> list[dict[str, Any]]:
    """Return only nearby chunks with URLs from the approved source inventory."""
    hits = retrieve_similar(
        question,
        persist_directory,
        n_results=n_results,
        embedder=embedder,
    )
    return [
        hit
        for hit in hits
        if float(hit.get("distance", float("inf"))) <= MAX_COSINE_DISTANCE
        and is_approved_url(str(hit.get("metadata", {}).get("source_url", "")))
    ]