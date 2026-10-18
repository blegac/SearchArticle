"""
Unit tests for searcharticle.downloaders ("already downloaded" branch).

Check that when a PDF already exists in the output folder,
``download_article`` still records it in ``manifest.json``
so the link_zotero companion script can link it to Zotero.

Run with:  python -m unittest discover -s tests
(from the project root)
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

# Make src/searcharticle importable without installation.
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "src")
)

from searcharticle.downloaders import download_article  # noqa: E402


class TestAlreadyDownloadedManifest(unittest.TestCase):
    """The "⏭ Already downloaded" branch feeds the manifest."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_article(self, **kw):
        article = {
            "title": "Smith_et_al_2021",
            "full_title": "A test article",
            "doi": "10.1234/test.2021",
            "pmid": None,
        }
        article.update(kw)
        return article

    def _state(self):
        return SimpleNamespace(output_folder=str(self.out))

    def test_skip_records_manifest(self):
        # The PDF already exists (previous batch, before the manifest feature).
        (self.out / "Smith_et_al_2021.pdf").write_bytes(b"%PDF-1.4 factice")

        ok = download_article(
            self._make_article(), self._state(), log_cb=lambda m, s: None
        )
        self.assertTrue(ok)

        manifest = json.loads(
            (self.out / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertIn("10.1234/test.2021", manifest)
        self.assertEqual(
            manifest["10.1234/test.2021"]["file_path"], "Smith_et_al_2021.pdf"
        )

    def test_skip_without_doi_breaks_nothing(self):
        # Article with PMID only: the skip happens, but without a DOI there
        # is nothing to record in the manifest (and no error).
        (self.out / "SansDoi_2020.pdf").write_bytes(b"%PDF-1.4 factice")

        ok = download_article(
            self._make_article(title="SansDoi_2020", doi=None, pmid="12345678"),
            self._state(),
            log_cb=lambda m, s: None,
        )
        self.assertTrue(ok)
        # No DOI → nothing to record, but no error either.
        self.assertFalse((self.out / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
