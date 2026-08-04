import unittest

from services.model_registry import ModelChoice, ROLES, resolve


class TestGeminiColumnMatchesProduction(unittest.TestCase):
    """Gemini 열은 기존 실동작의 이식이다 — 값이 다르면 동작 변경이므로 버그다."""

    def test_screening_flash_lite_minimal(self):
        choice = resolve("screening", "gemini")
        self.assertEqual(choice.model, "gemini-3.5-flash-lite")
        self.assertEqual(choice.effort, "minimal")  # analysis_routes.py:456 실값

    def test_citation_low(self):
        self.assertEqual(resolve("citation", "gemini").effort, "low")

    def test_chain_stages(self):
        self.assertEqual(resolve("visual", "gemini").effort, "low")
        self.assertEqual(resolve("recipe", "gemini").effort, "medium")
        self.assertEqual(resolve("deep_dive", "gemini").effort, "high")
        self.assertEqual(resolve("viz_planning", "gemini").effort, "medium")

    def test_resolvers_minimal(self):
        for role in ("figure_resolver", "table_resolver", "subfigure"):
            with self.subTest(role=role):
                choice = resolve(role, "gemini")
                self.assertEqual(choice.model, "gemini-3.6-flash")
                self.assertEqual(choice.effort, "minimal")

    def test_naming_flash_lite(self):
        self.assertEqual(resolve("naming", "gemini").model, "gemini-3.5-flash-lite")

    def test_figure_explain_high(self):
        self.assertEqual(resolve("figure_explain", "gemini").effort, "high")

    def test_viz_image_plan_uses_pro(self):
        self.assertEqual(resolve("viz_image_plan", "gemini").model, "gemini-3.1-pro-preview")


class TestOpenAIColumn(unittest.TestCase):
    def test_deep_dive_is_high_not_xhigh(self):
        """스펙 개정 R3 — xhigh 금지."""
        self.assertEqual(resolve("deep_dive", "openai").effort, "high")

    def test_all_openai_text_roles_use_luna(self):
        for role in ROLES:
            if role == "image":
                continue
            with self.subTest(role=role):
                self.assertEqual(resolve(role, "openai").model, "gpt-5.6-luna")

    def test_no_role_uses_xhigh(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.assertNotEqual(resolve(role, "openai").effort, "xhigh")


class TestRegistryShape(unittest.TestCase):
    def test_unknown_role_raises(self):
        with self.assertRaises(KeyError):
            resolve("no_such_role", "gemini")

    def test_unknown_provider_raises(self):
        with self.assertRaises(KeyError):
            resolve("deep_dive", "anthropic")

    def test_both_providers_cover_same_roles(self):
        from services.model_registry import _REGISTRY
        self.assertEqual(set(_REGISTRY["gemini"]), set(_REGISTRY["openai"]))


if __name__ == "__main__":
    unittest.main()
