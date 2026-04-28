"""
Destitch service tests.

Runs against real stitched composites on the developer's machine. Skipped
automatically if fixture paths are not present (so CI elsewhere doesn't break).

Run from /server:
    python -m pytest test_destitch.py -v
"""

import base64
import os
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.destitch_service import destitch_service  # noqa: E402

FIXTURES_DIR_SIPPAR = Path(r"C:/Users/wende/Downloads/Sippar/Sippar Selection/_Final_JPG")
FIXTURES_DIR_DOWNLOADS = Path(r"C:/Users/wende/Downloads/destitch")


def _load_b64(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


class DestitchSplitTests(unittest.TestCase):
    """Each fixture asserts on the set of view codes we expect. Codes match
    what the prototype produced after the _05r/_06r drop rule."""

    CASES = [
        (FIXTURES_DIR_SIPPAR / "Si.1.jpg",
         {"_01", "_02", "_03", "_04", "_05", "_06"}),
        (FIXTURES_DIR_SIPPAR / "Si.18.jpg",
         {"_01", "_02", "_04", "_05", "_06", "_ot"}),
        (FIXTURES_DIR_SIPPAR / "Si.56.jpg",
         {"_01", "_02", "_03", "_04", "_05", "_06"}),  # + _or, _rl (checked separately)
        (FIXTURES_DIR_DOWNLOADS / "eBL-BM.45776.jpeg",
         {"_01", "_02", "_03", "_04", "_05", "_06"}),
        (FIXTURES_DIR_DOWNLOADS / "eBL-U.31357.jpeg",
         {"_01", "_02", "_03", "_04", "_05", "_06"}),
    ]

    def _assert_codes(self, path: Path, required_codes: set):
        if not path.exists():
            self.skipTest(f"fixture not available: {path}")
        result = destitch_service.split(_load_b64(path))
        self.assertIsNone(result.error, f"unexpected error: {result.error}")
        codes = {v.code for v in result.views}
        missing = required_codes - codes
        self.assertFalse(missing, f"missing view codes {missing} in {path.name}; got {codes}")
        # No _05r / _06r duplicates should ever be returned.
        self.assertNotIn("_05r", codes)
        self.assertNotIn("_06r", codes)

    def test_si1(self):
        self._assert_codes(*self.CASES[0])

    def test_si18(self):
        self._assert_codes(*self.CASES[1])

    def test_si56_main_views_plus_intermediates(self):
        path, required = self.CASES[2]
        if not path.exists():
            self.skipTest(f"fixture not available: {path}")
        result = destitch_service.split(_load_b64(path))
        codes = {v.code for v in result.views}
        self.assertTrue(required.issubset(codes))
        # Si.56 has extra intermediate shots — we at least expect obverse-right
        # and reverse-left intermediates to be detected.
        self.assertTrue(any(c.startswith("_or") for c in codes),
                        f"expected _or* in {codes}")
        self.assertTrue(any(c.startswith("_rl") for c in codes),
                        f"expected _rl* in {codes}")

    def test_bm45776(self):
        self._assert_codes(*self.CASES[3])

    def test_u31357(self):
        self._assert_codes(*self.CASES[4])

    def test_origin_equals_bbox_topleft(self):
        path = self.CASES[0][0]
        if not path.exists():
            self.skipTest(f"fixture not available: {path}")
        result = destitch_service.split(_load_b64(path))
        for view in result.views:
            self.assertEqual(view.origin.x, view.bbox.x)
            self.assertEqual(view.origin.y, view.bbox.y)

    def test_include_crops_emits_base64(self):
        path = self.CASES[0][0]
        if not path.exists():
            self.skipTest(f"fixture not available: {path}")
        result = destitch_service.split(_load_b64(path), include_crops=True)
        for view in result.views:
            self.assertIsNotNone(view.crop_base64)
            self.assertGreater(len(view.crop_base64), 100)
            self.assertIsNone(view.mask_base64)

    def test_include_masks_emits_base64(self):
        path = self.CASES[0][0]
        if not path.exists():
            self.skipTest(f"fixture not available: {path}")
        result = destitch_service.split(_load_b64(path), include_masks=True)
        for view in result.views:
            self.assertIsNotNone(view.mask_base64)
            self.assertGreater(len(view.mask_base64), 100)


class DestitchClassifyTests(unittest.TestCase):

    def test_si1_is_composite(self):
        path = FIXTURES_DIR_SIPPAR / "Si.1.jpg"
        if not path.exists():
            self.skipTest(f"fixture not available: {path}")
        c = destitch_service.classify(_load_b64(path))
        self.assertTrue(c.is_composite)
        self.assertGreaterEqual(c.view_count, 6)
        self.assertGreaterEqual(c.confidence, 0.5)

    def test_u31357_is_composite(self):
        path = FIXTURES_DIR_DOWNLOADS / "eBL-U.31357.jpeg"
        if not path.exists():
            self.skipTest(f"fixture not available: {path}")
        c = destitch_service.classify(_load_b64(path))
        self.assertTrue(c.is_composite)


if __name__ == "__main__":
    unittest.main(verbosity=2)
