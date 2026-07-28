from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from presentation_media import (  # noqa: E402
    EXCLUSIONS_PATH,
    MANIFEST_PATH,
    ImageEvidence,
    classify_evidence,
    load_exclusions,
    unreviewed_candidates,
    validate_exclusions,
)


class PresentationMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.exclusions = load_exclusions(EXCLUSIONS_PATH)

    def test_known_navigation_arrow_is_classified(self) -> None:
        evidence = ImageEvidence(
            source_url="https://example.com/files/next.jpg",
            page_url="https://example.com/files/a1.htm",
            alt="next",
            href="a2.htm#g2",
        )
        self.assertEqual(
            classify_evidence(evidence),
            ("navigation", "Legacy Family Tree next arrow"),
        )

    def test_generic_picture_alt_is_not_classified(self) -> None:
        evidence = ImageEvidence(
            source_url="https://example.com/files/ellen.jpg",
            page_url="https://example.com/ellen.htm",
            alt="picture",
        )
        self.assertIsNone(classify_evidence(evidence))

    def test_exclusion_manifest_matches_archive(self) -> None:
        self.assertEqual(validate_exclusions(self.manifest, self.exclusions), [])

    def test_all_high_confidence_candidates_are_reviewed(self) -> None:
        self.assertEqual(unreviewed_candidates(self.manifest, self.exclusions), [])


if __name__ == "__main__":
    unittest.main()
