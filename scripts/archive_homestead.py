#!/usr/bin/env python3
"""Capture the approved Homestead collections and produce a checksum manifest."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import ssl
import time
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "archive"
RAW = ARCHIVE / "raw"
MEDIA = ARCHIVE / "media"
MANIFEST = ARCHIVE / "manifest.json"
HOSTS = (
    "nojd.homestead.com",
    "karlaugust.homestead.com",
    "mortensen.homestead.com",
)
SEEDS = tuple(f"https://{host}/" for host in HOSTS)
HTML_EXTENSIONS = {"", ".htm", ".html"}
ASSET_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".gif",
    ".png",
    ".webp",
    ".pdf",
    ".ged",
    ".txt",
}
EXCLUDED_PATH_PARTS = (
    "/~site/",
    "/~media/",
    "/~globals/",
    "/scripts_",
)
USER_AGENT = "FamilyHistoryPreservation/1.0 (+https://github.com/garynye/familyhistory)"


class ReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"a", "link"} and values.get("href"):
            self.references.append(values["href"] or "")
        if tag in {"img", "source"} and values.get("src"):
            self.references.append(values["src"] or "")


def canonical_url(candidate: str, base: str) -> str | None:
    candidate = candidate.strip()
    if not candidate or candidate.startswith(("#", "mailto:", "javascript:", "data:")):
        return None
    parsed = urlparse(urljoin(base, candidate))
    host = (parsed.hostname or "").lower()
    if host not in HOSTS:
        return None
    path = parsed.path or "/"
    if any(part in path.lower() for part in EXCLUDED_PATH_PARTS):
        return None
    return urlunparse(("https", host, path, "", "", ""))


def safe_relative_path(url: str, *, html: bool) -> Path:
    parsed = urlparse(url)
    raw_path = unquote(parsed.path).lstrip("/") or "index.html"
    clean_parts = []
    for part in PurePosixPath(raw_path).parts:
        if part in {"", ".", ".."}:
            continue
        clean = re.sub(r"[^A-Za-z0-9._~() -]", "_", part)
        clean_parts.append(clean or "unnamed")
    relative = Path(*clean_parts) if clean_parts else Path("index.html")
    if html and relative.suffix.lower() not in {".htm", ".html"}:
        relative = relative / "index.html"
    if html and relative.name.lower() == "index.html":
        relative = relative.with_name("index.html")
    return relative


def fetch(url: str, attempts: int = 3) -> tuple[bytes, str, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    context = ssl.create_default_context()
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=35, context=context) as response:
                return (
                    response.read(),
                    response.headers.get_content_type(),
                    response.geturl(),
                )
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    assert last_error is not None
    raise last_error


def decode_html(data: bytes) -> str:
    for encoding in ("utf-8", "windows-1252", "iso-8859-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def classify(url: str, content_type: str = "") -> str | None:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in HTML_EXTENSIONS or "html" in content_type:
        return "html"
    if suffix in ASSET_EXTENSIONS:
        return "asset"
    return None


def write_capture(
    url: str,
    data: bytes,
    content_type: str,
    final_url: str,
    kind: str,
    captured_at: str,
) -> dict[str, object]:
    host = urlparse(url).hostname or "unknown"
    relative = safe_relative_path(url, html=kind == "html")
    base = RAW if kind == "html" else MEDIA
    destination = base / host / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    return {
        "source_url": url,
        "final_url": final_url,
        "archive_path": destination.relative_to(ROOT).as_posix(),
        "kind": kind,
        "content_type": content_type or mimetypes.guess_type(destination.name)[0] or "application/octet-stream",
        "bytes": len(data),
        "sha256": digest,
        "captured_at": captured_at,
        "source": "live",
    }


def discover_references(html: str, base_url: str) -> Iterable[str]:
    parser = ReferenceParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    for reference in parser.references:
        canonical = canonical_url(reference, base_url)
        if canonical:
            yield canonical


def main() -> int:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    queue: deque[tuple[str, str]] = deque((seed, "html") for seed in SEEDS)
    queued = {seed for seed in SEEDS}
    entries: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []

    while queue:
        url, expected_kind = queue.popleft()
        try:
            data, content_type, final_url = fetch(url)
        except Exception as error:
            failures.append({"source_url": url, "error": str(error)})
            print(f"FAILED {url}: {error}")
            continue

        kind = classify(url, content_type) or expected_kind
        entry = write_capture(url, data, content_type, final_url, kind, captured_at)
        entries.append(entry)
        print(f"CAPTURED {kind:5} {entry['bytes']:>9} {url}")

        if kind != "html":
            continue

        html = decode_html(data)
        for reference in discover_references(html, url):
            reference_kind = classify(reference)
            if reference_kind is None or reference in queued:
                continue
            queued.add(reference)
            queue.append((reference, reference_kind))

    entries.sort(key=lambda item: str(item["source_url"]).lower())
    failures.sort(key=lambda item: item["source_url"].lower())
    payload = {
        "schema_version": 1,
        "captured_at": captured_at,
        "collections": list(HOSTS),
        "entries": entries,
        "failures": failures,
        "summary": {
            "html": sum(entry["kind"] == "html" for entry in entries),
            "assets": sum(entry["kind"] == "asset" for entry in entries),
            "bytes": sum(int(entry["bytes"]) for entry in entries),
            "failures": len(failures),
        },
    }
    MANIFEST.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    return 0 if entries else 1


if __name__ == "__main__":
    raise SystemExit(main())
