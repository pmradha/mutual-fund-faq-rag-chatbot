"""Load and validate the approved source inventory."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from urllib.parse import urlsplit


REQUIRED_FIELDS = (
    "id",
    "scheme_or_scope",
    "source_type",
    "publisher",
    "faq_coverage",
    "url",
)
APPROVED_DOMAINS = {
    "hdfcfund.com",
    "hdfcamc.com",
    "sebi.gov.in",
    "amfiindia.com",
}
PUBLISHER_DOMAINS = {
    "hdfc mutual fund": ("hdfcfund.com", "hdfcamc.com"),
    "hdfc asset management company": ("hdfcamc.com", "hdfcfund.com"),
    "sebi": ("sebi.gov.in",),
    "amfi": ("amfiindia.com",),
}


class ManifestError(ValueError):
    """Raised when the source inventory is invalid or contains an unapproved URL."""


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    scheme_or_scope: str
    source_type: str
    publisher: str
    faq_coverage: str
    url: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def is_approved_url(url: str) -> bool:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    try:
        has_port = parsed.port is not None
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(hostname)
        and parsed.username is None
        and parsed.password is None
        and not has_port
        and any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in APPROVED_DOMAINS
        )
    )


def _publisher_matches_host(publisher: str, url: str) -> bool:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    approved_domains = PUBLISHER_DOMAINS.get(publisher.casefold())
    return bool(
        approved_domains
        and any(hostname == domain or hostname.endswith(f".{domain}") for domain in approved_domains)
    )


def load_source_manifest(path: str | Path) -> list[SourceRecord]:
    """Read the CSV and reject malformed rows or non-approved source hosts."""
    manifest_path = Path(path)
    try:
        stream = manifest_path.open(newline="", encoding="utf-8-sig")
    except OSError as error:
        raise ManifestError(f"Cannot open source manifest {manifest_path}: {error}") from error

    with stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ManifestError("Source manifest is missing its CSV header")
        missing_fields = [field for field in REQUIRED_FIELDS if field not in reader.fieldnames]
        if missing_fields:
            raise ManifestError(f"Source manifest is missing columns: {', '.join(missing_fields)}")

        records: list[SourceRecord] = []
        seen_ids: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            values = {field: (row.get(field) or "").strip() for field in REQUIRED_FIELDS}
            if any(not value for value in values.values()):
                raise ManifestError(f"Row {row_number} has an empty required field")
            if values["id"] in seen_ids:
                raise ManifestError(f"Row {row_number} repeats source id {values['id']!r}")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", values["id"]):
                raise ManifestError(f"Row {row_number} has an unsafe source id")
            if not is_approved_url(values["url"]):
                raise ManifestError(
                    f"Row {row_number} uses an unapproved or invalid HTTPS URL: {values['url']}"
                )
            if not _publisher_matches_host(values["publisher"], values["url"]):
                raise ManifestError(
                    f"Row {row_number} publisher does not match its approved source host"
                )

            seen_ids.add(values["id"])
            records.append(
                SourceRecord(
                    source_id=values["id"],
                    scheme_or_scope=values["scheme_or_scope"],
                    source_type=values["source_type"],
                    publisher=values["publisher"],
                    faq_coverage=values["faq_coverage"],
                    url=values["url"],
                )
            )

        if not records:
            raise ManifestError("Source manifest contains no source records")
        return records