# Groww Mutual Fund FAQ Assistant — RAG

## 1. Product Overview

**Product:** Groww
**Use case:** Mutual Fund FAQ Assistant
**AMC:** HDFC Mutual Fund

**Schemes covered:**

* HDFC Large Cap Fund
* HDFC Flexi Cap Fund
* HDFC ELSS Tax Saver Fund
* HDFC Small Cap Fund
* HDFC Balanced Advantage Fund

The product is a small Retrieval-Augmented Generation (RAG) chatbot that answers **factual questions about the covered mutual-fund schemes using only the approved source corpus**.

The chatbot helps users quickly find factual information about mutual-fund schemes **without providing investment advice or making investment decisions for them**.

---

## 2. Problem

Retail mutual-fund users may need to search across multiple scheme documents and investor-service pages to find simple factual information such as expense ratio, exit load, minimum SIP, lock-in period, riskometer, benchmark, or how to obtain statements.

The chatbot should make these facts easier to find while maintaining a clear boundary between **factual information and investment advice**.

---

## 3. Goal

Build a working FAQ assistant that:

1. Retrieves relevant information from a curated corpus of **15–25 official public source pages/documents**.
2. Answers factual mutual-fund questions using retrieved source content.
3. Provides **one clear source link with every answer**.
4. Refuses questions that require investment advice, recommendations, or decisions.
5. Clearly communicates that the chatbot provides **facts only and not investment advice**.

---

## 4. Target Users

### Primary users

Retail users researching or looking for factual information about mutual-fund schemes.

### Secondary users

Support or content teams handling repetitive mutual-fund factual questions.

---

## 5. In Scope

### Factual questions

The chatbot should support questions such as:

* What is the expense ratio?
* What is the minimum SIP/investment amount?
* What is the exit load?
* What is the lock-in period for the ELSS fund?
* What is the riskometer?
* What is the benchmark?
* How can I download/request a capital-gains or account statement?
* Other factual questions that can be answered from the approved source corpus.

### User experience

The prototype should include:

* A short welcome message.
* Three example questions.
* A visible **“Facts-only. No investment advice.”** notice.
* A concise answer of no more than **3 sentences**.
* One clear source link.
* A **“Last updated from sources:”** statement.

---

## 6. Out of Scope

The chatbot must not:

* Recommend a mutual fund.
* Tell users whether they should buy, sell, hold, or switch a fund.
* Recommend a portfolio or asset allocation.
* Rank schemes as better or worse for investment.
* Predict future returns.
* Calculate or compare investment performance/returns.
* Provide personalized financial advice.
* Accept or store sensitive personal information.

---

## 7. Answer & Safety Rules

These are core product requirements.

### 7.1 Facts only

The chatbot should answer only questions that can be supported by the approved source corpus.

### 7.2 No investment decisions

For questions such as:

* “Should I buy this fund?”
* “Should I sell this fund?”
* “Which fund should I choose?”
* “Which is better for me?”

the chatbot should politely refuse to provide a recommendation and, where appropriate, provide a relevant educational source.

### 7.3 No performance claims

The chatbot must not:

* Calculate returns.
* Compare returns between schemes.
* Predict future performance.
* Make claims about which scheme will perform better.

If a user asks about performance, the chatbot may direct the user to the relevant official factsheet/source.

### 7.4 Source-grounded answers

The chatbot should answer using the retrieved source content rather than unsupported general knowledge.

If the available source content does not support the answer, the chatbot should say that the information is not available in the provided sources rather than inventing an answer.

### 7.5 Citation requirement

**Every factual answer must contain one clear source link.**

The source link should correspond to the source from which the retrieved information was obtained.

### 7.6 PII protection

The chatbot must not accept or store:

* PAN
* Aadhaar
* Bank/account numbers
* OTPs
* Email addresses
* Phone numbers

---

## 8. Knowledge Corpus

The RAG corpus will contain **15–25 validated public source pages/documents**.

The source ecosystem should be limited to approved official sources, primarily:

* HDFC Mutual Fund / HDFC Asset Management Company
* SEBI
* AMFI

Third-party blogs and generic finance websites are excluded.

The authoritative source inventory will be maintained in:

**`source_corpus.csv`**

Each source should have a clear purpose in supporting the chatbot's factual FAQ use cases.

---

## 9. RAG Approach

The chatbot will use a Retrieval-Augmented Generation architecture.

### Data ingestion

**Load → Chunk → Embed → Store**

### Query and retrieval

**Question → Embed → Retrieve relevant chunks → LLM → Answer**

The retrieved source information will be passed to the LLM as context so that answers are grounded in the approved corpus.

---

## 10. Technical Requirements

### Embedding model

Use:

`sentence-transformers/all-MiniLM-L6-v2`

The same embedding model must be used for:

* Source chunks
* User questions

The model runs locally and produces 384-dimensional embeddings.

### Chunking

The AI coding agent should inspect the actual source data **before implementing chunking**.

It should propose and document:

* Chunk size
* Chunk overlap
* Chunk boundaries/strategy
* Metadata retained with each chunk

The strategy should be appropriate for the structure of the source documents.

All generated chunks must also be saved to a readable `.txt` file so they can be inspected.

### Vector database

Use **ChromaDB**.

The ChromaDB store must be persisted to disk so that the corpus does not need to be re-ingested and re-embedded every time the application restarts.

### LLM

Use **Groq** for answer generation.

The Groq API key must:

* Be stored in `.env`.
* Never be committed to Git.
* Never be exposed in the frontend.

### Source metadata

Each retrieved chunk should retain sufficient metadata to identify its source and support citation generation, including the source URL.

The exact metadata structure should be proposed by the AI coding agent after inspecting the corpus.

---

## 11. Core User Flow

```text
User asks a question
        ↓
Determine whether the question is factual and in scope
        ↓
If not appropriate → polite facts-only refusal
        ↓
If factual → embed the question
        ↓
Retrieve relevant chunks from ChromaDB
        ↓
Pass retrieved context + question to Groq
        ↓
Generate concise factual answer
        ↓
Add one source link
        ↓
Add "Last updated from sources:"
```

---

## 12. Success Criteria

The prototype is successful when:

1. A user can ask factual questions about the covered schemes.
2. The system retrieves relevant source content.
3. The answer is grounded in the retrieved content.
4. Every factual answer provides one clear source link.
5. Answers are no more than 3 sentences.
6. Advice/recommendation questions are refused appropriately.
7. The system does not make performance claims.
8. The system does not accept/store PII.
9. ChromaDB persists between application restarts.
10. The source chunks can be inspected independently.
11. The prototype demonstrates the complete RAG flow from retrieval to answer.

---

## 13. Key Evaluation Areas

### W1 — Thinking Like a Model

The system distinguishes between:

**Answerable factual question → answer**

and

**Advice/opinion/unsupported question → refuse or state that the source corpus does not provide the information.**

### W2 — LLMs & Prompting

The system uses clear instructions for:

* concise answers
* facts-only behavior
* safe refusal
* source grounding
* citation
* transparency

### W3 — RAG

The system demonstrates:

**accurate retrieval from a small official-source corpus with source-linked answers.**

---

## 14. Known Limitations

The chatbot is intentionally a small, curated FAQ prototype.

It does not attempt to:

* cover all mutual funds,
* provide personalized investment advice,
* replace official scheme documents,
* provide a complete financial-planning service,
* make investment decisions for users.

The quality of answers depends on the coverage and accuracy of the curated source corpus.
