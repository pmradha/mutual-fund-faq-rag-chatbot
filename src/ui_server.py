"""Serve the Phase 4 chat UI and proxy requests to the Phase 3 API."""

from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
from typing import Any


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
BACKEND_URL = "http://127.0.0.1:8000/api/answer"
MAX_REQUEST_BYTES = 16_384


def create_server(host: str = "127.0.0.1", port: int = 8001) -> ThreadingHTTPServer:
    class UIRequestHandler(SimpleHTTPRequestHandler):
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

            body = self.rfile.read(content_length)
            request = Request(
                BACKEND_URL,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=65) as response:
                    self._send_response(response.status, response.read())
            except HTTPError as error:
                self._send_response(error.code, error.read())
            except URLError:
                self._send_json(502, {"error": "Answer service unavailable"})

        def _send_json(self, status_code: int, payload: dict[str, str]) -> None:
            self._send_response(status_code, json.dumps(payload).encode("utf-8"))

        def _send_response(self, status_code: int, body: bytes) -> None:
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    handler = partial(UIRequestHandler, directory=str(WEB_ROOT))
    return ThreadingHTTPServer((host, port), handler)


def serve() -> None:
    server = create_server()
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()