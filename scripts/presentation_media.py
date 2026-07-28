#!/usr/bin/env python3
"""Audit and classify archived images used by the modern presentation."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "archive"
MANIFEST_PATH = ARCHIVE / "manifest.json"
EXCLUSIONS_PATH = ROOT / "content" / "presentation-exclusions.json"

KNOWN_INTERFACE_FILES = {
    "airbrush.jpg": ("decoration", "Legacy Family Tree page separator"),
    "bluedash.gif": ("decoration", "Legacy Family Tree decorative dash"),
    "bluediam.gif": ("decoration", "Legacy Family Tree decorative bullet"),
    "bluepin1.gif": ("decoration", "Legacy Family Tree decorative pin"),
    "email.gif": ("contact", "Legacy Family Tree email button"),
    "next.jpg": ("navigation", "Legacy Family Tree next arrow"),
    "prev.jpg": ("navigation", "Legacy Family Tree previous arrow"),
    "tp.gif": ("spacer", "Homestead transparent spacer pixel"),
}
NAVIGATION_LABELS = {"back", "email", "forward", "home", "next", "previous"}


@dataclass(frozen=True)
class ImageEvidence:
    source_url: str
    page_url: str
    alt: str = ""
    title: str = ""
    href: str = ""
    width: str = ""
    height: str = ""


@dataclass
class Candidate:
    archive_path: str
    sha256: str
    source_url: str
    category: str
    reason: str
    referring_pages: set[str] = field(default_factory=set)

    def as_dict(self) -> dict:
        return {
            "archive_path": self.archive_path,
            "sha256": self.sha256,
            "source_url": self.source_url,
            "category": self.category,
            "reason": self.reason,
            "referring_pages": sorted(self.referring_pages),
        }


class ImageAuditParser(HTMLParser):
    """Collect image metadata and enclosing link context from source HTML."""

    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.images: list[ImageEvidence] = []
        self.href_stack: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"script", "style", "noscript", "map"}:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if tag == "a":
            self.href_stack.append(values.get("href") or "")
            return
        if tag != "img" or not values.get("src"):
            return
        source_url = urljoin(self.page_url, values["src"] or "").split("?", 1)[0]
        if (urlparse(source_url).hostname or "").lower() != (urlparse(self.page_url).hostname or "").lower():
            return
        self.images.append(
            ImageEvidence(
                source_url=source_url,
                page_url=self.page_url,
                alt=(values.get("alt") or "").strip(),
                title=(values.get("title") or "").strip(),
                href=self.href_stack[-1] if self.href_stack else "",
                width=(values.get("width") or "").strip(),
                height=(values.get("height") or "").strip(),
            )
        )

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "map"} and self.ignored_depth:
            self.ignored_depth -= 1
            return
        if self.ignored_depth:
            return
        if tag == "a" and self.href_stack:
            self.href_stack.pop()


def decode_source(data: bytes) -> str:
    for encoding in ("utf-8", "windows-1252", "iso-8859-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def normalize_key(value: str) -> str:
    return value.lower().rstrip("/")


def classify_evidence(evidence: ImageEvidence) -> tuple[str, str] | None:
    """Return a high-confidence interface category and reason."""

    basename = Path(unquote(urlparse(evidence.source_url).path)).name.lower()
    if basename in KNOWN_INTERFACE_FILES:
        return KNOWN_INTERFACE_FILES[basename]

    try:
        width = int(evidence.width)
        height = int(evidence.height)
    except ValueError:
        width = height = 0
    if width == 1 and height == 1:
        return ("tracking", "One-pixel tracking or spacer image")

    labels = {
        re.sub(r"\s+", " ", value).strip().lower()
        for value in (evidence.alt, evidence.title)
        if value.strip()
    }
    if labels & NAVIGATION_LABELS and evidence.href:
        label = sorted(labels & NAVIGATION_LABELS)[0]
        category = "contact" if label == "email" else "navigation"
        return (category, f"Linked legacy {label} control")

    href_path = unquote(urlparse(urljoin(evidence.page_url, evidence.href)).path).lower()
    source_path = unquote(urlparse(evidence.source_url).path).lower()
    if (
        evidence.href
        and "/publishimages/" in source_path
        and Path(href_path).name in {"", "index.htm", "index.html", "index.asp"}
    ):
        return ("navigation", "Homestead-generated image linked to a collection home page")

    return None


def load_exclusions(path: Path = EXCLUSIONS_PATH) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("entries"), list):
        raise ValueError(f"invalid presentation exclusion manifest: {path}")
    return {
        str(entry["archive_path"]): entry
        for entry in data["entries"]
    }


def validate_exclusions(manifest: dict, exclusions: dict[str, dict]) -> list[str]:
    assets = {
        str(entry["archive_path"]): entry
        for entry in manifest["entries"]
        if entry["kind"] == "asset"
    }
    errors: list[str] = []
    for archive_path, exclusion in exclusions.items():
        asset = assets.get(archive_path)
        if not asset:
            errors.append(f"excluded media is not an archived asset: {archive_path}")
            continue
        if asset["sha256"] != exclusion.get("sha256"):
            errors.append(f"excluded media checksum changed: {archive_path}")
        if not exclusion.get("category") or not exclusion.get("reason"):
            errors.append(f"excluded media lacks category or reason: {archive_path}")
    return errors


def entry_is_excluded(entry: dict, exclusions: dict[str, dict]) -> bool:
    exclusion = exclusions.get(str(entry["archive_path"]))
    return bool(exclusion and exclusion.get("sha256") == entry.get("sha256"))


def audit_candidates(manifest: dict) -> list[Candidate]:
    entries_by_url = {
        normalize_key(str(entry["source_url"])): entry
        for entry in manifest["entries"]
    }
    candidates: dict[str, Candidate] = {}
    for page_entry in manifest["entries"]:
        if page_entry["kind"] != "html":
            continue
        page_url = str(page_entry["source_url"])
        parser = ImageAuditParser(page_url)
        parser.feed(decode_source((ROOT / str(page_entry["archive_path"])).read_bytes()))
        for evidence in parser.images:
            classification = classify_evidence(evidence)
            asset = entries_by_url.get(normalize_key(evidence.source_url))
            if not classification or not asset or asset["kind"] != "asset":
                continue
            archive_path = str(asset["archive_path"])
            category, reason = classification
            candidate = candidates.setdefault(
                archive_path,
                Candidate(
                    archive_path=archive_path,
                    sha256=str(asset["sha256"]),
                    source_url=str(asset["source_url"]),
                    category=category,
                    reason=reason,
                ),
            )
            candidate.referring_pages.add(evidence.page_url)

    assets_by_sha: dict[str, list[dict]] = {}
    for entry in manifest["entries"]:
        if entry["kind"] == "asset" and str(entry.get("content_type", "")).startswith("image/"):
            assets_by_sha.setdefault(str(entry["sha256"]), []).append(entry)
    for candidate in list(candidates.values()):
        for duplicate in assets_by_sha.get(candidate.sha256, []):
            archive_path = str(duplicate["archive_path"])
            candidates.setdefault(
                archive_path,
                Candidate(
                    archive_path=archive_path,
                    sha256=str(duplicate["sha256"]),
                    source_url=str(duplicate["source_url"]),
                    category=candidate.category,
                    reason=f"Duplicate of confirmed interface asset: {candidate.reason}",
                ),
            )
    return sorted(candidates.values(), key=lambda candidate: candidate.archive_path.lower())


def unreviewed_candidates(manifest: dict, exclusions: dict[str, dict]) -> list[Candidate]:
    return [
        candidate
        for candidate in audit_candidates(manifest)
        if candidate.archive_path not in exclusions
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print candidates as JSON")
    parser.add_argument("--check", action="store_true", help="fail for invalid or unreviewed candidates")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    exclusions = load_exclusions()
    candidates = audit_candidates(manifest)
    errors = validate_exclusions(manifest, exclusions)
    unreviewed = [
        candidate
        for candidate in candidates
        if candidate.archive_path not in exclusions
    ]

    if args.json:
        print(json.dumps([candidate.as_dict() for candidate in candidates], indent=2))
    else:
        for candidate in candidates:
            status = "excluded" if candidate.archive_path in exclusions else "REVIEW"
            print(f"{status:8} {candidate.category:10} {candidate.archive_path} — {candidate.reason}")
        print(f"{len(candidates)} candidate(s); {len(unreviewed)} require review.")

    if args.check and (errors or unreviewed):
        for error in errors:
            print(f"ERROR: {error}")
        for candidate in unreviewed:
            print(f"ERROR: unreviewed presentation-media candidate: {candidate.archive_path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
