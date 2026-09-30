"""Persistent Chroma storage for the validated Phase 2A chunk artifact."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any

from embeddings import EMBEDDING_DIMENSION, MODEL_NAME, EmbeddingModel
from ingestion.manifest import is_approved_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COLLECTION_NAME = "hdfc_faq_chunks"
_BLOCK_MARKER = "=" * 80
_BODY_MARKER = "-" * 80
_REQUIRED_METADATA = (
    "chunk_id",
    "source_id",
    "source_url",
    "source_title",
    "source_type",
    "publisher",
    "scheme_or_scope",
    "section_path",
    "fetched_at",
    "content_hash",
    "chunk_index",
)


class ChunkArtifactError(ValueError):
    """Raised when the Phase 2A chunk dump is incomplete or malformed."""


@dataclass(frozen=True)
class StoredChunk:
    chunk_id: str
    text: str
    metadata: dict[str, str | int]


@dataclass(frozen=True)
class IndexResult:
    indexed_count: int
    added_count: int
    metadata_updated_count: int
    removed_count: int
    embedding_dimension: int


def load_chunk_artifact(path: str | Path) -> list[StoredChunk]:
    """Read Phase 2A's human-readable artifact without changing its chunking."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    chunks: list[StoredChunk] = []
    position = 0
    expected_count: int | None = None
    seen_ids: set[str] = set()

    while position < len(lines):
        if not lines[position].strip():
            position += 1
            continue
        if lines[position] != _BLOCK_MARKER:
            raise ChunkArtifactError(f"Unexpected content at line {position + 1}")
        position += 1
        if position >= len(lines):
            raise ChunkArtifactError("Chunk header is incomplete")
        match = re.fullmatch(r"CHUNK (\d+) of (\d+)", lines[position])
        if not match:
            raise ChunkArtifactError(f"Invalid chunk header at line {position + 1}")
        chunk_number, declared_count = map(int, match.groups())
        if expected_count is None:
            expected_count = declared_count
        elif expected_count != declared_count:
            raise ChunkArtifactError("Chunk headers disagree on total chunk count")
        if chunk_number != len(chunks) + 1:
            raise ChunkArtifactError("Chunk numbers are missing or out of order")
        position += 1

        metadata: dict[str, str | int] = {}
        while position < len(lines) and lines[position] != _BODY_MARKER:
            if ": " not in lines[position]:
                raise ChunkArtifactError(f"Invalid metadata at line {position + 1}")
            key, value = lines[position].split(": ", 1)
            if not key or key in metadata:
                raise ChunkArtifactError(f"Duplicate or empty metadata key: {key!r}")
            metadata[key] = value
            position += 1
        if position >= len(lines):
            raise ChunkArtifactError("Chunk body marker is missing")
        position += 1

        body_lines: list[str] = []
        while position < len(lines) and lines[position] != _BLOCK_MARKER:
            body_lines.append(lines[position])
            position += 1
        text = "\n".join(body_lines).strip()
        missing = [key for key in _REQUIRED_METADATA if not metadata.get(key)]
        if missing:
            raise ChunkArtifactError(
                f"Chunk {chunk_number} is missing metadata: {', '.join(missing)}"
            )
        if not text:
            raise ChunkArtifactError(f"Chunk {chunk_number} has no text")
        if not is_approved_url(str(metadata["source_url"])):
            raise ChunkArtifactError(
                f"Chunk {chunk_number} has an unapproved source URL"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", str(metadata["content_hash"])):
            raise ChunkArtifactError(f"Chunk {chunk_number} has an invalid content hash")
        for field in ("chunk_index", "page_number", "token_count"):
            if field in metadata:
                try:
                    metadata[field] = int(metadata[field])
                except ValueError as error:
                    raise ChunkArtifactError(
                        f"Chunk {chunk_number} has an invalid {field}"
                    ) from error
        if int(metadata["chunk_index"]) < 0:
            raise ChunkArtifactError(f"Chunk {chunk_number} has a negative chunk index")
        if "page_number" in metadata and int(metadata["page_number"]) < 1:
            raise ChunkArtifactError(f"Chunk {chunk_number} has an invalid page number")
        chunk_id = str(metadata["chunk_id"])
        if chunk_id in seen_ids:
            raise ChunkArtifactError(f"Duplicate chunk ID: {chunk_id}")
        seen_ids.add(chunk_id)
        chunks.append(StoredChunk(chunk_id=chunk_id, text=text, metadata=metadata))

    if not chunks:
        raise ChunkArtifactError("Chunk artifact contains no chunks")
    if expected_count != len(chunks):
        raise ChunkArtifactError(
            f"Artifact declares {expected_count} chunks but contains {len(chunks)}"
        )
    return chunks


def _get_collection(client: Any, collection_name: str) -> Any:
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"embedding_model": MODEL_NAME, "hnsw:space": "cosine"},
        embedding_function=None,
    )
    collection_metadata = collection.metadata or {}
    stored_model = collection_metadata.get("embedding_model")
    if stored_model != MODEL_NAME:
        raise ValueError(
            f"Collection uses embedding model {stored_model!r}, expected {MODEL_NAME!r}"
        )
    return collection


def index_chunks(
    artifact_path: str | Path,
    persist_directory: str | Path,
    embedder: Any | None = None,
    client: Any | None = None,
    collection_name: str = COLLECTION_NAME,
) -> IndexResult:
    """Synchronize artifact chunks into a persistent Chroma collection."""
    try:
        import chromadb
    except ImportError as error:
        raise RuntimeError("Install chromadb to persist the vector collection") from error

    chunks = load_chunk_artifact(artifact_path)
    if client is None:
        persist_path = Path(persist_directory)
        persist_path.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(persist_path))
    if embedder is None:
        embedder = EmbeddingModel()
    collection = _get_collection(client, collection_name)

    existing = collection.get(include=["documents", "metadatas"])
    existing_documents = dict(zip(existing["ids"], existing["documents"] or []))
    existing_metadata = dict(zip(existing["ids"], existing["metadatas"] or []))
    desired_ids = {chunk.chunk_id for chunk in chunks}
    stale_ids = [chunk_id for chunk_id in existing["ids"] if chunk_id not in desired_ids]
    if stale_ids:
        collection.delete(ids=stale_ids)

    new_chunks: list[StoredChunk] = []
    metadata_updates: list[StoredChunk] = []
    for chunk in chunks:
        if chunk.chunk_id not in existing_documents:
            new_chunks.append(chunk)
        elif existing_documents[chunk.chunk_id] != chunk.text:
            collection.delete(ids=[chunk.chunk_id])
            new_chunks.append(chunk)
        elif existing_metadata.get(chunk.chunk_id) != chunk.metadata:
            metadata_updates.append(chunk)

    if metadata_updates:
        collection.update(
            ids=[chunk.chunk_id for chunk in metadata_updates],
            metadatas=[chunk.metadata for chunk in metadata_updates],
        )
    if new_chunks:
        vectors = embedder.embed_documents([chunk.text for chunk in new_chunks])
        if len(vectors) != len(new_chunks) or any(
            len(vector) != EMBEDDING_DIMENSION for vector in vectors
        ):
            raise ValueError(
                f"Expected {EMBEDDING_DIMENSION}-dimensional vectors for every new chunk"
            )
        collection.add(
            ids=[chunk.chunk_id for chunk in new_chunks],
            documents=[chunk.text for chunk in new_chunks],
            metadatas=[chunk.metadata for chunk in new_chunks],
            embeddings=vectors,
        )

    return IndexResult(
        indexed_count=collection.count(),
        added_count=len(new_chunks),
        metadata_updated_count=len(metadata_updates),
        removed_count=len(stale_ids),
        embedding_dimension=EMBEDDING_DIMENSION,
    )


def retrieve_similar(
    query: str,
    persist_directory: str | Path,
    n_results: int = 3,
    embedder: Any | None = None,
    client: Any | None = None,
    collection_name: str = COLLECTION_NAME,
) -> list[dict[str, Any]]:
    """Retrieve nearest chunks, embedding the query with the indexing model."""
    if n_results < 1:
        raise ValueError("n_results must be at least one")
    try:
        import chromadb
    except ImportError as error:
        raise RuntimeError("Install chromadb to retrieve indexed chunks") from error
    if client is None:
        client = chromadb.PersistentClient(path=str(persist_directory))
    collection = _get_collection(client, collection_name)
    if embedder is None:
        embedder = EmbeddingModel()
    vector = embedder.embed_query(query)
    if len(vector) != EMBEDDING_DIMENSION:
        raise ValueError(
            f"Expected a {EMBEDDING_DIMENSION}-dimensional query embedding"
        )
    result = collection.query(
        query_embeddings=[vector],
        n_results=min(n_results, collection.count()),
        include=["documents", "metadatas", "distances"],
    )
    return [
        {
            "chunk_id": chunk_id,
            "text": text,
            "metadata": metadata,
            "distance": distance,
        }
        for chunk_id, text, metadata, distance in zip(
            result["ids"][0],
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        )
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Embed Phase 2A chunks and persist them in ChromaDB."
    )
    parser.add_argument(
        "--chunks",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "chunks.txt",
    )
    parser.add_argument(
        "--persist-directory", type=Path, default=PROJECT_ROOT / "data" / "chroma"
    )
    args = parser.parse_args()

    result = index_chunks(args.chunks, args.persist_directory)
    print(
        f"Indexed {result.indexed_count} chunks in {args.persist_directory}; "
        f"added {result.added_count}, refreshed metadata for "
        f"{result.metadata_updated_count}, removed {result.removed_count}; "
        f"embedding dimension {result.embedding_dimension}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())