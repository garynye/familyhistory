#!/usr/bin/env python3
"""Validate archive integrity and generated static-site references."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

from presentation_media import (
    entry_is_excluded,
    load_exclusions,
    unreviewed_candidates,
    validate_exclusions,
)


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
MANIFEST_PATH = ROOT / "archive" / "manifest.json"


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        for key in ("href", "src"):
            if values.get(key):
                self.references.append(values[key] or "")
        if values.get("data-lightbox-src"):
            self.references.append(values["data-lightbox-src"] or "")


def local_target(reference: str, page: Path) -> Path | None:
    if not reference or reference.startswith(("#", "mailto:", "tel:", "data:")):
        return None
    parsed = urlparse(reference)
    if parsed.scheme or parsed.netloc:
        return None
    path = unquote(parsed.path)
    if path.startswith("/"):
        target = DIST / path.lstrip("/")
    else:
        target = page.parent / path
    if path.endswith("/") or (not target.suffix and not target.exists()):
        target = target / "index.html"
    return target


def main() -> int:
    errors: list[str] = []
    if not DIST.exists():
        errors.append("dist directory is missing")
    if not MANIFEST_PATH.exists():
        errors.append("archive manifest is missing")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    exclusions = load_exclusions()
    errors.extend(validate_exclusions(manifest, exclusions))
    excluded_routes = {
        f"/media/{Path(entry['archive_path']).relative_to('archive/media').as_posix()}"
        for entry in manifest["entries"]
        if entry["kind"] == "asset" and entry_is_excluded(entry, exclusions)
    }
    for candidate in unreviewed_candidates(manifest, exclusions):
        errors.append(f"unreviewed presentation-media candidate: {candidate.archive_path}")

    for entry in manifest["entries"]:
        path = ROOT / entry["archive_path"]
        if not path.exists():
            errors.append(f"missing archive file: {path}")
            continue
        data = path.read_bytes()
        if len(data) != entry["bytes"]:
            errors.append(f"size mismatch: {path}")
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            errors.append(f"checksum mismatch: {path}")

    html_files = sorted(DIST.rglob("*.html"))
    for page in html_files:
        source = page.read_text(encoding="utf-8")
        parser = LinkParser()
        parser.feed(source)
        for reference in parser.references:
            if urlparse(reference).path in excluded_routes:
                errors.append(
                    f"excluded presentation media in {page.relative_to(DIST)}: {reference}"
                )
            target = local_target(reference, page)
            if target is not None and not target.exists():
                errors.append(f"broken reference in {page.relative_to(DIST)}: {reference}")
        if "<title>" not in source or "<h1>" not in source:
            errors.append(f"missing title or h1: {page.relative_to(DIST)}")
        if re.search(r"<script[^>]+src=[\"']http:", source, flags=re.I):
            errors.append(f"mixed-content script: {page.relative_to(DIST)}")

    search_path = DIST / "search-index.json"
    try:
        search = json.loads(search_path.read_text(encoding="utf-8"))
        if not search or any(not item.get("title") or not item.get("url") for item in search):
            errors.append("search index is empty or malformed")
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"invalid search index: {error}")

    if manifest["failures"]:
        print(f"NOTICE: {len(manifest['failures'])} source URLs could not be captured.")
        for failure in manifest["failures"][:20]:
            print(f"  {failure['source_url']}: {failure['error']}")

    if errors:
        print(f"Validation failed with {len(errors)} error(s):", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(
        f"Validated {len(html_files)} HTML pages, "
        f"{len(manifest['entries'])} archived objects, and {len(search)} search records."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
