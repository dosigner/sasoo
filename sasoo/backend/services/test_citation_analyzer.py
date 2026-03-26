import unittest

from services.citation_analyzer import parse_references


class CitationAnalyzerParsingTests(unittest.TestCase):
    def test_parse_references_handles_initial_based_author_prefix(self):
        refs = parse_references(
            """
1. R. K. Tyson, Introduction to Adaptive Optics, 2nd ed. (SPIE Press, Bellingham, 2000).
2. M. J. Booth, Adaptive optical microscopy: the ongoing quest for a perfect image, Light: Science & Applications 3, e165 (2014).
3. A. Roorda and D. R. Williams, "The arrangement of the three cone classes in the living human eye," Nature 397, 520-522 (1999).
            """.strip()
        )

        self.assertEqual(refs[0].authors, "R. K. Tyson")
        self.assertIn("Introduction to Adaptive Optics", refs[0].title)
        self.assertEqual(refs[1].authors, "M. J. Booth")
        self.assertIn("Adaptive optical microscopy", refs[1].title)

    def test_parse_references_handles_surname_first_author_lists(self):
        refs = parse_references(
            """
1. Ragazzoni, R., Marchetti, E. & Rigaut, F. Modal tomography for adaptive optics. Astron. Astrophys. 342, L53-L56 (1999).
2. Ragazzoni, R., Marchetti, E. & Valente, G. Adaptive-optics corrections available for the whole sky. Nature 403, 54-56 (2000).
3. Vincent Deo, et al, The CACAO real-time computer for adaptive optics: updates, performance, and development plans, Proc. SPIE 13097 (2024).
            """.strip()
        )

        self.assertIn("Ragazzoni", refs[0].authors)
        self.assertEqual(refs[0].title, "Modal tomography for adaptive optics")
        self.assertIn("Valente", refs[1].authors)
        self.assertIn("Adaptive-optics corrections available for the whole sky", refs[1].title)


if __name__ == "__main__":
    unittest.main()
