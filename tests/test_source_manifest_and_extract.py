import csv
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ingestion.extract import extract_document, extract_html, extract_pdf
from ingestion.fetch import FetchedSource, SourceFetchError, fetch_source
from ingestion.manifest import ManifestError, SourceRecord, is_approved_url, load_source_manifest
from ingestion.pipeline import ingest_sources


class SourceManifestTests(unittest.TestCase):
    def test_loads_all_approved_inventory_records(self):
        records = load_source_manifest(ROOT / "source_corpus.csv")
        self.assertEqual(len(records), 17)
        self.assertEqual(records[0].source_id, "1")
        self.assertEqual(records[0].url, "https://www.hdfcfund.com/explore/mutual-funds/hdfc-large-cap-fund/regular")

    def test_rejects_unapproved_hosts_and_non_https_urls(self):
        self.assertTrue(is_approved_url("https://files.hdfcfund.com/facts.pdf"))
        self.assertFalse(is_approved_url("https://hdfcfund.com.attacker.example/file"))
        self.assertFalse(is_approved_url("http://hdfcfund.com/file"))
        self.assertFalse(is_approved_url("https://user@hdfcfund.com/file"))

    def test_rejects_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "sources.csv"
            fields = ["id", "scheme_or_scope", "source_type", "publisher", "faq_coverage", "url"]
            row = ["1", "Scheme", "Scheme page", "HDFC Mutual Fund", "Facts", "https://www.hdfcfund.com/a"]
            with manifest_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(fields)
                writer.writerow(row)
                writer.writerow(row)
            with self.assertRaisesRegex(ManifestError, "repeats source id"):
                load_source_manifest(manifest_path)

    def test_rejects_publisher_host_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "sources.csv"
            fields = ["id", "scheme_or_scope", "source_type", "publisher", "faq_coverage", "url"]
            row = ["1", "Scheme", "Scheme page", "SEBI", "Facts", "https://www.hdfcfund.com/a"]
            with manifest_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(fields)
                writer.writerow(row)
            with self.assertRaisesRegex(ManifestError, "publisher does not match"):
                load_source_manifest(manifest_path)


class HtmlExtractionTests(unittest.TestCase):
    def test_extracts_sections_tables_and_dates_without_navigation_or_form(self):
        html = b"""<!doctype html><html><head>
        <title>Sample Scheme</title><meta property='article:published_time' content='2026-09-01T10:00:00Z'>
        </head><body><nav>Menu text</nav><main><h1>Scheme</h1>
        <h2>Exit Load</h2><p>One percent within one year.</p>
        <table><tr><th>Plan</th><th>Amount</th></tr><tr><td>SIP</td><td>100</td></tr></table>
        <form><label>PAN</label><input name='pan' value='not content'></form>
        <script>hidden code</script></main></body></html>"""

        document = extract_html(html, "https://www.hdfcfund.com/sample")

        self.assertEqual(document.title, "Sample Scheme")
        self.assertEqual(document.document_date, "2026-09-01")
        content = " ".join(block.text for section in document.sections for block in section.blocks)
        self.assertIn("One percent within one year.", content)
        self.assertNotIn("Menu text", content)
        self.assertNotIn("PAN", content)
        self.assertNotIn("hidden code", content)
        section = next(section for section in document.sections if section.section_path[-1] == "Exit Load")
        table_block = next(block for block in section.blocks if block.kind == "table")
        self.assertEqual(table_block.rows[1], ["SIP", "100"])

    def test_dispatch_requires_html_content_type_or_pdf_signature(self):
        with self.assertRaisesRegex(ValueError, "Unsupported source content type"):
            extract_document(b"not html", "https://www.hdfcfund.com/page", "text/plain")
        document = extract_document(b"<html><body><p>Text</p></body></html>", "https://www.hdfcfund.com/page", "text/html")
        self.assertEqual(document.sections[0].blocks[0].text, "Text")


class PdfExtractionTests(unittest.TestCase):
    def test_preserves_page_text_and_table_rows(self):
        class FakePage:
            def extract_text(self, layout=False):
                return "Fund Facts\nBenchmark" if layout else "Fund Facts Benchmark"

            def extract_tables(self):
                return [[["Field", "Value"], ["Benchmark", "Index"]]]

        class FakePdf:
            metadata = {"Title": "Factsheet"}
            pages = [FakePage()]

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        fake_module = types.SimpleNamespace(open=lambda _: FakePdf())
        with patch.dict(sys.modules, {"pdfplumber": fake_module}):
            document = extract_pdf(b"%PDF-fake", "https://files.hdfcfund.com/facts.pdf")

        self.assertEqual(document.title, "Factsheet")
        self.assertEqual(document.page_count, 1)
        self.assertEqual(document.sections[0].blocks[0].page_number, 1)
        self.assertEqual(document.sections[0].blocks[1].rows[1], ["Benchmark", "Index"])


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.source = SourceRecord(
            source_id="1",
            scheme_or_scope="HDFC Large Cap Fund",
            source_type="Scheme page",
            publisher="HDFC Mutual Fund",
            faq_coverage="Fund facts",
            url="https://www.hdfcfund.com/sample",
        )

    def test_fetches_direct_approved_url_and_hashes_content(self):
        class Headers(dict):
            def get_content_type(self):
                return "text/html"

        class FakeResponse:
            headers = Headers()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, _):
                return b"<html><body>source</body></html>"

            def geturl(self):
                return "https://www.hdfcfund.com/sample"

        with patch("ingestion.fetch.build_opener") as build_opener_mock:
            build_opener_mock.return_value.open.return_value = FakeResponse()
            fetched = fetch_source(self.source)

        self.assertEqual(fetched.canonical_url, self.source.url)
        self.assertEqual(fetched.content_type, "text/html")
        self.assertEqual(len(fetched.content_sha256), 64)
        request = build_opener_mock.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, self.source.url)

    def test_preserves_http_403_as_fetch_error(self):
        from io import BytesIO
        from urllib.error import HTTPError

        with patch("ingestion.fetch.build_opener") as build_opener_mock:
            build_opener_mock.return_value.open.side_effect = HTTPError(
                self.source.url, 403, "Forbidden", {}, BytesIO(b"blocked")
            )
            with self.assertRaises(SourceFetchError) as context:
                fetch_source(self.source)

        self.assertEqual(context.exception.status_code, 403)

    def test_pipeline_continues_and_writes_status_manifest(self):
        html = b"<html><body><main><h1>Scheme</h1><p>Public facts.</p></main></body></html>"
        fetched = FetchedSource(
            canonical_url=self.source.url,
            content_type="text/html",
            fetched_at="2026-09-28T00:00:00+00:00",
            content_sha256="a" * 64,
            content=html,
        )
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "sources.csv"
            with manifest_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["id", "scheme_or_scope", "source_type", "publisher", "faq_coverage", "url"])
                writer.writeheader()
                writer.writerow({"id": "1", "scheme_or_scope": self.source.scheme_or_scope, "source_type": self.source.source_type, "publisher": self.source.publisher, "faq_coverage": self.source.faq_coverage, "url": self.source.url})
                writer.writerow({"id": "2", "scheme_or_scope": self.source.scheme_or_scope, "source_type": self.source.source_type, "publisher": self.source.publisher, "faq_coverage": self.source.faq_coverage, "url": "https://www.hdfcfund.com/blocked"})
            output_dir = Path(directory) / "output"
            with patch("ingestion.pipeline.fetch_source", side_effect=[fetched, SourceFetchError("HTTP 403", 403)]):
                results = ingest_sources(manifest_path, output_dir)

            self.assertEqual([item["status"] for item in results], ["ok", "fetch_failed"])
            self.assertEqual(results[1]["http_status"], 403)
            self.assertTrue((output_dir / "sources/source-1.html").exists())
            self.assertTrue((output_dir / "extracted/source-1.json").exists())
            self.assertTrue((output_dir / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()