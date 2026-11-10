import unittest

from services.chat_context import build_reading_context


class ReadingContextTests(unittest.TestCase):
    def test_long_introduction_keeps_conclusion_and_section_list(self):
        document = {"sections": {
            "abstract": "Abstract evidence " * 400,
            "introduction": "Introduction evidence " * 1000,
            "method": "Method not needed for this overview",
            "conclusion": "CONCLUSION EVIDENCE",
        }}
        text, truncated = build_reading_context(document)
        self.assertIn("CONCLUSION EVIDENCE", text)
        self.assertIn("abstract, introduction, method, conclusion", text)
        self.assertNotIn("Method not needed", text)
        self.assertLess(len(text), 7200)
        self.assertTrue(truncated)
        self.assertEqual(build_reading_context(document), (text, truncated))

    def test_missing_sections_are_reported_without_fabrication(self):
        text, truncated = build_reading_context({"sections": {"abstract": "Only an abstract"}})
        self.assertIn("발췌하지 못한 절: introduction, conclusion", text)
        self.assertNotIn("=== CONCLUSION ===", text)
        self.assertFalse(truncated)

    def test_unstructured_text_is_labelled_as_a_prefix(self):
        text, truncated = build_reading_context({"sections": {"full_text": "raw text " * 2000}})
        self.assertIn("절 구분을 확인하지 못해", text)
        self.assertNotIn("=== ABSTRACT ===", text)
        self.assertLess(len(text), 6500)
        self.assertTrue(truncated)

    def test_empty_document_has_no_source(self):
        self.assertEqual(build_reading_context({}), ("", False))

    def test_detected_non_overview_sections_are_not_called_detection_failure(self):
        text, _ = build_reading_context({"sections": {"method": "Method only", "results": "Results only"}, "full_text": "original source"})
        self.assertIn("감지한 절 목록: method, results", text)
        self.assertIn("발췌하지 못해", text)
        self.assertNotIn("절 구분을 확인하지 못해", text)
