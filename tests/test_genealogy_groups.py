from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_site import MANIFEST_PATH, load_pages, render_genealogy_hub  # noqa: E402
from genealogy_groups import GENEALOGY_GROUPS, is_collection_visible  # noqa: E402
from presentation_media import load_exclusions  # noqa: E402


class GenealogyGroupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.pages = load_pages(manifest, load_exclusions())
        cls.pages_by_key = {
            (page.host, page.slug): page
            for page in cls.pages
        }

    def test_every_configured_page_exists(self) -> None:
        for group in GENEALOGY_GROUPS:
            configured_slugs = {group.hub_slug, *group.child_slugs}
            for slug in configured_slugs:
                self.assertIn((group.host, slug), self.pages_by_key)

    def test_group_page_titles_are_distinct(self) -> None:
        for group in GENEALOGY_GROUPS:
            titles = list(group.page_titles.values())
            self.assertEqual(len(titles), len(set(titles)))

    def test_only_intended_group_cards_are_top_level(self) -> None:
        for group in GENEALOGY_GROUPS:
            configured_slugs = {group.hub_slug, *group.child_slugs}
            visible = {
                slug
                for slug in configured_slugs
                if is_collection_visible(group.host, slug)
            }
            expected = {group.hub_slug, *group.top_level_report_slugs}
            self.assertEqual(visible, expected)

    def test_preserved_surname_stats_match_hub(self) -> None:
        for group in GENEALOGY_GROUPS:
            surname_page = self.pages_by_key[(group.host, group.surname_page.slug)]
            text = " ".join(surname_page.text)
            self.assertIn(
                f"This site contains {group.people} individuals and {group.surnames} unique surnames",
                text,
            )

    def test_hub_links_to_every_group_page(self) -> None:
        for group in GENEALOGY_GROUPS:
            hub_page = self.pages_by_key[(group.host, group.hub_slug)]
            rendered = render_genealogy_hub(group, hub_page, self.pages)
            for slug in group.child_slugs:
                child = self.pages_by_key[(group.host, slug)]
                self.assertIn(f'href="/{child.route}"', rendered)


if __name__ == "__main__":
    unittest.main()
