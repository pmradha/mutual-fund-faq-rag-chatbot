"""Minimal HTTP API for the facts-only answer service."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Any

from answer import AnswerService


MAX_REQUEST_BYTES = 16_384


def create_server(
    service: Any | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> ThreadingHTTPServer:
    answer_service = service or AnswerService()

    class AnswerRequestHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/api/answer":
                self._send_json(404, {"error": "Not found"})
                return

            try:
                content_length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._send_json(400, {"error": "Invalid request"})
                return
            if content_length <= 0:
                self._send_json(400, {"error": "Invalid request"})
                return
            if content_length > MAX_REQUEST_BYTES:
                self._send_json(413, {"error": "Request too large"})
                return

            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"error": "Invalid request"})
                return
            if (
                not isinstance(payload, dict)
                or set(payload) != {"question"}
                or not isinstance(payload["question"], str)
                or not payload["question"].strip()
            ):
                self._send_json(400, {"error": "Invalid request"})
                return

            try:
                answer = answer_service.answer(payload["question"])
            except Exception:
                self._send_json(500, {"error": "Unable to answer request"})
                return
            self._send_json(200, {"answer": answer})

        def _send_json(self, status: int, payload: dict[str, str]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return ThreadingHTTPServer((host, port), AnswerRequestHandler)


def serve() -> None:
    server = create_server()
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()