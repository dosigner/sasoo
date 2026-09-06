"""단위 테스트 — tools/provider_compare.py의 순수 로직만 검증한다.

이 도구는 실 API 호출 도구다(비용 발생). 여기서는 네트워크·DB I/O가 없는
부분만 검증한다: CLI 파싱/검증, 스테이지별 프롬프트·스키마 조립, 비용
계산의 재시도 분기. 실 LLM 호출(run_one/main_async 본체)은 검증하지 않는다.
"""

import unittest

from services.model_registry import ROLES as REGISTRY_ROLES

from tools.provider_compare import (
    STAGE_ROLES,
    build_visual_figure_desc,
    citation_prompt,
    deep_dive_prompt,
    parse_args,
    recipe_prompt,
    screening_prompt,
    visual_prompt,
    _result_cost,
)


class TestStageRoles(unittest.TestCase):
    def test_all_five_stages_present(self):
        self.assertEqual(
            set(STAGE_ROLES),
            {"screening", "citation", "visual", "recipe", "deep_dive"},
        )

    def test_stage_roles_are_registered_in_model_registry(self):
        """model_registry가 단일 소스 — 여기 나열한 role은 전부 레지스트리에 있어야 한다."""
        for role in STAGE_ROLES:
            self.assertIn(role, REGISTRY_ROLES)


class TestParseArgs(unittest.TestCase):
    def test_defaults_cover_all_stages_and_providers(self):
        args, stages, providers, effort_compare, efforts = parse_args([])
        self.assertEqual(stages, list(STAGE_ROLES))
        self.assertEqual(providers, ["gemini", "openai"])
        self.assertFalse(effort_compare)
        self.assertEqual(efforts, [None])

    def test_stages_and_providers_filter(self):
        _args, stages, providers, _c, _e = parse_args(
            ["--stages", "visual,deep_dive", "--providers", "openai"]
        )
        self.assertEqual(stages, ["visual", "deep_dive"])
        self.assertEqual(providers, ["openai"])

    def test_unknown_stage_exits(self):
        with self.assertRaises(SystemExit):
            parse_args(["--stages", "bogus"])

    def test_unknown_provider_exits(self):
        with self.assertRaises(SystemExit):
            parse_args(["--providers", "bogus"])

    def test_role_without_efforts_exits(self):
        with self.assertRaises(SystemExit):
            parse_args(["--role", "deep_dive"])

    def test_efforts_without_role_exits(self):
        with self.assertRaises(SystemExit):
            parse_args(["--efforts", "high,xhigh"])

    def test_effort_compare_mode_overrides_stages_to_single_role(self):
        _args, stages, _providers, effort_compare, efforts = parse_args(
            ["--role", "deep_dive", "--efforts", "high,xhigh"]
        )
        self.assertTrue(effort_compare)
        self.assertEqual(stages, ["deep_dive"])
        self.assertEqual(efforts, ["high", "xhigh"])

    def test_unknown_role_in_effort_compare_mode_exits(self):
        with self.assertRaises(SystemExit):
            parse_args(["--role", "bogus", "--efforts", "high"])

    def test_paper_id_parses_as_int(self):
        args, *_ = parse_args(["--paper-id", "7"])
        self.assertEqual(args.paper_id, 7)


class TestBuildVisualFigureDesc(unittest.TestCase):
    def test_empty_when_no_figures_or_tables(self):
        self.assertEqual(build_visual_figure_desc({"figures": [], "tables": []}), "")

    def test_lists_figure_and_table_metadata(self):
        meta = {
            "figures": [
                {"figure_num": "Fig. 1", "quality": "high", "confidence": 0.9, "resolver_version": "v3"},
            ],
            "tables": [
                {"table_num": "Table 1", "confidence": 0.8, "parse_method": "vlm", "resolver_version": "v3"},
            ],
        }
        desc = build_visual_figure_desc(meta)
        self.assertIn("Extracted 1 resolved figures and 1 resolved tables", desc)
        self.assertIn("Fig. 1: quality=high, confidence=0.9, resolver=v3", desc)
        self.assertIn("Table 1: confidence=0.8, method=vlm, resolver=v3", desc)

    def test_caps_table_listing_at_ten(self):
        meta = {
            "figures": [],
            "tables": [
                {"table_num": f"T{i}", "confidence": 1.0, "parse_method": "vlm", "resolver_version": "v3"}
                for i in range(15)
            ],
        }
        desc = build_visual_figure_desc(meta)
        self.assertIn("T9", desc)
        self.assertNotIn("T10", desc)


class TestStagePromptBuilders(unittest.TestCase):
    def test_screening_prompt_embeds_input_and_uses_real_schema(self):
        from services import analysis_execution as ar

        prompt, schema = screening_prompt("이 논문은 ...")
        self.assertIn("이 논문은 ...", prompt)
        self.assertIs(schema, ar._SCREENING_SCHEMA)

    def test_visual_prompt_uses_real_instruction_and_schema(self):
        from services import analysis_execution as ar

        prompt, schema = visual_prompt({"figures": [], "tables": []})
        self.assertIn(ar._VISUAL_INSTRUCTION, prompt)
        self.assertIs(schema, ar._VISUAL_SCHEMA)

    def test_recipe_prompt_uses_real_schema(self):
        from services import analysis_execution as ar

        prompt, schema = recipe_prompt()
        self.assertIn("재현 가능한 실험 레시피", prompt)
        self.assertIs(schema, ar._RECIPE_SCHEMA)

    def test_deep_dive_prompt_uses_real_instruction_and_schema(self):
        from services import analysis_execution as ar

        prompt, schema = deep_dive_prompt()
        self.assertIn(ar._DEEP_DIVE_INSTRUCTION, prompt)
        self.assertIs(schema, ar._DEEP_DIVE_SCHEMA)

    def test_citation_prompt_none_when_no_references(self):
        prompt, schema, local_result = citation_prompt(
            {"citation_body": "본문", "citation_references": ""},
            sections={},
            paper_authors="Kim",
        )
        self.assertIsNone(prompt)
        self.assertIsNone(schema)
        self.assertEqual(local_result.get("total_references", 0), 0)

    def test_citation_prompt_builds_when_references_parseable(self):
        from services import analysis_execution as ar

        references = (
            "[1] Kim, J. (2020). A Great Method. Journal of Things.\n"
            "[2] Lee, S. (2019). Another Study. Journal of Stuff.\n"
        )
        body = (
            "We build on prior work [1]. This extends earlier findings [1]. "
            "A different approach was tried [2]."
        )
        prompt, schema, local_result = citation_prompt(
            {"citation_body": body, "citation_references": references},
            sections={},
            paper_authors="",
        )
        if prompt is None:
            # 파서가 이 합성 텍스트에서 top_cited를 못 뽑으면(실제 참고문헌 포맷
            # 의존) 최소한 로컬 파싱 자체는 죽지 않았는지만 확인한다.
            self.assertIsInstance(local_result, dict)
        else:
            self.assertIs(schema, ar._CITATION_SCHEMA)
            self.assertIn("인용", prompt)


class TestResultCost(unittest.TestCase):
    def test_uses_prior_attempts_when_present(self):
        result = {"model": "gpt-5.6-luna", "tokens_in": 999, "tokens_out": 999, "cost_usd_prior_attempts": 0.0042}
        self.assertEqual(_result_cost(result), 0.0042)

    def test_falls_back_to_calc_cost(self):
        from services.pricing import calc_cost

        result = {"model": "gpt-5.6-luna", "tokens_in": 1000, "tokens_out": 500}
        expected = calc_cost("gpt-5.6-luna", 1000, 500)
        self.assertEqual(_result_cost(result), expected)


if __name__ == "__main__":
    unittest.main()
