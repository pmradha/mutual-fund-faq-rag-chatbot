# Repository Instructions

## Product

Build a factual FAQ assistant for the five HDFC Mutual Fund schemes listed in `docs/PRD.md`. Treat the PRD as the product source of truth and `source_corpus.csv` as the approved-source inventory.

## Non-negotiable behavior

- Answer only factual questions supported by retrieved content from approved sources. Do not use model knowledge to fill gaps; say when the corpus does not contain the answer.
- Do not give investment advice or recommendations, tell users to buy/sell/hold/switch, rank schemes, predict returns, or calculate/compare performance. Refuse these requests politely; performance questions may be directed to an official source.
- Every factual answer must include one clear link to the source that supports it, be no more than three sentences, and include the `Last updated from sources:` statement.
- Display `Facts-only. No investment advice.` and the welcome message and three example questions described in the PRD.
- Do not accept or store PAN, Aadhaar, bank/account numbers, OTPs, email addresses, or phone numbers. Keep the Groq API key server-side in `.env`; never expose or commit it.

## RAG requirements

- Use `sentence-transformers/all-MiniLM-L6-v2` for both source and query embeddings.
- Use ChromaDB with a persistent on-disk store and Groq for answer generation.
- Preserve source URL and enough source metadata on every chunk for reliable citations.
- Save generated chunks to a readable `.txt` artifact.
- Do not choose or implement chunking based only on `source_corpus.csv`: it is an inventory of 17 source records, not the source document contents. First inspect the fetched source data, then document chunk size, overlap, boundary strategy, and retained metadata before implementing chunking.
- Limit ingestion to validated public sources from HDFC Mutual Fund/HDFC AMC, SEBI, and AMFI, as specified in the PRD.

## Development

- Keep changes focused and follow existing repository conventions. The repository currently contains the PRD and source inventory; do not assume an application framework or invent product requirements where the PRD is silent.
- Add focused tests for behavior and safety rules when implementing them. Validate changes with the narrowest relevant checks available.
