import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from services.model_registry import ModelChoice, ROLES, active_provider, resolve
from services.models import MODEL_VISUAL


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

    def test_mermaid_and_chat_match_pre_task9_literals(self):
        """Task 9 이전: get_mermaid/repair_mermaid/chat 핸들러가 레지스트리를 거치지
        않고 MODEL_FLASH_HQ를 thinking_level 없이 직접 호출했다. Task 9가 이 두
        role을 레지스트리 경유로 배선하므로, gemini 열이 그 실값과 바이트 단위로
        같아야 provider가 gemini로 결정될 때 기존 경로가 무손상이다."""
        for role in ("mermaid", "chat"):
            with self.subTest(role=role):
                choice = resolve(role, "gemini")
                self.assertEqual(choice.model, "gemini-3.6-flash")
                self.assertIsNone(choice.effort)


class TestActiveProvider(unittest.TestCase):
    def test_defaults_to_gemini_when_resolution_yields_none(self):
        """둘 다 키가 없어 _resolve_active_provider가 None을 돌려주는 경우
        (예: 최초 설치, 아직 아무 키도 등록 안 함) — active_provider는 여기서
        죽지 않고 "gemini"를 돌려준다. 실제 거절은 /run 사전 점검이 한다."""
        settings_stub = {"ai_provider": None, "openai_api_key": "", "gemini_api_key": ""}
        with (
            patch("api.settings._get_all_settings", new=AsyncMock(return_value=settings_stub)),
            patch("api.settings._resolve_active_provider", return_value=None),
        ):
            result = asyncio.run(active_provider())
        self.assertEqual(result, "gemini")

    def test_delegates_to_settings_resolution(self):
        settings_stub = {"ai_provider": "openai", "openai_api_key": "k", "gemini_api_key": ""}
        with patch("api.settings._get_all_settings", new=AsyncMock(return_value=settings_stub)):
            result = asyncio.run(active_provider())
        self.assertEqual(result, "openai")


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


class TestPdfParseRole(unittest.TestCase):
    def test_gemini_pdf_parse_matches_current_parser_defaults(self):
        """Gemini 경로는 현행 페이지 파서와 바이트 동일해야 한다 — 모델은 MODEL_VISUAL,
        effort는 minimal. 기존 role "visual"(low)을 재사용하면 이 테스트가 막는다."""
        choice = resolve("pdf_parse", "gemini")
        self.assertEqual(choice.model, MODEL_VISUAL)
        self.assertEqual(choice.effort, "minimal")

    def test_openai_pdf_parse_uses_luna_low(self):
        """OpenAI는 minimal을 BadRequestError로 거부한다(플랜 Task 0 실측). low가 최저치."""
        choice = resolve("pdf_parse", "openai")
        self.assertEqual(choice.model, "gpt-5.6-luna")
        self.assertEqual(choice.effort, "low")

    def test_pdf_parse_is_declared_in_roles(self):
        self.assertIn("pdf_parse", ROLES)


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
