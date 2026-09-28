# RAG Architecture

## Scope and source inspection

This is a small, source-grounded FAQ prototype for the five HDFC Mutual Fund schemes in `PRD.md`. The current `source_corpus.csv` contains 17 official HDFC Mutual Fund records: five scheme pages, five Key Information Memorandums (KIMs), five Fund Facts PDFs, and two investor-statement pages. A text-reader view was used only to inspect/retrieve content because direct requests from this environment received HTTP 403 responses; the canonical knowledge sources and citation URLs remain the official HDFC URLs in `source_corpus.csv`.

The inspected formats have different natural boundaries:

- Scheme pages are long HTML pages (roughly 32,000–36,000 extracted characters) with named sections such as “Exit Load,” “Benchmark Performance,” and riskometer content, mixed with navigation and performance material.
- KIM PDFs are 22–25 pages, with headings, prose, scheme facts, and tables.
- Fund Facts PDFs are 2–3 pages, usually date-labelled, with short prose sections and dense portfolio/fund-fact tables. Text extraction can flatten table columns, so table structure must be retained during extraction.
- The statement pages are long HTML pages (roughly 24,000–26,000 extracted characters); one has FAQ question/answer entries, while the other includes a statement-request form. The form contains a PAN field and must not be ingested as user data or used to collect data.

The 2026 Fund Facts PDFs include holdings and portfolio statistics, and scheme pages contain performance sections. Those passages do not expand the product scope: performance calculations, comparisons, predictions, and investment recommendations remain disallowed by the PRD.

## Components

1. **Source manifest:** `source_corpus.csv` is the allowlist and source metadata for ingestion. Accept only validated public sources from HDFC Mutual Fund/HDFC AMC, SEBI, and AMFI.
2. **Ingestion and extraction:** Fetch each approved URL, record retrieval status and time, and extract HTML sections and PDF text with layout information. Remove repeated navigation and unrelated boilerplate. Preserve table row/column relationships and PDF page numbers. Exclude interactive form controls, including the PAN field, from extracted content.
3. **Chunker:** Create bounded, structure-aware chunks as described below. Write a readable chunk dump for inspection before or alongside indexing.
4. **Embedding model:** Use `sentence-transformers/all-MiniLM-L6-v2` for both document chunks and user queries. This keeps the embedding space consistent and runs locally; the model produces 384-dimensional vectors.
5. **Vector store:** ChromaDB holds chunk text, vectors, and citation metadata in a persistent local on-disk collection.
6. **Answer service:** Apply scope, advice/performance, and sensitive-data checks before retrieval or generation. For an in-scope factual question, retrieve only from the approved collection and send the question plus retrieved evidence to Groq. Require a concise, source-grounded response and validate its citation and response limits before returning it.
7. **Chat interface:** Present the PRD welcome message, three example questions, and `Facts-only. No investment advice.` Use the backend for Groq calls; never expose the API key in the browser.

## RAG flow

### Ingestion

```text
source_corpus.csv allowlist
  -> fetch approved official URLs
  -> extract HTML sections / PDF pages and table structure
  -> remove boilerplate and form controls
  -> split into structure-aware chunks
  -> embed chunks with sentence-transformers/all-MiniLM-L6-v2
  -> persist vectors, text, and metadata in ChromaDB
  -> write readable chunk text artifact
```

### Query

```text
user question
  -> reject advice/performance requests and sensitive personal data
  -> embed question with sentence-transformers/all-MiniLM-L6-v2
  -> retrieve relevant approved chunks from ChromaDB
  -> send question and evidence to Groq
  -> enforce grounding, one supporting source link, <= 3 sentences,
     and "Last updated from sources:" on factual answers
  -> return answer (do not persist the conversation)
```

If retrieved material does not support an answer, return the PRD's not-in-sources response rather than filling gaps from model knowledge. Advice or recommendation requests are refused; performance requests may be directed to an official source without calculating or comparing performance. Sensitive identifiers must not be sent to Groq, written to logs, or persisted.

## Chunking strategy

Use **220 model-token maximum per chunk**, with **40 model-token overlap only when splitting an oversized prose section**. The 220-token cap leaves room beneath the embedding model's 256-token input limit and keeps the retrieval unit focused. Overlap helps retain context when a long paragraph or prose section must be split; applying it everywhere would duplicate short facts and table rows across this small corpus.

Use semantic boundaries before token boundaries:

- HTML: keep a section heading with its paragraphs; split oversized sections at paragraph/sentence boundaries and repeat the section path in each chunk.
- KIMs and Fund Facts PDFs: keep heading plus related prose together. Chunk tables by complete logical rows and repeat the table title and column headings in each table chunk. Preserve page boundaries as metadata. Do not flatten a table into text if row/value association is lost; use layout-aware extraction or exclude that malformed passage until it can be extracted reliably.
- Statement FAQs: keep each question with its answer as one unit when it fits; split long answers at sentence boundaries while repeating the question/section label.
- Oversized blocks: split at sentence or row boundaries to stay within 220 tokens. Apply the 40-token overlap to prose splits only; do not overlap across headings, FAQ pairs, or table rows.

Token counts must use the embedding model tokenizer, not character or word counts. Verify chunk lengths and inspect the generated `.txt` artifact before indexing. This is a proposed initial strategy based on the inspected documents; tune it against representative FAQ retrieval cases after extraction is implemented.

## Chunk metadata

Store the following fields on each chunk so retrieval, filtering, deduplication, and citations do not depend on generated text:

| Field | Purpose |
| --- | --- |
| `chunk_id` | Stable unique vector-store ID, derived from source identity and chunk position/content. |
| `source_id` | Row identifier from `source_corpus.csv`. |
| `source_url` | Canonical approved URL; used for the single citation link. |
| `source_title` | Document or page title extracted from the source. |
| `source_type` | Inventory type, such as Scheme page, KIM, Fund Facts, or statement page. |
| `publisher` | Source publisher from the inventory. |
| `scheme_or_scope` | Scheme name or investor scope from the inventory. |
| `section_path` | Heading hierarchy, FAQ question, or table title for context and filtering. |
| `page_number` | PDF page number; omit for HTML. |
| `document_date` | Publication/as-of date when explicitly available in the source; do not infer if absent. |
| `fetched_at` | UTC time this source version was retrieved; supports freshness reporting. |
| `content_hash` | Hash of normalized source content, to detect changes and avoid stale chunks. |
| `chunk_index` | Order of the chunk within its source section/document. |

Use scalar metadata values supported by ChromaDB. Keep the full URL and citation details with every chunk so the answer layer can cite the source actually retrieved. The displayed `Last updated from sources:` value should be based on source dates when known and otherwise transparently use the retrieval date.

## Storage and persistence

- Persist the ChromaDB collection under a local data directory (for example, `data/chroma/`) using ChromaDB's persistent client. Reuse the collection on application restart; re-embed only sources whose normalized content hash changed or which are new.
- Save extracted source snapshots and a manifest of fetch status, content hash, and fetch time alongside the generated chunks artifact. Keep the readable chunk dump (for example, `data/processed/chunks.txt`) as a reviewable build output.
- Keep `.env`, the Groq API key, and local user data out of version control. Keep the Groq key server-side. Do not store questions, answers, or conversation history; do not log sensitive input. Reject sensitive identifiers before they reach retrieval, the LLM, or logging.
- Treat a failed fetch, parse error, or malformed table as an ingestion error, not as permission to answer from model knowledge. Preserve source URL and retrieval status for operational diagnosis.

## Why this fits the milestone

- The inventory has only 17 approved records, making local ingestion and a single persistent Chroma collection practical without distributed services.
- Heading, FAQ, page, and table-aware chunking follows the actual source formats instead of treating the CSV inventory as document text. A 220-token cap also fits the selected model's 256-token input limit; a narrow 40-token prose overlap preserves continuity without needlessly duplicating compact facts.
- The same local embedding model for indexing and querying satisfies the PRD and avoids mismatched vector spaces. Groq is reserved for answer generation, as required.
- Explicit dates, URLs, section paths, page numbers, and content hashes support citations, freshness statements, and safe incremental re-indexing.
- A readable chunk artifact and persistent local vectors make the complete retrieval flow inspectable and repeatable for a small prototype.
- Keeping user conversations transient and filtering sensitive data before external generation directly supports the PRD's privacy and safety requirements.

## Implementation boundary

This document proposes the architecture only. No code, dependencies, source downloads, or chunking implementation are added here. Direct HDFC origin requests returned HTTP 403 during inspection; the reader view/Jina is not yet an approved production dependency. The implementation must use a supported, approved fetch path and verify retrieved content against the canonical source URL before ingestion. Recheck document dates and extraction quality at ingestion time because web pages and monthly factsheets can change.
