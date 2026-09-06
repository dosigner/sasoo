import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from services import model_registry
from services.model_registry import ModelChoice, ROLES, active_provider, resolve
from services.models import MODEL_FLASH_HQ, MODEL_VISUAL


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

    def test_resolvers_low(self):
        """FLASH_HQ는 minimal을 400으로 거부한다(ai.google.dev, 2026-08-16 확인)
        — main #51(159c5f2)이 같은 이유로 세 리졸버를 low로 올렸다.
        2026-08-22, 병합 전에 이 표를 같은 값으로 맞췄다.

        모델은 리터럴이 아니라 MODEL_FLASH_HQ로 비교한다. main 병합으로 프로덕션
        FLASH_HQ가 3.6에서 3.7로 올라갔고, 이 클래스가 잠그는 것은 "레지스트리
        값 == 프로덕션 실동작"이므로 상수를 따라가는 것이 그 계약이다. 레지스트리
        안에서 엉뚱한 상수(MODEL_PRO 등)로 드리프트하면 여기서 걸린다.

        상수가 가리키는 문자열 값은 여기서 보지 않는다 —
        services/test_model_pins.py::test_flash_hq_is_the_38_flash_id가 잠근다."""
        for role in ("figure_resolver", "table_resolver", "subfigure"):
            with self.subTest(role=role):
                choice = resolve(role, "gemini")
                self.assertEqual(choice.model, MODEL_FLASH_HQ)
                self.assertEqual(choice.effort, "low")

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
        같아야 provider가 gemini로 결정될 때 기존 경로가 무손상이다.

        그 실값은 MODEL_FLASH_HQ다 — main 병합으로 3.6에서 3.7로 올라갔으므로
        리터럴이 아니라 상수로 비교한다(test_resolvers_low와 같은 이유). 문자열
        값 잠금은 services/test_model_pins.py에 있다."""
        # 2026-09-06: mermaid만 사용자 결정으로 high. chat은 이식 당시 실값(None) 유지.
        expected = {"mermaid": "high", "chat": None}
        for role, effort in expected.items():
            with self.subTest(role=role):
                choice = resolve(role, "gemini")
                self.assertEqual(choice.model, MODEL_FLASH_HQ)
                self.assertEqual(choice.effort, effort)


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
        """Gemini 경로는 현행 페이지 파서와 바이트 동일해야 한다 — 모델은 MODEL_VISUAL.

        effort는 minimal이 아니라 low다. FLASH_HQ(3.7/3.8 Flash)는 minimal을 400으로
        거부한다(ai.google.dev, 2026-08-16 확인) — main의 gemini_parser.
        _THINKING_LEVEL 기본값도 이미 low이므로, 여기서도 low로 맞춰야 병합 후
        main과 동치가 된다(2026-08-22).

        주의: 이 단정만으로는 파서가 "pdf_parse" 대신 "visual" role을 잘못 써도
        못 잡는다 — 2026-08-22에 pdf_parse의 effort가 minimal에서 low로 올라가면서
        두 role의 (model, effort) 값이 gemini/openai 양쪽에서 완전히 같아졌다.
        role 이름 자체를 지키는 것은 아래 test_gemini_parser_resolves_pdf_parse_role
        (resolve 호출 인자를 직접 단정)이다."""
        choice = resolve("pdf_parse", "gemini")
        self.assertEqual(choice.model, MODEL_VISUAL)
        self.assertEqual(choice.effort, "low")

    def test_openai_pdf_parse_uses_luna_low(self):
        """OpenAI는 minimal을 BadRequestError로 거부한다(플랜 Task 0 실측). low가 최저치."""
        choice = resolve("pdf_parse", "openai")
        self.assertEqual(choice.model, "gpt-5.6-luna")
        self.assertEqual(choice.effort, "low")

    def test_pdf_parse_is_declared_in_roles(self):
        self.assertIn("pdf_parse", ROLES)

    def test_gemini_parser_resolves_pdf_parse_role(self):
        """값이 아니라 role 이름을 직접 단정한다.

        pdf_parse와 visual이 값(model, effort)으로는 더 이상 구별되지 않으므로
        (위 참고), gemini_parser.run_convert_gemini가 model_registry.resolve를
        실제로 어떤 role 문자열로 호출하는지를 스파이로 가로채 확인한다.
        gemini_parser.py는 resolve를 함수 내부에서 지역 import하므로
        (`from services.model_registry import resolve`), model_registry 모듈의
        resolve 속성 자체를 감싸야 그 지역 import가 감싼 대상을 집어온다.

        PDF 경로를 존재하지 않는 파일로 둬 _open_metadata에서 GeminiParserError로
        조기 실패시킨다 — resolve 호출은 그보다 먼저(R6, 스테이지 진입 시 1회) 일어나므로
        페이지 호출·call_interaction을 모킹할 필요가 없다.

        실증: gemini_parser.py의 `resolve("pdf_parse", provider)`를
        `resolve("visual", provider)`로 바꾸면 이 테스트가 실패한다."""
        from services.gemini_parser import GeminiParserError, run_convert_gemini

        spy = MagicMock(wraps=model_registry.resolve)
        with patch.object(model_registry, "resolve", spy):
            with self.assertRaises(GeminiParserError):
                asyncio.run(
                    run_convert_gemini(
                        Path("/nonexistent/does-not-exist.pdf"),
                        Path("/tmp"),
                        Path("/tmp"),
                    )
                )
        spy.assert_any_call("pdf_parse", "gemini")


class TestSynthesisRole(unittest.TestCase):
    """Phase 5 종합 스테이지. effort는 3편 게이트에서 high와 비교 후 확정(스펙 §5.2) — 지금은 medium."""

    def test_resolves_on_both_providers(self):
        for provider in ("gemini", "openai"):
            with self.subTest(provider=provider):
                choice = resolve("synthesis", provider)
                self.assertEqual(choice.effort, "medium")

    def test_gemini_uses_flash_hq(self):
        self.assertEqual(resolve("synthesis", "gemini").model, MODEL_FLASH_HQ)

    def test_openai_uses_luna(self):
        self.assertEqual(resolve("synthesis", "openai").model, "gpt-5.6-luna")

    def test_not_in_provider_override_table(self):
        """DEC-022: 표는 비어 있어야 한다 — synthesis도 예외가 아니다."""
        self.assertNotIn("synthesis", model_registry._ROLE_PROVIDER_OVERRIDE)


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


def test_flash_hq_roles_never_use_minimal_effort():
    """FLASH_HQ(=3.7/3.8 Flash)는 minimal을 400으로 거부한다.

    근거: services/models.py 모듈 docstring, ai.google.dev 2026-08-16 확인.
    main #51(159c5f2)이 figure_resolver/table_resolver/subfigure/gemini_parser
    네 곳을 이 이유로 low로 올렸다. 레지스트리로 값을 옮기면서 minimal이 다시
    들어오면 그 네 경로가 런타임에 400을 받는다 — 테스트 없이는 실호출에서만 드러난다.

    minimal이 안전한 곳은 flash-lite를 쓰는 role뿐이다(screening, naming).
    """
    from services.model_registry import _REGISTRY
    from services.models import MODEL_FLASH_HQ, MODEL_FLASH_LITE

    offenders = [
        role
        for role, choice in _REGISTRY["gemini"].items()
        if choice.effort == "minimal" and choice.model != MODEL_FLASH_LITE
    ]
    assert offenders == [], (
        f"minimal은 flash-lite에서만 쓸 수 있다. FLASH_HQ({MODEL_FLASH_HQ})를 "
        f"쓰면서 minimal인 role: {offenders}"
    )


class TestProviderForRole(unittest.TestCase):
    """role별 provider 오버라이드 기제. 표(_ROLE_PROVIDER_OVERRIDE)는 지금 비어 있다(DEC-022).

    DEC-019가 deep_dive를 OpenAI Luna로 보내던 항목은 2026-09-06에 뺐다: 3.7이 폭주한
    VLA 6편을 3.8 Flash로 같은 체인·상한으로 재실행해 0/6 무폭주였다
    (RESEARCH/2026-09-06-vla6-gemini-3-8.md). 기제(provider_for_role, 체인 갈림 배선)는
    남겨 두므로 표가 비어 있을 때와 항목이 있을 때의 동작을 둘 다 잠근다.
    """

    @staticmethod
    def _run(role, *, stored, has_openai, has_gemini):
        settings_stub = {
            "ai_provider": stored,
            "openai_api_key": "sk-x" if has_openai else "",
            "gemini_api_key": "AIza-x" if has_gemini else "",
        }
        with patch("api.settings._get_all_settings", new=AsyncMock(return_value=settings_stub)):
            return asyncio.run(model_registry.provider_for_role(role))

    def test_override_table_is_empty(self):
        """DEC-022: deep_dive도 기본 provider를 따른다. 항목을 다시 넣으려면 실측이 먼저다."""
        self.assertEqual(model_registry._ROLE_PROVIDER_OVERRIDE, {})

    def test_deep_dive_stays_on_base_provider_even_with_openai_key(self):
        result = self._run("deep_dive", stored="gemini", has_openai=True, has_gemini=True)
        self.assertEqual(result, "gemini")

    def test_override_entry_moves_role_when_key_present(self):
        """기제는 살아 있다 — 항목이 있고 그 키가 있으면 그쪽으로 보낸다(DEC-019의 배선)."""
        with patch.dict(model_registry._ROLE_PROVIDER_OVERRIDE, {"deep_dive": "openai"}):
            result = self._run("deep_dive", stored="gemini", has_openai=True, has_gemini=True)
        self.assertEqual(result, "openai")

    def test_override_entry_falls_back_without_key(self):
        """항목이 있어도 그 키가 없으면 조용히 기본 provider로 돌아간다.

        키가 없어 단계를 통째로 잃는 것보다 폭주 위험을 안고 돌리는 편이 낫다.
        """
        with patch.dict(model_registry._ROLE_PROVIDER_OVERRIDE, {"deep_dive": "openai"}):
            result = self._run("deep_dive", stored="gemini", has_openai=False, has_gemini=True)
        self.assertEqual(result, "gemini")

    def test_other_roles_keep_base_provider(self):
        """오버라이드는 표에 적힌 role에만 걸린다 — 다른 role까지 번지면 안 된다."""
        with patch.dict(model_registry._ROLE_PROVIDER_OVERRIDE, {"deep_dive": "openai"}):
            for role in ("visual", "recipe", "viz_planning", "citation"):
                with self.subTest(role=role):
                    result = self._run(role, stored="gemini", has_openai=True, has_gemini=True)
                    self.assertEqual(result, "gemini")


if __name__ == "__main__":
    unittest.main()
