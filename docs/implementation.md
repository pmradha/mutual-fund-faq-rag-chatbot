# Implementation Plan

This plan follows `PRD.md` and `architecture.md`. File paths below are proposed component boundaries; choose the application framework during project setup. No implementation is included in this plan.

| Phase | Build | Main files/components | Validation |
| --- | --- | --- | --- |
| 1. Source ingestion | Secure configuration, approved-URL fetcher, and HTML/PDF extraction with source status and dates. Remove navigation and form controls; retain headings, FAQ pairs, table structure, and PDF pages. | `.env.example`, `.gitignore`, `source_corpus.csv`, `src/ingestion/fetch.py`, `src/ingestion/extract.py`, source manifest | Validate allowed publishers/URLs; verify fetch and parse results per source; inspect extracted sections and table rows; confirm PAN form controls are excluded and failures do not silently pass. |
| 2. Chunking and index | Implement documented heading/FAQ/table-aware chunking (220-token cap, 40-token prose overlap), readable chunk dump, local `sentence-transformers/all-MiniLM-L6-v2` embeddings for chunks, and persistent ChromaDB storage with source metadata. | `src/ingestion/chunk.py`, `src/embeddings.py`, `src/vector_store.py`, `data/processed/chunks.txt`, `data/chroma/`, focused tests | Check token limits, boundary/overlap rules, row integrity, metadata and 384-dimensional vectors; inspect the chunk dump; restart and confirm Chroma persistence and content-hash-based re-indexing. |
| 3. Safe answer service | Add query checks, retrieval using the same embedding model, Groq generation through a server-side key, and output enforcement for grounding, citations, length, and source-date statement. | `src/safety.py`, `src/retrieval.py`, `src/answer.py`, backend API, `.env` | Test factual and unsupported questions, advice and performance refusals, sensitive-data rejection before logging or external calls, one canonical source URL, maximum three sentences, and `Last updated from sources:`. |
| 4. Chat interface | Build the chat experience with the PRD welcome message, three example questions, visible facts-only notice, and backend-connected question/answer flow. | Frontend chat view/components, backend API integration | Verify initial content, example-question submission, answer/source rendering, refusal states, and that the Groq key is absent from frontend assets and network responses. |
| 5. End-to-end acceptance | Integrate ingestion, retrieval, answer service, and interface; document local setup and run procedure. | Application entry point, integration tests, `README.md` | Run representative FAQs for all required fact types plus unsupported/advice/performance/PII cases; confirm citations point to retrieved canonical sources, answer limits hold, Chroma survives restart, and the full flow works from a clean setup. |

## Phase 2B Validation Results

- Indexed all 547 chunks from `data/processed/chunks.txt` with `sentence-transformers/all-MiniLM-L6-v2`; stored embeddings are 384-dimensional.
- Persistent ChromaDB storage under `data/chroma/` was reopened and verified. Similarity retrieval returned matching minimum-SIP fact chunks.
- Repeat indexing added 0 chunks, updated 0 metadata records, and removed 0 chunks.
- All 25 repository tests passed.
- Known non-failing warnings: Python 3.14/Chroma telemetry deprecation and the existing HTTP 403 resource-cleanup warning.

Keep generated source snapshots, vectors, credentials, and user input out of version control as appropriate. Do not enable conversation persistence or use the reader view/Jina as a production fetch dependency without approval. If source fetch or extraction is unreliable, stop ingestion for that source rather than answering from model knowledge.
