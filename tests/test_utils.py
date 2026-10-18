"""
Unit tests for searcharticle.utils.

Run with:  python -m unittest discover -s tests
(from the project root)
"""

import os
import sys
import unittest

# Make src/searcharticle importable without installation.
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "src")
)

from searcharticle.utils import (  # noqa: E402
    assign_unique_names,
    detect_type,
    is_pdf,
    format_filename,
    sanitize_filename,
)


class TestSanitizeFilename(unittest.TestCase):
    def test_forbidden_chars_replaced(self):
        self.assertEqual(sanitize_filename('a<b>c:d"e/f\\g|h?i*j'), "a_b_c_d_e_f_g_h_i_j")

    def test_spaces_become_underscores(self):
        self.assertEqual(sanitize_filename("Neural correlates of consciousness"), "Neural_correlates_of_consciousness")

    def test_150_char_limit(self):
        self.assertLessEqual(len(sanitize_filename("x" * 300)), 150)

    def test_simple_name_unchanged(self):
        self.assertEqual(sanitize_filename("Smith_2021"), "Smith_2021")


class TestIsPdf(unittest.TestCase):
    def test_real_pdf(self):
        self.assertTrue(is_pdf(b"%PDF-1.7" + b"x" * 6000))

    def test_too_small(self):
        self.assertFalse(is_pdf(b"%PDF" + b"x" * 100))

    def test_not_a_pdf(self):
        self.assertFalse(is_pdf(b"<html>" + b"x" * 6000))

    def test_custom_threshold(self):
        data = b"%PDF" + b"x" * 12000
        self.assertTrue(is_pdf(data, min_size=10000))
        self.assertFalse(is_pdf(data, min_size=20000))


class TestFormatFilename(unittest.TestCase):
    def test_author_and_year(self):
        self.assertEqual(format_filename("Smith", "2021", "fb"), "Smith_et_al_2021")

    def test_author_without_year(self):
        self.assertEqual(format_filename("Smith", "", "fb"), "Smith_et_al")

    def test_year_without_author(self):
        self.assertEqual(format_filename("", "2021", "fb"), "Unknown_et_al_2021")

    def test_fallback(self):
        self.assertEqual(format_filename("", "", "10.1234_abc"), "10.1234_abc")


class TestDetectType(unittest.TestCase):
    def test_bare_doi(self):
        self.assertEqual(detect_type("10.1016/j.cell.2020.01.001"), ("doi", "10.1016/j.cell.2020.01.001"))

    def test_prefixed_doi(self):
        self.assertEqual(detect_type("doi:10.1038/s41586-021-03819-2"), ("doi", "10.1038/s41586-021-03819-2"))

    def test_uppercase_prefixed_doi(self):
        self.assertEqual(detect_type("DOI:10.1000/xyz"), ("doi", "10.1000/xyz"))

    def test_bare_pmid(self):
        self.assertEqual(detect_type("32589966"), ("pmid", "32589966"))

    def test_prefixed_pmid(self):
        self.assertEqual(detect_type("pmid:32589966"), ("pmid", "32589966"))

    def test_unknown(self):
        t, v = detect_type("some random nonsense")
        self.assertEqual(t, "unknown")
        self.assertEqual(v, "some random nonsense")

    def test_spaces_trimmed(self):
        self.assertEqual(detect_type("  10.1000/xyz  "), ("doi", "10.1000/xyz"))


class TestAssignUniqueNames(unittest.TestCase):
    def _make_article(self, title, doi=None, full_title=""):
        return {"title": title, "doi": doi, "full_title": full_title}

    def test_no_collision(self):
        articles = [self._make_article("Smith_et_al_2021"), self._make_article("Dupont_et_al_2020")]
        self.assertEqual(assign_unique_names(articles), 0)
        self.assertEqual([a["title"] for a in articles],
                         ["Smith_et_al_2021", "Dupont_et_al_2020"])

    def test_collision_abc_suffixes(self):
        articles = [
            self._make_article("Smith_et_al_2021", "10.1000/b"),
            self._make_article("Smith_et_al_2021", "10.1000/a"),
            self._make_article("Smith_et_al_2021", "10.1000/c"),
        ]
        self.assertEqual(assign_unique_names(articles), 3)
        # Stable order by DOI, independent of arrival order
        self.assertEqual([a["title"] for a in articles],
                         ["Smith_et_al_2021b", "Smith_et_al_2021a",
                          "Smith_et_al_2021c"])

    def test_stable_regardless_of_order(self):
        def names(order):
            articles = [self._make_article("X_2020", doi=d) for d in order]
            assign_unique_names(articles)
            return sorted(a["title"] for a in articles)

        self.assertEqual(names(["10.2/b", "10.1/a"]), names(["10.1/a", "10.2/b"]))

    def test_mixed(self):
        articles = [
            self._make_article("Smith_et_al_2021", "10.1/a"),
            self._make_article("Dupont_et_al_2020"),
            self._make_article("Smith_et_al_2021", "10.1/b"),
        ]
        assign_unique_names(articles)
        self.assertEqual(articles[0]["title"], "Smith_et_al_2021a")
        self.assertEqual(articles[1]["title"], "Dupont_et_al_2020")
        self.assertEqual(articles[2]["title"], "Smith_et_al_2021b")


if __name__ == "__main__":
    unittest.main()
