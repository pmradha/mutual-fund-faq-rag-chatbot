import json
from pathlib import Path
import re
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ingestion.chunk import ChunkingError, chunk_documents, write_chunk_dump


class WhitespaceTokenizer:
    def encode(self, text, add_special_tokens=False):
        return re.findall(r"\S+", text)

    def decode(self, token_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False):
        return " ".join(token_ids)


class ChunkingTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.extracted_dir = self.root / "extracted"
        self.extracted_dir.mkdir()
        self.manifest_path = self.root / "manifest.json"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_source(self, sections, source_id="1", document_date="2025-11-21"):
        source_url = "https://files.hdfcfund.com/source.pdf"
        document = {
            "source_url": source_url,
            "title": "Sample KIM",
            "document_date": document_date,
            "sections": sections,
        }
        (self.extracted_dir / f"source-{source_id}.json").write_text(
            json.dumps(document), encoding="utf-8"
        )
        manifest = {
            "sources": [
                {
                    "source_id": source_id,
                    "scheme_or_scope": "Sample Fund",
                    "source_type": "KIM",
                    "publisher": "HDFC Mutual Fund",
                    "url": source_url,
                    "canonical_url": source_url,
                    "status": "ok",
                    "fetched_at": "2026-09-29T08:00:00+00:00",
                }
            ]
        }
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_oversized_prose_uses_40_token_overlap_and_stays_within_limit(self):
        sentences = [f"fact{i}." for i in range(55)]
        self.write_source(
            [
                {
                    "section_path": ["Page 1"],
                    "blocks": [
                        {
                            "kind": "page_text",
                            "text": " ".join(sentences),
                            "page_number": 1,
                        }
                    ],
                }
            ]
        )

        chunks = chunk_documents(
            self.manifest_path,
            self.extracted_dir,
            tokenizer=WhitespaceTokenizer(),
            max_tokens=10,
            overlap_tokens=3,
        )

        self.assertGreater(len(chunks), 1)
        token_lists = [chunk.text.split() for chunk in chunks]
        for chunk, tokens in zip(chunks, token_lists):
            self.assertLessEqual(chunk.metadata["token_count"], 10)
            self.assertLessEqual(len(tokens), 10)
        for previous, following in zip(token_lists, token_lists[1:]):
            self.assertEqual(previous[-3:], following[:3])

    def test_facts_faqs_tables_and_metadata_keep_structure(self):
        answer = " ".join(f"answer{i}." for i in range(35))
        rows = [["Company", "Industry"]]
        rows.extend([[f"Company{i}", f"Industry{i}"] for i in range(8)])
        self.write_source(
            [
                {
                    "section_path": ["Page 2", "Scheme facts"],
                    "blocks": [
                        {
                            "kind": "fact",
                            "text": "Minimum SIP: INR 100",
                            "page_number": 2,
                        },
                        {
                            "kind": "faq",
                            "question": "How do I get a statement?",
                            "text": answer,
                            "page_number": 2,
                        },
                        {
                            "kind": "table",
                            "title": "Top holdings",
                            "rows": rows,
                            "page_number": 2,
                        },
                    ],
                }
            ]
        )

        chunks = chunk_documents(
            self.manifest_path,
            self.extracted_dir,
            tokenizer=WhitespaceTokenizer(),
            max_tokens=18,
            overlap_tokens=4,
        )

        fact = next(
            chunk for chunk in chunks if "Minimum SIP: INR 100" in chunk.text
        )
        self.assertEqual(fact.text, "Sample Fund - Minimum SIP: INR 100")
        self.assertEqual(fact.metadata["source_url"], "https://files.hdfcfund.com/source.pdf")
        self.assertEqual(fact.metadata["source_title"], "Sample KIM")
        self.assertEqual(fact.metadata["source_type"], "KIM")
        self.assertEqual(fact.metadata["publisher"], "HDFC Mutual Fund")
        self.assertEqual(fact.metadata["scheme_or_scope"], "Sample Fund")
        self.assertEqual(fact.metadata["section_path"], "Page 2 > Scheme facts")
        self.assertEqual(fact.metadata["page_number"], 2)
        self.assertEqual(fact.metadata["document_date"], "2025-11-21")
        self.assertEqual(fact.metadata["fetched_at"], "2026-09-29T08:00:00+00:00")
        self.assertEqual(len(fact.metadata["content_hash"]), 64)

        faq_chunks = [
            chunk
            for chunk in chunks
            if "How do I get a statement?" in chunk.metadata["section_path"]
        ]
        self.assertGreater(len(faq_chunks), 1)
        for chunk in faq_chunks:
            self.assertTrue(
                chunk.text.startswith("Question: How do I get a statement?\nAnswer: ")
            )
            self.assertLessEqual(chunk.metadata["token_count"], 18)
        faq_answer_tokens = " ".join(
            chunk.text.split("\nAnswer: ", 1)[1] for chunk in faq_chunks
        ).split()
        self.assertEqual(faq_answer_tokens, answer.split())

        table_chunks = [
            chunk for chunk in chunks if "Top holdings" in chunk.metadata["section_path"]
        ]
        self.assertGreater(len(table_chunks), 1)
        seen_rows = []
        for chunk in table_chunks:
            self.assertIn("Column headings: Company | Industry", chunk.text)
            self.assertLessEqual(chunk.metadata["token_count"], 18)
            seen_rows.extend(
                line for line in chunk.text.splitlines() if line.startswith("Company")
            )
        self.assertEqual(seen_rows, [f"Company{i} | Industry{i}" for i in range(8)])

    def test_standalone_sip_label_value_paragraphs_get_scheme_context(self):
        self.write_source(
            [
                {
                    "section_path": ["About Sample Fund"],
                    "blocks": [
                        {"kind": "paragraph", "text": "Min SIP"},
                        {"kind": "paragraph", "text": "INR 100"},
                    ],
                }
            ]
        )

        chunks = chunk_documents(
            self.manifest_path,
            self.extracted_dir,
            tokenizer=WhitespaceTokenizer(),
        )

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "Sample Fund - Min SIP: INR 100")
        self.assertLessEqual(chunks[0].metadata["token_count"], 220)

    def test_manifest_failures_and_source_url_mismatches_are_rejected(self):
        self.write_source(
            [
                {
                    "section_path": ["Facts"],
                    "blocks": [{"kind": "paragraph", "text": "A fact."}],
                }
            ]
        )
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["sources"][0]["status"] = "parse_failed"
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ChunkingError, "did not ingest successfully"):
            chunk_documents(
                self.manifest_path,
                self.extracted_dir,
                tokenizer=WhitespaceTokenizer(),
            )

        manifest["sources"][0]["status"] = "ok"
        manifest["sources"][0]["canonical_url"] = "https://files.hdfcfund.com/other.pdf"
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ChunkingError, "URL mismatch"):
            chunk_documents(
                self.manifest_path,
                self.extracted_dir,
                tokenizer=WhitespaceTokenizer(),
            )

    def test_long_label_value_first_row_is_not_misread_as_table_header(self):
        manager_names = " ".join(f"Manager{i}" for i in range(45))
        self.write_source(
            [
                {
                    "section_path": ["Page 2"],
                    "blocks": [
                        {
                            "kind": "table",
                            "title": "Scheme details",
                            "rows": [
                                ["Fund Manager*", manager_names],
                                ["Inception Date", "February 1, 1994"],
                            ],
                            "page_number": 2,
                        }
                    ],
                }
            ]
        )

        chunks = chunk_documents(
            self.manifest_path,
            self.extracted_dir,
            tokenizer=WhitespaceTokenizer(),
            max_tokens=70,
            overlap_tokens=10,
        )

        self.assertEqual(len(chunks), 1)
        self.assertNotIn("Column headings:", chunks[0].text)
        self.assertIn(f"Fund Manager* | {manager_names}", chunks[0].text)
        self.assertIn("Inception Date | February 1, 1994", chunks[0].text)
        self.assertLessEqual(chunks[0].metadata["token_count"], 70)

    def test_performance_sections_tables_and_return_metrics_are_excluded(self):
        self.write_source(
            [
                {
                    "section_path": ["Scheme", "About Scheme"],
                    "blocks": [
                        {"kind": "paragraph", "text": "Benchmark"},
                        {"kind": "paragraph", "text": "NIFTY 50 TRI"},
                        {"kind": "paragraph", "text": "Returns"},
                        {"kind": "paragraph", "text": "17.95%"},
                        {
                            "kind": "table",
                            "title": "Benchmark Performance",
                            "rows": [["Scheme Returns (%)", "17.95"]],
                        },
                    ],
                },
                {
                    "section_path": ["Scheme", "Benchmark Performance"],
                    "blocks": [{"kind": "paragraph", "text": "Historical data."}],
                },
            ]
        )

        chunks = chunk_documents(
            self.manifest_path,
            self.extracted_dir,
            tokenizer=WhitespaceTokenizer(),
        )

        joined_text = "\n".join(chunk.text for chunk in chunks)
        self.assertIn("NIFTY 50 TRI", joined_text)
        self.assertNotIn("17.95%", joined_text)
        self.assertNotIn("Scheme Returns", joined_text)
        self.assertNotIn("Historical data", joined_text)

    def test_scheme_category_values_get_context_and_statement_or_is_excluded(self):
        sources = [
            {
                "source_id": "1",
                "scheme_or_scope": "HDFC Large Cap Fund",
                "source_type": "Scheme page",
                "publisher": "HDFC Mutual Fund",
                "url": "https://www.hdfcfund.com/large-cap",
                "canonical_url": "https://www.hdfcfund.com/large-cap",
                "status": "ok",
                "fetched_at": "2026-09-29T08:00:00+00:00",
            },
            {
                "source_id": "5",
                "scheme_or_scope": "HDFC Balanced Advantage Fund",
                "source_type": "Scheme page",
                "publisher": "HDFC Mutual Fund",
                "url": "https://www.hdfcfund.com/balanced-advantage",
                "canonical_url": "https://www.hdfcfund.com/balanced-advantage",
                "status": "ok",
                "fetched_at": "2026-09-29T08:00:00+00:00",
            },
            {
                "source_id": "17",
                "scheme_or_scope": "All HDFC Mutual Fund investors",
                "source_type": "Consolidated Account Statement",
                "publisher": "HDFC Mutual Fund",
                "url": "https://www.hdfcfund.com/consolidated-account-statement",
                "canonical_url": "https://www.hdfcfund.com/consolidated-account-statement",
                "status": "ok",
                "fetched_at": "2026-09-29T08:00:00+00:00",
            },
        ]
        documents = {
            "1": (
                "HDFC Large Cap Fund",
                [
                    {
                        "section_path": ["HDFC Large Cap Fund"],
                        "blocks": [{"kind": "paragraph", "text": "Equity"}],
                    }
                ],
            ),
            "5": (
                "HDFC Balanced Advantage Fund",
                [
                    {
                        "section_path": ["HDFC Balanced Advantage Fund"],
                        "blocks": [{"kind": "paragraph", "text": "Hybrid"}],
                    }
                ],
            ),
            "17": (
                "Download Consolidated Account Statement",
                [
                    {
                        "section_path": ["Download Statement"],
                        "blocks": [{"kind": "paragraph", "text": "OR"}],
                    }
                ],
            ),
        }
        for source in sources:
            title, sections = documents[source["source_id"]]
            (self.extracted_dir / f"source-{source['source_id']}.json").write_text(
                json.dumps(
                    {
                        "source_url": source["canonical_url"],
                        "title": title,
                        "document_date": None,
                        "sections": sections,
                    }
                ),
                encoding="utf-8",
            )
        self.manifest_path.write_text(
            json.dumps({"sources": sources}), encoding="utf-8"
        )

        chunks = chunk_documents(
            self.manifest_path,
            self.extracted_dir,
            tokenizer=WhitespaceTokenizer(),
        )

        self.assertEqual(
            [chunk.text for chunk in chunks],
            [
                "Scheme: HDFC Large Cap Fund\nScheme category: Equity",
                "Scheme: HDFC Balanced Advantage Fund\nScheme category: Hybrid",
            ],
        )
        self.assertEqual([chunk.metadata["source_id"] for chunk in chunks], ["1", "5"])

    def test_readable_dump_includes_metadata_and_text(self):
        self.write_source(
            [
                {
                    "section_path": ["Facts"],
                    "blocks": [{"kind": "paragraph", "text": "Public fact."}],
                }
            ]
        )
        chunks = chunk_documents(
            self.manifest_path,
            self.extracted_dir,
            tokenizer=WhitespaceTokenizer(),
        )
        output_path = self.root / "processed" / "chunks.txt"

        write_chunk_dump(chunks, output_path)

        dump = output_path.read_text(encoding="utf-8")
        self.assertIn("chunk_id:", dump)
        self.assertIn("source_url: https://files.hdfcfund.com/source.pdf", dump)
        self.assertIn("Public fact.", dump)


if __name__ == "__main__":
    unittest.main()