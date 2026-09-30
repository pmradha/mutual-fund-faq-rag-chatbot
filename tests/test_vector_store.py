import hashlib
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from embeddings import EMBEDDING_DIMENSION
from vector_store import index_chunks, load_chunk_artifact, retrieve_similar


class KeywordEmbedder:
    def __init__(self):
        self.calls = []

    def embed_documents(self, texts):
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def embed_query(self, text):
        return self._vector(text)

    @staticmethod
    def _vector(text):
        vector = [0.0] * EMBEDDING_DIMENSION
        lowered = text.lower()
        vector[0 if "expense" in lowered else 1] = 1.0
        return vector


def make_artifact(path: Path, entries):
    blocks = []
    for number, (chunk_id, text, metadata) in enumerate(entries, start=1):
        block = ["=" * 80, f"CHUNK {number} of {len(entries)}"]
        block.extend(f"{key}: {value}" for key, value in metadata.items())
        block.extend(["-" * 80, text, ""])
        blocks.append("\n".join(block))
    path.write_text("\n".join(blocks), encoding="utf-8")


def metadata_for(chunk_id, chunk_index):
    return {
        "chunk_id": chunk_id,
        "source_id": "1",
        "source_url": "https://www.hdfcfund.com/sample",
        "source_title": "Sample Scheme",
        "source_type": "Scheme page",
        "publisher": "HDFC Mutual Fund",
        "scheme_or_scope": "HDFC Large Cap Fund",
        "section_path": "Scheme > Facts",
        "fetched_at": "2026-09-29T08:00:00+00:00",
        "content_hash": hashlib.sha256(b"sample").hexdigest(),
        "chunk_index": chunk_index,
    }


class VectorStoreTests(unittest.TestCase):
    def setUp(self):
        try:
            import chromadb
        except ImportError as error:
            self.fail(f"chromadb dependency is unavailable: {error}")
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.artifact_path = self.root / "chunks.txt"
        self.persist_directory = self.root / "chroma"
        self.entries = [
            (
                "source-1-expense",
                "Expense ratio information for the scheme.",
                metadata_for("source-1-expense", 0),
            ),
            (
                "source-1-exit",
                "Exit load information for the scheme.",
                metadata_for("source-1-exit", 1),
            ),
        ]
        make_artifact(self.artifact_path, self.entries)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_artifact_metadata_embeddings_persistence_and_retrieval(self):
        embedder = KeywordEmbedder()
        result = index_chunks(
            self.artifact_path, self.persist_directory, embedder=embedder
        )

        self.assertEqual(result.indexed_count, len(self.entries))
        self.assertEqual(result.added_count, len(self.entries))
        self.assertEqual(result.embedding_dimension, 384)
        self.assertEqual(len(embedder.calls[0]), len(self.entries))
        loaded = load_chunk_artifact(self.artifact_path)
        self.assertEqual(len(loaded), len(self.entries))
        for chunk in loaded:
            for field in (
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
            ):
                self.assertIn(field, chunk.metadata)

        results = retrieve_similar(
            "What is the expense ratio?",
            self.persist_directory,
            n_results=1,
            embedder=embedder,
        )
        self.assertEqual(results[0]["chunk_id"], "source-1-expense")
        self.assertIn("source_url", results[0]["metadata"])

        import chromadb

        reopened = chromadb.PersistentClient(path=str(self.persist_directory))
        collection = reopened.get_collection("hdfc_faq_chunks", embedding_function=None)
        self.assertEqual(collection.count(), len(self.entries))
        stored = collection.get(include=["embeddings"])
        self.assertEqual(len(stored["embeddings"][0]), EMBEDDING_DIMENSION)

    def test_repeated_indexing_does_not_reembed_existing_chunks(self):
        embedder = KeywordEmbedder()
        first = index_chunks(
            self.artifact_path, self.persist_directory, embedder=embedder
        )
        calls_after_first = len(embedder.calls)
        second = index_chunks(
            self.artifact_path, self.persist_directory, embedder=embedder
        )

        self.assertEqual(first.added_count, 2)
        self.assertEqual(second.indexed_count, 2)
        self.assertEqual(second.added_count, 0)
        self.assertEqual(len(embedder.calls), calls_after_first)


if __name__ == "__main__":
    unittest.main()