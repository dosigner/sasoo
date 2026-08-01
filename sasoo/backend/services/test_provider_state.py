import unittest

from services.provider_state import (
    VALID_PROVIDERS,
    effective_provider,
    mirror_legacy_settings,
    provider_switched,
)


class TestLegacyMirror(unittest.TestCase):
    """ai_provider와 lockstep으로 갱신할 레거시 설정."""

    def test_gemini_mirrors_image_provider(self):
        self.assertEqual(mirror_legacy_settings("gemini"), {"image_provider": "gemini"})

    def test_openai_mirrors_image_provider(self):
        self.assertEqual(mirror_legacy_settings("openai"), {"image_provider": "openai"})

    def test_pdf_visual_engine_is_not_mirrored(self):
        """pdf_visual_engine의 도메인은 {gemini, odl}이라 공급사 값을 받지 못한다.

        api/settings.py가 그 둘 외의 값을 400으로 거부하므로, 미러링하면
        ai_provider=openai 저장이 통째로 실패한다.
        """
        for provider in VALID_PROVIDERS:
            with self.subTest(provider=provider):
                self.assertNotIn("pdf_visual_engine", mirror_legacy_settings(provider))

    def test_unknown_provider_raises(self):
        with self.assertRaises(ValueError):
            mirror_legacy_settings("anthropic")


class TestEffectiveProvider(unittest.TestCase):
    def test_stored_choice_wins_when_its_key_exists(self):
        self.assertEqual(effective_provider("gemini", has_openai=True, has_gemini=True), "gemini")
        self.assertEqual(effective_provider("openai", has_openai=True, has_gemini=True), "openai")

    def test_falls_back_to_the_remaining_key(self):
        self.assertEqual(effective_provider("openai", has_openai=False, has_gemini=True), "gemini")
        self.assertEqual(effective_provider("gemini", has_openai=True, has_gemini=False), "openai")

    def test_none_when_no_keys_at_all(self):
        self.assertIsNone(effective_provider("openai", has_openai=False, has_gemini=False))

    def test_unset_choice_prefers_openai_when_both_keys_exist(self):
        self.assertEqual(effective_provider(None, has_openai=True, has_gemini=True), "openai")

    def test_unset_choice_uses_whichever_key_exists(self):
        self.assertEqual(effective_provider(None, has_openai=False, has_gemini=True), "gemini")

    def test_garbage_stored_value_is_treated_as_unset(self):
        self.assertEqual(effective_provider("anthropic", has_openai=True, has_gemini=True), "openai")


class TestSwitchDetection(unittest.TestCase):
    def test_switch_detected_when_effective_differs(self):
        self.assertTrue(provider_switched("openai", "gemini"))

    def test_no_switch_when_same(self):
        self.assertFalse(provider_switched("openai", "openai"))

    def test_no_switch_when_locked_out(self):
        """키가 하나도 없는 건 '전환'이 아니라 '잠김'이다."""
        self.assertFalse(provider_switched("openai", None))

    def test_no_switch_when_stored_was_unset(self):
        self.assertFalse(provider_switched(None, "openai"))


if __name__ == "__main__":
    unittest.main()
