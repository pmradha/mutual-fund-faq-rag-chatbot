"""Command line entry point for approved-source ingestion and extraction."""

from __future__ import annotations

import argparse
from pathlib import Path

from ingestion.pipeline import ingest_sources


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch and extract approved FAQ source documents.")
    parser.add_argument("--manifest", type=Path, default=PROJECT_ROOT / "source_corpus.csv")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--max-bytes", type=int, default=30 * 1024 * 1024)
    args = parser.parse_args()

    try:
        results = ingest_sources(args.manifest, args.output_dir, args.timeout, args.max_bytes)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    for result in results:
        status = result["status"]
        detail = result.get("error", result.get("title", ""))
        print(f"[{status}] {result['source_id']} {result['url']} {detail}".rstrip())

    succeeded = sum(result["status"] == "ok" for result in results)
    failed = len(results) - succeeded
    print(f"Ingestion complete: {succeeded} succeeded, {failed} failed; manifest: {args.output_dir / 'manifest.json'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())