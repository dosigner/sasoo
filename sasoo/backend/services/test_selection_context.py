import tempfile
import unittest
from pathlib import Path

import fitz

from services.selection_context import build_selection_context, match_selection, validate_selection


def selection(text, page=1, end_page=None):
    return {"text": text, "page": page, "end_page": end_page or page}


class SelectionContextTests(unittest.TestCase):
    def test_whitespace_and_hyphenation_preserve_original_symbols(self):
        source = "Definition: E = α² + β.\n\nThe proba-\nbility distribution is normalized.\nThe value x − y remains unchanged."
        result = match_selection([source], selection("The probability distribution is normalized."))
        self.assertEqual(result["status"], "matched")
        self.assertIn("proba-\nbility", result["excerpt"])
        self.assertIn("x − y", result["excerpt"])
        self.assertEqual(source[result["match_start"]:result["match_end"]], "The proba-\nbility distribution is normalized.")

    def test_duplicate_on_same_page_is_unverified(self):
        result = match_selection(["Repeated sentence.\n\nWrong neighborhood. Repeated sentence."], selection("Repeated sentence."))
        self.assertEqual(result["status"], "unverified")
        self.assertNotIn("excerpt", result)

    def test_no_fuzzy_match_or_symbol_replacement(self):
        for text in ("Entirely missing text", "x + y = z", "a"):
            self.assertNotIn("excerpt", match_selection(["x − y = z"], selection(text)))

    def test_cross_page_match_must_span_both_pages(self):
        result = match_selection(["Prior context. Selected across", "pages with E = mc². Next context."], selection("Selected across pages with E = mc².", 3, 4))
        self.assertEqual(result["status"], "matched")
        self.assertIn("Prior context", result["excerpt"])
        self.assertNotIn("excerpt", match_selection(["Only first page sentence.", "Different page"], selection("Only first page sentence.", 3, 4)))

    def test_long_paragraph_is_bounded_and_raw(self):
        source = "a" * 10000 + " unique selection α=β " + "z" * 10000
        result = match_selection([source], selection("unique selection α=β"))
        self.assertLessEqual(len(result["excerpt"]), 1640)
        self.assertTrue(result["partial_before"])
        self.assertTrue(result["partial_after"])

    def test_real_pdf_pages_disambiguate_repeated_sentence(self):
        with tempfile.TemporaryDirectory() as folder:
            with fitz.open() as doc:
                for context in ("Wrong page context.", "Correct page context."):
                    page = doc.new_page()
                    page.insert_text((60, 80), context + "\nRepeated sentence.")
                doc.save(Path(folder) / "paper.pdf")
            result = build_selection_context(Path(folder), selection("Repeated sentence.", 2))
            self.assertEqual(result["status"], "matched")
            self.assertIn("Correct page", result["excerpt"])
            self.assertNotIn("Wrong page", result["excerpt"])
            for page, end in ((3, 3), (1, 4)):
                self.assertNotIn("excerpt", build_selection_context(Path(folder), selection("Repeated sentence.", page, end)))

    def test_invalid_payload(self):
        for value in ([], {}, selection("x" * 2001), selection("valid text", 0), selection("valid text", True), selection("valid text", 3, 2)):
            with self.assertRaises(ValueError):
                validate_selection(value)

    def test_line_hyphens_are_not_algebraic_minus_signs(self):
        self.assertEqual(match_selection(["The proba-\nbility is high."], selection("The proba- bility is high."))["status"], "matched")
        self.assertEqual(match_selection(["xy- zw = a"], selection("xyzw = a"))["status"], "unverified")
        self.assertEqual(match_selection(["xyzw = a"], selection("xy- zw = a"))["status"], "unverified")
