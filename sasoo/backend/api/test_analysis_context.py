import unittest

from api.analysis_context import build_chain_system_instruction, EXPLANATION_LEVELS
from api.analysis_context import (
    AREA_LABELS,
    ROLE_EMPHASIS,
    build_reader_profile_block,
)


def test_level_keys_complete():
    assert set(EXPLANATION_LEVELS) == {"elementary", "middle", "high", "undergrad", "masters", "phd"}


def test_instruction_composition():
    si = build_chain_system_instruction(
        persona_prompt="광학 전문가 페르소나",
        research_context="페로브스카이트 태양전지",
        focus={"chips": ["reproduction"], "note": "격자 정합"},
        level_key="high",
    )
    assert "광학 전문가 페르소나" in si
    assert "페로브스카이트" in si
    assert "재현 방법" in si
    assert "격자 정합" in si
    assert EXPLANATION_LEVELS["high"][:20] in si
    assert "한국어" in si  # 기본 한국어 지시 포함


def test_instruction_defaults():
    si = build_chain_system_instruction("", "", None, "masters")
    assert EXPLANATION_LEVELS["masters"][:20] in si


class TestVocabularyTables(unittest.TestCase):
    def test_area_labels_cover_frontend_options(self):
        """Profile.tsx의 RESEARCH_AREA_OPTIONS와 값이 일치해야 한다."""
        expected = {
            "optics_photonics",
            "ai_ml",
            "robotics_control",
            "electrical_electronics",
            "computer_science",
            "physics_math",
            "bio_medical",
            "other",
        }
        self.assertEqual(set(AREA_LABELS), expected)

    def test_role_emphasis_covers_frontend_options(self):
        expected = {
            "student",
            "grad_student",
            "postdoc",
            "professor",
            "engineer",
            "manager",
            "other",
        }
        self.assertEqual(set(ROLE_EMPHASIS), expected)


class TestReaderProfileBlock(unittest.TestCase):
    def test_empty_when_nothing_meaningful(self):
        """기본값만 있으면 지시문을 늘리지 않는다."""
        self.assertEqual(
            build_reader_profile_block([], "major", "regular", "grad_student"), ""
        )

    def test_areas_are_rendered_as_korean_labels(self):
        block = build_reader_profile_block(
            ["optics_photonics", "ai_ml"], "major", "regular", "grad_student"
        )
        self.assertIn("광학·포토닉스", block)
        self.assertIn("AI·머신러닝", block)
        self.assertNotIn("optics_photonics", block)

    def test_unknown_area_is_dropped_not_rendered_raw(self):
        block = build_reader_profile_block(
            ["optics_photonics", "no_such_area"], "major", "regular", "grad_student"
        )
        self.assertNotIn("no_such_area", block)
        self.assertIn("광학·포토닉스", block)

    def test_areas_are_capped_at_three(self):
        block = build_reader_profile_block(
            ["optics_photonics", "ai_ml", "bio_medical", "physics_math"],
            "major", "regular", "grad_student",
        )
        self.assertNotIn("물리·수학", block)

    def test_novice_expertise_asks_for_more_background(self):
        block = build_reader_profile_block([], "novice", "regular", "grad_student")
        self.assertNotEqual(block, "")
        self.assertIn("배경", block)

    def test_expert_expertise_allows_terse_terms(self):
        block = build_reader_profile_block([], "expert", "regular", "grad_student")
        self.assertNotEqual(block, "")

    def test_author_experience_mentions_review_perspective(self):
        block = build_reader_profile_block([], "major", "author", "grad_student")
        self.assertNotEqual(block, "")

    def test_role_changes_emphasis(self):
        engineer = build_reader_profile_block([], "major", "regular", "engineer")
        professor = build_reader_profile_block([], "major", "regular", "professor")
        self.assertNotEqual(engineer, professor)

    def test_block_is_terse(self):
        """시스템 지시문은 매 호출에 실린다. 항목당 한 줄을 넘기지 않는다."""
        block = build_reader_profile_block(
            ["optics_photonics", "ai_ml", "bio_medical"], "novice", "author", "engineer"
        )
        self.assertLessEqual(len(block.splitlines()), 5)

    def test_no_em_dash(self):
        block = build_reader_profile_block(
            ["optics_photonics"], "novice", "author", "engineer"
        )
        self.assertNotIn("—", block)
        self.assertNotIn("–", block)


class TestChainInstructionAssembly(unittest.TestCase):
    def test_reader_profile_is_included(self):
        from api.analysis_context import build_chain_system_instruction

        out = build_chain_system_instruction(
            "", "", None, "masters", reader_profile="독자 전공: 광학·포토닉스."
        )
        self.assertIn("광학·포토닉스", out)

    def test_omitting_reader_profile_keeps_old_output(self):
        """기존 호출부가 안 바뀌어도 결과가 같아야 한다."""
        from api.analysis_context import build_chain_system_instruction

        without = build_chain_system_instruction("", "", None, "masters")
        with_empty = build_chain_system_instruction(
            "", "", None, "masters", reader_profile=""
        )
        self.assertEqual(without, with_empty)

    def test_explanation_level_comes_last(self):
        """어휘 수준이 1차 기준이므로 마지막에 와야 덮어쓰기 순서가 맞다."""
        from api.analysis_context import build_chain_system_instruction

        out = build_chain_system_instruction(
            "", "", None, "phd", reader_profile="독자 전공: 광학·포토닉스."
        )
        self.assertLess(out.index("광학·포토닉스"), out.index("설명 수준: 박사생"))


if __name__ == "__main__":
    unittest.main()
