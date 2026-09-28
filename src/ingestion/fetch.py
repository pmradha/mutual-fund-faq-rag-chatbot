"""Fetch approved sources directly from their canonical HTTPS URLs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ingestion.manifest import SourceRecord, is_approved_url


USER_AGENT = "HDFC-Mutual-Fund-FAQ-Prototype/0.1"
DEFAULT_MAX_BYTES = 30 * 1024 * 1024


class SourceFetchError(RuntimeError):
    """A source could not be safely fetched; includes an HTTP status when available."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class FetchedSource:
    canonical_url: str
    content_type: str
    fetched_at: str
    content_sha256: str
    content: bytes


class _ApprovedRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        if not is_approved_url(new_url):
            raise SourceFetchError("Redirect target is not an approved HTTPS source")
        return super().redirect_request(request, response, code, message, headers, new_url)


def fetch_source(
    source: SourceRecord,
    timeout_seconds: float = 20,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> FetchedSource:
    """Fetch one allowlisted URL, rejecting redirects or payloads outside the source policy."""
    if not is_approved_url(source.url):
        raise SourceFetchError("Source URL is not approved")
    if timeout_seconds <= 0 or max_bytes <= 0:
        raise ValueError("Timeout and maximum response size must be positive")

    request = Request(
        source.url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/pdf",
            "User-Agent": USER_AGENT,
        },
    )
    opener = build_opener(_ApprovedRedirectHandler())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            if not is_approved_url(final_url):
                raise SourceFetchError("Final response URL is not an approved HTTPS source")
            content = response.read(max_bytes + 1)
            content_type = response.headers.get_content_type().lower()
    except HTTPError as error:
        raise SourceFetchError(f"HTTP {error.code}", status_code=error.code) from error
    except URLError as error:
        raise SourceFetchError(f"Network error: {error.reason}") from error

    if len(content) > max_bytes:
        raise SourceFetchError(f"Response exceeds the {max_bytes}-byte limit")
    if content.startswith(b"%PDF-"):
        if content_type not in {"application/pdf", "application/octet-stream"}:
            raise SourceFetchError(f"PDF signature has unexpected content type {content_type!r}")
        content_type = "application/pdf"
    elif content_type not in {"text/html", "application/xhtml+xml"}:
        raise SourceFetchError(f"Unsupported source content type {content_type!r}")

    return FetchedSource(
        canonical_url=source.url,
        content_type=content_type,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        content_sha256=hashlib.sha256(content).hexdigest(),
        content=content,
    )