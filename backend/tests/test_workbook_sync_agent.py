"""Offline tests for coaching-workbook catalog + learn crystals."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.workbook_catalog import (  # noqa: E402
    COACHING_STANCE,
    coaching_system_block,
    iter_workbook_files,
)
from app.services.workbook_sync_agent import (  # noqa: E402
    build_learn_crystals,
    file_sha256,
    should_full_learn,
)


class TestWorkbookLearn(unittest.TestCase):
    def test_stance_is_coaching_not_therapy(self):
        self.assertIn("not therapy", COACHING_STANCE.lower())
        block = coaching_system_block(max_files=2)
        self.assertIn("not therapy", block.lower())

    def test_build_learn_crystals_catalog_and_impl(self):
        text = (
            "Empty chair work helps a person speak to unfinished business.\n\n"
            "Thematic maps organize polarities the client can notice and choose "
            "whether to explore as a coaching exercise."
        )
        crystals = build_learn_crystals("Gestalts Steps.pdf", text, full=True)
        self.assertGreaterEqual(len(crystals), 2)
        self.assertTrue(crystals[0].startswith("[COACHING WORKBOOK:"))
        joined = "\n".join(crystals)
        self.assertIn("not therapy", joined.lower())
        self.assertIn("Gestalts Steps.pdf", joined)

    def test_large_file_is_catalog_only(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(b"x" * 100)
            path = Path(tmp.name)
        try:
            ok, reason = should_full_learn(path)
            self.assertTrue(ok)
            bible = path.with_name("new-king-james-version-en.pdf")
            path.rename(bible)
            ok, reason = should_full_learn(bible)
            self.assertFalse(ok)
            self.assertIn("catalog_only", reason)
            bible.unlink(missing_ok=True)
        finally:
            if path.exists():
                path.unlink(missing_ok=True)

    def test_sha_stable(self):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"workbook-bytes")
            path = Path(tmp.name)
        try:
            self.assertEqual(file_sha256(path), file_sha256(path))
        finally:
            path.unlink(missing_ok=True)

    def test_iter_skips_missing_roots(self):
        files = iter_workbook_files([Path("/no/such/workbooks-root-xyz")])
        self.assertEqual(files, [])


if __name__ == "__main__":
    unittest.main()
