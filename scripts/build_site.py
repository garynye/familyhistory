#!/usr/bin/env python3
"""Render the modern static archive from captured Homestead pages."""

from __future__ import annotations

import html
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

from presentation_media import entry_is_excluded, load_exclusions


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DIST = ROOT / "dist"
ARCHIVE = ROOT / "archive"
MANIFEST_PATH = ARCHIVE / "manifest.json"
CONFIG_PATH = ROOT / "content" / "site.json"
HOST_LABELS = {
    "nojd.homestead.com": "The Nye Family",
    "karlaugust.homestead.com": "Swedish Documents",
    "mortensen.homestead.com": "Danish Documents",
}
COLLECTION_SLUGS = {
    "nojd.homestead.com": "nye-family",
    "karlaugust.homestead.com": "swedish-documents",
    "mortensen.homestead.com": "danish-documents",
}
SKIP_TEXT = {
    "home",
    "email me",
    "submit",
    "view entries",
    "sign in",
    "additional web sites",
}


@dataclass
class ImageReference:
    source: str
    alt: str = ""


@dataclass
class ParsedPage:
    source_url: str
    host: str
    source_path: str
    title: str
    text: list[str] = field(default_factory=list)
    images: list[ImageReference] = field(default_factory=list)
    source_image_count: int = 0
    updated: str = ""

    @property
    def slug(self) -> str:
        path = unquote(urlparse(self.source_url).path).strip("/")
        if not path:
            return "index"
        value = re.sub(r"\.(html?|HTML?)$", "", path)
        value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
        return value or "index"

    @property
    def route(self) -> str:
        filename = "home.html" if self.slug == "index" else f"{self.slug}.html"
        return f"collections/{COLLECTION_SLUGS[self.host]}/{filename}"


class ContentParser(HTMLParser):
    BLOCKS = {
        "address",
        "article",
        "blockquote",
        "br",
        "div",
        "figcaption",
        "h1",
        "h2",
        "h3",
        "h4",
        "li",
        "p",
        "section",
        "td",
        "tr",
    }

    def __init__(self, source_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source_url = source_url
        self.title_parts: list[str] = []
        self.fragments: list[str] = []
        self.images: list[ImageReference] = []
        self.ignored_depth = 0
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"script", "style", "noscript", "map"}:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if tag == "title":
            self.in_title = True
        if tag in self.BLOCKS:
            self.fragments.append("\n")
        if tag == "img" and values.get("src"):
            source = urljoin(self.source_url, values["src"] or "")
            host = (urlparse(source).hostname or "").lower()
            if host == (urlparse(self.source_url).hostname or "").lower():
                self.images.append(ImageReference(source=source.split("?", 1)[0], alt=(values.get("alt") or "").strip()))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "map"} and self.ignored_depth:
            self.ignored_depth -= 1
            return
        if self.ignored_depth:
            return
        if tag == "title":
            self.in_title = False
        if tag in self.BLOCKS:
            self.fragments.append("\n")

    def handle_data(self, data: str) -> None:
        if self.ignored_depth:
            return
        if self.in_title:
            self.title_parts.append(data)
        else:
            self.fragments.append(data)


def decode_source(data: bytes) -> str:
    for encoding in ("utf-8", "windows-1252", "iso-8859-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def normalize_text(raw: str) -> list[str]:
    lines = []
    for line in raw.splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if not cleaned or cleaned.lower() in SKIP_TEXT:
            continue
        if cleaned.startswith(("function ", "var ", "<!--")):
            continue
        if cleaned not in lines:
            lines.append(cleaned)
    return lines


def title_from_page(parser: ContentParser, text: list[str], source_url: str) -> str:
    raw_title = re.sub(r"\s+", " ", " ".join(parser.title_parts)).strip()
    generic = {"", "index", "untitled", "basic"}
    if raw_title.lower() not in generic:
        return raw_title
    for candidate in text[:8]:
        if 2 < len(candidate) < 100 and "updated on" not in candidate.lower():
            return candidate
    stem = Path(urlparse(source_url).path).stem
    return re.sub(r"[-_]+", " ", stem or "Home").title()


def load_pages(manifest: dict, exclusions: dict[str, dict]) -> list[ParsedPage]:
    captured_by_url = {
        str(entry["source_url"]).lower().rstrip("/"): entry
        for entry in manifest["entries"]
    }
    pages: list[ParsedPage] = []
    seen_source_pages: set[tuple[str, str]] = set()
    for entry in manifest["entries"]:
        if entry["kind"] != "html":
            continue
        source_url = str(entry["source_url"])
        source_host = urlparse(source_url).hostname or ""
        source_path_value = unquote(urlparse(source_url).path).strip("/")
        source_slug = re.sub(r"\.(html?|HTML?)$", "", source_path_value)
        source_slug = re.sub(r"[^A-Za-z0-9]+", "-", source_slug).strip("-").lower() or "index"
        source_key = (source_host, source_slug)
        if source_key in seen_source_pages:
            continue
        seen_source_pages.add(source_key)
        source_path = ROOT / str(entry["archive_path"])
        parser = ContentParser(source_url)
        parser.feed(decode_source(source_path.read_bytes()))
        text = normalize_text("".join(parser.fragments))
        images = []
        seen = set()
        for image in parser.images:
            key = image.source.lower().rstrip("/")
            asset = captured_by_url.get(key)
            if not asset or key in seen:
                continue
            seen.add(key)
            if entry_is_excluded(asset, exclusions):
                continue
            images.append(image)
        updated = next((line for line in text if "last updated" in line.lower()), "")
        pages.append(
            ParsedPage(
                source_url=source_url,
                host=source_host,
                source_path=str(entry["archive_path"]),
                title=title_from_page(parser, text, source_url),
                text=text,
                images=images,
                source_image_count=len(seen),
                updated=updated,
            )
        )
    pages.sort(key=lambda page: (list(HOST_LABELS).index(page.host), page.slug != "index", page.title.lower()))
    unique_pages: list[ParsedPage] = []
    seen_routes: set[tuple[str, str]] = set()
    for page in pages:
        key = (page.host, page.slug)
        if key in seen_routes:
            continue
        seen_routes.add(key)
        unique_pages.append(page)
    return unique_pages


def escape(value: str) -> str:
    return html.escape(value, quote=True)


def media_route(source_url: str, asset_lookup: dict[str, dict]) -> str | None:
    entry = asset_lookup.get(source_url.lower().rstrip("/"))
    if not entry:
        return None
    archive_path = ROOT / str(entry["archive_path"])
    relative = archive_path.relative_to(ARCHIVE / "media")
    return f"/media/{relative.as_posix()}"


def page_shell(title: str, description: str, body: str, *, root: str = "/") -> str:
    canonical = f"https://familyhistory.garynye.com{root}"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} · The Nye Family History</title>
  <meta name="description" content="{escape(description)}">
  <meta name="theme-color" content="#26382f">
  <link rel="canonical" href="{escape(canonical)}">
  <link rel="icon" href="/media/nojd.homestead.com/Picture_916.jpg">
  <link rel="stylesheet" href="/assets/site.css">
  <script src="/assets/site.js" defer></script>
</head>
<body>
  <a class="skip-link" href="#main">Skip to content</a>
  <header class="site-header">
    <a class="brand" href="/">
      <span class="brand-mark" aria-hidden="true">N</span>
      <span><strong>The Nye Family</strong><small>Sweden · Denmark · Michigan</small></span>
    </a>
    <button class="menu-button" type="button" aria-expanded="false" aria-controls="site-nav">Menu</button>
    <nav id="site-nav" class="site-nav" aria-label="Primary navigation">
      <a href="/#story">Our story</a>
      <a href="/collections/">Collections</a>
      <a href="/gallery/">Gallery</a>
      <button class="search-button" type="button" data-search-open>Search</button>
    </nav>
  </header>
  <main id="main">{body}</main>
  <footer class="site-footer">
    <div><strong>The Nye Family History</strong><p>Preserving a journey from Scandinavia to Michigan.</p></div>
    <div><a href="/about/">About this archive</a><a href="https://github.com/garynye/familyhistory">View the preservation repository</a></div>
  </footer>
  <dialog class="search-dialog" data-search-dialog>
    <form method="dialog"><button class="dialog-close" aria-label="Close search">Close</button></form>
    <label for="site-search">Search the archive</label>
    <input id="site-search" type="search" placeholder="Try a name, place, or document…" autocomplete="off">
    <div class="search-results" data-search-results><p>Begin typing to search names, places, documents, and captions.</p></div>
  </dialog>
  <dialog class="lightbox" data-lightbox>
    <form method="dialog"><button class="dialog-close" aria-label="Close image">Close</button></form>
    <img alt="">
    <p></p>
  </dialog>
</body>
</html>
"""


def render_archive_page(page: ParsedPage, assets: dict[str, dict]) -> str:
    meaningful_text = [
        line
        for line in page.text
        if line.lower() not in {page.title.lower(), HOST_LABELS[page.host].lower()}
        and not line.lower().startswith(("home aspelund", "home swedish", "home danish"))
    ]
    paragraphs = "\n".join(f"<p>{escape(line)}</p>" for line in meaningful_text)
    figures = []
    for index, image in enumerate(page.images):
        route = media_route(image.source, assets)
        if not route:
            continue
        caption = image.alt or f"Historical image from {page.title}"
        figures.append(
            f"""<figure class="gallery-item">
  <button type="button" data-lightbox-src="{escape(route)}" data-lightbox-caption="{escape(caption)}">
    <img src="{escape(route)}" alt="{escape(caption)}" loading="lazy">
  </button>
  <figcaption>{escape(caption)}</figcaption>
</figure>"""
        )
    gallery = f'<section class="page-gallery"><h2>Images and documents</h2><div class="gallery-grid">{"".join(figures)}</div></section>' if figures else ""
    if gallery:
        gallery_markup = f"  {gallery}"
    elif page.source_image_count:
        gallery_markup = ""
    else:
        gallery_markup = "  "
    body = f"""
<article class="archive-page">
  <header class="page-hero">
    <p class="eyebrow">{escape(HOST_LABELS[page.host])}</p>
    <h1>{escape(page.title)}</h1>
    <p class="provenance">Transcribed from the original Homestead page.</p>
  </header>
  <div class="article-layout">
    <div class="article-copy">{paragraphs or "<p>This preserved page primarily contains images or linked family records.</p>"}</div>
    <aside class="source-card">
      <span>Original source</span>
      <strong>{escape(page.host)}</strong>
      {f"<p>{escape(page.updated)}</p>" if page.updated else ""}
      <a href="{escape(page.source_url)}">Open original page</a>
      <a href="https://github.com/garynye/familyhistory/blob/main/{escape(page.source_path)}">Inspect captured HTML</a>
    </aside>
  </div>
{gallery_markup}
</article>
"""
    return page_shell(page.title, f"{page.title}, preserved from {page.host}.", body, root=f"/{page.route}")


def render_home(config: dict, pages: list[ParsedPage], assets: dict[str, dict]) -> str:
    featured_sources = (
        "https://nojd.homestead.com/files/wedding2.jpg",
        "https://nojd.homestead.com/files/nyefamily.jpg",
        "https://nojd.homestead.com/files/marriage.jpg",
    )
    featured = [media_route(source, assets) for source in featured_sources]
    featured = [source for source in featured if source]
    hero_image = featured[0] if featured else next(iter((media_route(image.source, assets) for page in pages for image in page.images)), "")
    story_image = featured[1] if len(featured) > 1 else hero_image
    collections = []
    for host, label in HOST_LABELS.items():
        count = sum(page.host == host for page in pages)
        cover = next(
            (
                media_route(image.source, assets)
                for page in pages
                if page.host == host
                for image in page.images
                if media_route(image.source, assets)
            ),
            "",
        )
        collections.append(
            f"""<a class="collection-card" href="/collections/{COLLECTION_SLUGS[host]}/">
  <div class="collection-image">{f'<img src="{escape(cover)}" alt="" loading="lazy">' if cover else ""}</div>
  <div><p class="eyebrow">{count} preserved pages</p><h3>{escape(label)}</h3><p>{escape(config["collection_notes"][host])}</p><span>Explore collection →</span></div>
</a>"""
        )
    body = f"""
<section class="home-hero">
  <div class="hero-copy">
    <p class="eyebrow">A family journey · 1864 onward</p>
    <h1>From Sweden and Denmark to a farm in Michigan</h1>
    <p class="hero-lede">{escape(config["intro"])}</p>
    <div class="hero-actions"><a class="button primary" href="#story">Read their story</a><button class="button text" type="button" data-search-open>Search the archive</button></div>
  </div>
  <figure class="hero-portrait">
    {f'<img src="{escape(hero_image)}" alt="Charles and Tena Nye on their wedding day">' if hero_image else ""}
    <figcaption><span>5 February 1894</span> Charles Nye and Tena Mortensen</figcaption>
  </figure>
  <div class="route-line" aria-hidden="true"><span>Örebro</span><i></i><span>Glud</span><i></i><span>Hessel</span></div>
</section>
<section id="story" class="story-section">
  <div class="section-heading"><p class="eyebrow">Charles &amp; Tena</p><h2>Two beginnings, one family</h2></div>
  <div class="story-grid">
    <article><span class="story-number">01</span><h3>Karl August Karlsson</h3><p>{escape(config["charles"])}</p><a href="/collections/swedish-documents/">Explore Charles’s Swedish roots →</a></article>
    <article><span class="story-number">02</span><h3>Dorthe Mortensen</h3><p>{escape(config["tena"])}</p><a href="/collections/danish-documents/">Explore Tena’s Danish roots →</a></article>
    <figure>{f'<img src="{escape(story_image)}" alt="The Nye family in Hessel, Michigan" loading="lazy">' if story_image else ""}<figcaption>The Nye family in Hessel, Michigan, circa 1910</figcaption></figure>
  </div>
</section>
<section class="collections-section">
  <div class="section-heading split"><div><p class="eyebrow">The preserved record</p><h2>Explore the collections</h2></div><p>Photographs, family documents, places, recollections, and genealogical records gathered across three original websites.</p></div>
  <div class="collection-grid">{"".join(collections)}</div>
</section>
<section class="family-tree-panel">
  <div>
    <p class="eyebrow">The ancestry of Ellen Augusta Nye</p>
    <h2>Follow the family tree through the generations.</h2>
    <p>The original Legacy Family Tree export remains available as browsable pages and as its source GEDCOM file.</p>
  </div>
  <div class="tree-actions">
    <a class="button primary" href="/collections/nye-family/files-index.html">Browse the family tree</a>
    <a class="button text" href="/media/nojd.homestead.com/files/annegedcom.ged" download>Download GEDCOM</a>
  </div>
</section>
<section class="preservation-callout">
  <p class="eyebrow">Built to endure</p>
  <h2>The story is preserved with its sources.</h2>
  <p>Every captured file is recorded with its original address, retrieval date, file size, and cryptographic checksum.</p>
  <a class="button pale" href="/about/">How this archive works</a>
</section>
"""
    return page_shell(config["title"], config["description"], body)


def render_collection_index(host: str, pages: list[ParsedPage], config: dict, assets: dict[str, dict]) -> str:
    host_pages = [page for page in pages if page.host == host]
    cards = []
    for page in host_pages:
        cover = next((media_route(image.source, assets) for image in page.images if media_route(image.source, assets)), "")
        excerpt = next((line for line in page.text if len(line) > 45 and "updated" not in line.lower()), "")
        cards.append(
            f"""<a class="page-card" href="/{page.route}">
  {f'<img src="{escape(cover)}" alt="" loading="lazy">' if cover else '<div class="page-card-placeholder"></div>'}
  <div><p class="eyebrow">{len(page.images)} images</p><h2>{escape(page.title)}</h2><p>{escape(excerpt[:180])}</p><span>View page →</span></div>
</a>"""
        )
    label = HOST_LABELS[host]
    body = f"""
<section class="collection-hero">
  <p class="eyebrow">Preserved collection</p>
  <h1>{escape(label)}</h1>
  <p>{escape(config["collection_notes"][host])}</p>
  <div class="collection-meta"><span>{len(host_pages)} pages</span><span>Source: {escape(host)}</span></div>
</section>
<section class="page-card-grid">{"".join(cards)}</section>
"""
    return page_shell(label, config["collection_notes"][host], body, root=f"/collections/{COLLECTION_SLUGS[host]}/")


def render_collections_index(config: dict, pages: list[ParsedPage], assets: dict[str, dict]) -> str:
    cards = []
    for host, label in HOST_LABELS.items():
        cover = next((media_route(image.source, assets) for page in pages if page.host == host for image in page.images if media_route(image.source, assets)), "")
        cards.append(
            f"""<a class="collection-card wide" href="/collections/{COLLECTION_SLUGS[host]}/">
  <div class="collection-image">{f'<img src="{escape(cover)}" alt="" loading="lazy">' if cover else ""}</div>
  <div><p class="eyebrow">{sum(page.host == host for page in pages)} pages</p><h2>{escape(label)}</h2><p>{escape(config["collection_notes"][host])}</p><span>Explore collection →</span></div>
</a>"""
        )
    body = f'<section class="collection-hero"><p class="eyebrow">The preserved record</p><h1>Collections</h1><p>Three connected family-history websites, gathered into one durable archive.</p></section><section class="collection-list">{"".join(cards)}</section>'
    return page_shell("Collections", "Browse the three preserved Homestead collections.", body, root="/collections/")


def render_gallery(pages: list[ParsedPage], assets: dict[str, dict]) -> str:
    figures = []
    seen = set()
    for page in pages:
        for image in page.images:
            route = media_route(image.source, assets)
            if not route or route in seen:
                continue
            seen.add(route)
            caption = image.alt or f"{page.title} · {HOST_LABELS[page.host]}"
            figures.append(
                f"""<figure class="gallery-item">
  <button type="button" data-lightbox-src="{escape(route)}" data-lightbox-caption="{escape(caption)}">
    <img src="{escape(route)}" alt="{escape(caption)}" loading="lazy">
  </button>
  <figcaption>{escape(caption)}</figcaption>
</figure>"""
            )
    body = f'<section class="collection-hero"><p class="eyebrow">Across the archive</p><h1>Gallery</h1><p>Family photographs, places, keepsakes, and historical documents from the three collections.</p></section><section class="gallery-grid gallery-all">{"".join(figures)}</section>'
    return page_shell("Gallery", "Browse photographs and documents from the Nye family archive.", body, root="/gallery/")


def render_about(manifest: dict) -> str:
    summary = manifest["summary"]
    captured = datetime.fromisoformat(manifest["captured_at"]).strftime("%-d %B %Y")
    body = f"""
<section class="collection-hero">
  <p class="eyebrow">Provenance and preservation</p>
  <h1>About this archive</h1>
  <p>This site preserves family-history material originally published across three Homestead websites.</p>
</section>
<section class="about-grid">
  <article><h2>What was captured</h2><p>{summary["html"]} HTML pages and {summary["assets"]} locally hosted media or document files were captured on {escape(captured)}.</p></article>
  <article><h2>How authenticity is recorded</h2><p>Every captured object has a source URL, capture timestamp, media type, byte count, and SHA-256 checksum in the preservation manifest.</p></article>
  <article><h2>What was not restored</h2><p>Obsolete trackers, guestbooks, email forms, weather widgets, and remote scripts are excluded from the modern site. Historical wording and source media remain unchanged.</p></article>
  <article><h2>Corrections and attribution</h2><p>Historical text is transcribed verbatim. Corrections should be recorded as editorial notes without replacing the original wording.</p></article>
</section>
<section class="download-panel"><div><p class="eyebrow">Preservation record</p><h2>Inspect the sources</h2><p>The public repository contains the original HTML captures, media, checksums, tooling, and site history.</p></div><a class="button primary" href="https://github.com/garynye/familyhistory">Open GitHub repository</a></section>
"""
    return page_shell("About this archive", "How the Nye family history archive was preserved.", body, root="/about/")


def write_file(relative: str, content: str) -> None:
    destination = SITE / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")


def prepare_site() -> None:
    SITE.mkdir(parents=True, exist_ok=True)
    for child in SITE.iterdir():
        if child.name == "assets":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def copy_static_and_media() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(SITE, DIST)
    shutil.copytree(ARCHIVE / "media", DIST / "media")
    shutil.copy2(MANIFEST_PATH, DIST / "archive-manifest.json")


def main() -> int:
    if not MANIFEST_PATH.exists():
        raise SystemExit("archive/manifest.json is missing; run archive_homestead.py first")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    exclusions = load_exclusions()
    pages = load_pages(manifest, exclusions)
    assets = {
        str(entry["source_url"]).lower().rstrip("/"): entry
        for entry in manifest["entries"]
        if entry["kind"] == "asset"
    }

    prepare_site()
    write_file("index.html", render_home(config, pages, assets))
    write_file("collections/index.html", render_collections_index(config, pages, assets))
    for host in HOST_LABELS:
        write_file(
            f"collections/{COLLECTION_SLUGS[host]}/index.html",
            render_collection_index(host, pages, config, assets),
        )
    for page in pages:
        write_file(page.route, render_archive_page(page, assets))
    write_file("gallery/index.html", render_gallery(pages, assets))
    write_file("about/index.html", render_about(manifest))

    search = [
        {
            "title": page.title,
            "url": f"/{page.route}",
            "collection": HOST_LABELS[page.host],
            "text": " ".join(page.text),
        }
        for page in pages
    ]
    write_file("search-index.json", json.dumps(search, ensure_ascii=False, separators=(",", ":")))

    routes = ["/", "/collections/", "/gallery/", "/about/"] + [f"/{page.route}" for page in pages]
    sitemap = "\n".join(f"  <url><loc>https://familyhistory.garynye.com{escape(route)}</loc></url>" for route in routes)
    write_file("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{sitemap}\n</urlset>\n')
    write_file("robots.txt", "User-agent: *\nAllow: /\nSitemap: https://familyhistory.garynye.com/sitemap.xml\n")
    write_file(".nojekyll", "")
    write_file(
        "404.html",
        page_shell(
            "Page not found",
            "The requested archive page could not be found.",
            '<section class="not-found"><p class="eyebrow">404</p><h1>This page has wandered from the trail.</h1><p>Try searching the archive or return to the family story.</p><div><a class="button primary" href="/">Return home</a><button class="button text" type="button" data-search-open>Search archive</button></div></section>',
            root="/404.html",
        ),
    )
    copy_static_and_media()
    print(f"Built {len(pages)} archive pages and {len(assets)} assets into {DIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
