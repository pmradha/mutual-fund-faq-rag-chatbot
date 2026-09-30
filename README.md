# HDFC Mutual Fund FAQ Assistant

A prototype facts-only assistant for factual questions about the five HDFC Mutual Fund schemes listed in `docs/PRD.md`. The chat UI calls the local backend; Groq credentials stay server-side.

## Run locally

Use Python 3.10 or newer and install the packages listed in `requirements.txt`. Set `GROQ_API_KEY` in the backend process environment or in a local `.env` file at the repository root. Do not put the key in browser code or commit `.env`.

Start the answer API in one terminal:

```sh
python src/api.py
```

Start the chat UI in another terminal:

```sh
python src/ui_server.py
```

Open <http://127.0.0.1:8001/>. The UI server forwards `/api/answer` to the answer API at `127.0.0.1:8000`. The corpus must already be indexed in the local ChromaDB store for factual answers to be available.

## Acceptance tests

Run the complete test suite without a Groq key or network call to Groq:

```sh
python -m unittest discover -s tests -v
```

The end-to-end acceptance test uses the existing fake retrieval and generation fixtures to exercise the chat proxy, HTTP API, and answer service together. It does not verify live Groq behavior.