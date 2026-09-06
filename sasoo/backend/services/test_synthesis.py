"""Phase 5 종합 스테이지와 다이어그램 기획 후처리 테스트(스펙 §5.3, §5.4).

여기서 잠그는 계약:
- `_validate_synthesis`는 근거 없는 수치·목록 밖 참조를 버린다. 버림은 조용해선 안 되고
  `dropped` 카운트로 세어져야 한다(스펙 §8 게이트 지표).
- `_normalize_viz_plan`은 구획 상한과 "result는 flowchart만"을 강제한다.
- 두 스키마의 마지막 속성은 정수다(DEC-014: 마지막 자유서술 필드가 폭주의 자리였다).
"""

import unittest
from unittest.mock import AsyncMock, patch

from services import analysis_execution as ae


class ValidateSynthesisTests(unittest.TestCase):
    DOC = "The measured loss was 0.35 dB at 1550 nm with a bandwidth of 40 GHz."

    def _validate(self, data, doc_text=None, figure_nums=None, param_names=None):
        return ae._validate_synthesis(
            data,
            self.DOC if doc_text is None else doc_text,
            ["1", "2", "3"] if figure_nums is None else figure_nums,
            ["펌프 출력", "격자 주기"] if param_names is None else param_names,
        )

    def test_metric_without_unit_is_dropped(self):
        out, dropped = self._validate({"key_metrics": [
            {"label": "손실", "value": "0.35", "unit": "", "evidence": "The measured loss was 0.35 dB."},
        ]})
        self.assertEqual(out["key_metrics"], [])
        self.assertEqual(dropped["key_metrics"], 1)

    def test_metric_value_missing_from_evidence_is_dropped(self):
        out, dropped = self._validate({"key_metrics": [
            {"label": "손실", "value": "0.35", "unit": "dB",
             "evidence": "The measured loss was 1550 nm wide."},
        ]})
        self.assertEqual(out["key_metrics"], [])
        self.assertEqual(dropped["key_metrics"], 1)

    def test_metric_evidence_missing_from_document_is_dropped(self):
        out, dropped = self._validate({"key_metrics": [
            # 인용 자체는 값과 앞뒤가 맞지만 논문 본문에 없는 수치다(지어낸 인용).
            {"label": "손실", "value": "9.99", "unit": "dB",
             "evidence": "The measured loss was 9.99 dB."},
        ]})
        self.assertEqual(out["key_metrics"], [])
        self.assertEqual(dropped["key_metrics"], 1)

    def test_metric_passes_with_comma_separated_number(self):
        """리터럴이 아니라 수치 동치로 본다 — "1,550"과 "1550"은 같은 값이다."""
        out, dropped = self._validate({"key_metrics": [
            {"label": "파장", "value": "1,550", "unit": "nm",
             "evidence": "The measured loss was 0.35 dB at 1550 nm."},
        ]})
        self.assertEqual(len(out["key_metrics"]), 1)
        self.assertEqual(dropped["key_metrics"], 0)

    def test_figure_num_normalized_then_unknown_dropped(self):
        out, dropped = self._validate({"result_figures": [
            {"figure_num": "Fig. 3", "interpretation": "정규화되어 통과"},
            {"figure_num": "Figure 2", "interpretation": "정규화되어 통과"},
            {"figure_num": "12", "interpretation": "목록에 없어 버림"},
        ]})
        self.assertEqual(
            [f["figure_num"] for f in out["result_figures"]], ["Fig. 3", "Figure 2"],
        )
        self.assertEqual(dropped["result_figures"], 1)

    def test_unknown_parameter_name_dropped(self):
        out, dropped = self._validate({"key_parameters": [
            {"name": "펌프출력"},           # 공백만 다르다 — 통과
            {"name": "굴절률 대비"},         # 레시피에 없다 — 버림
        ]})
        self.assertEqual([p["name"] for p in out["key_parameters"]], ["펌프출력"])
        self.assertEqual(dropped["key_parameters"], 1)

    def test_caps_arrays_and_strips_emoji(self):
        metric = {"label": "손실 🚀", "value": "0.35", "unit": "dB",
                  "evidence": "The measured loss was 0.35 dB."}
        out, dropped = self._validate({
            "problem_sentence": "문제 ✨",
            "key_metrics": [dict(metric) for _ in range(5)],
            "equations": [
                {"latex": f"E_{i}", "meaning": "뜻",
                 "symbols": [{"symbol": f"s{j}", "meaning": "뜻"} for j in range(6)],
                 "paper_number": ""}
                for i in range(7)
            ],
            "result_figures": [{"figure_num": "1", "interpretation": "i"} for _ in range(6)],
            "key_parameters": [{"name": "펌프 출력"} for _ in range(7)],
        })
        self.assertEqual(len(out["key_metrics"]), 3)
        self.assertEqual(len(out["equations"]), 5)
        self.assertEqual(len(out["equations"][0]["symbols"]), 4)
        self.assertEqual(len(out["result_figures"]), 4)
        self.assertEqual(len(out["key_parameters"]), 5)
        self.assertEqual(out["problem_sentence"], "문제")
        self.assertEqual(out["key_metrics"][0]["label"], "손실")
        # 상한 자르기는 버림으로 세지 않는다(게이트 지표는 품질 신호여야 한다).
        self.assertEqual(dropped, {"key_metrics": 0, "result_figures": 0, "key_parameters": 0})

    def test_empty_doc_text_skips_body_check(self):
        out, dropped = self._validate(
            {"key_metrics": [
                {"label": "손실", "value": "9.99", "unit": "dB",
                 "evidence": "The measured loss was 9.99 dB."},
            ]},
            doc_text="",
        )
        self.assertEqual(len(out["key_metrics"]), 1)
        self.assertEqual(dropped["key_metrics"], 0)


class NormalizeVizPlanTests(unittest.TestCase):
    def _plan(self, diagrams):
        return {
            "concept_illustration": {
                "title": "광학 셋업", "description": "설명", "category": "physical_setup",
            },
            "diagrams": diagrams,
            "diagram_count": len(diagrams),
        }

    def test_concept_illustration_comes_first(self):
        items = ae._normalize_viz_plan(self._plan([
            {"title": "절차", "block": "method", "diagram_type": "flowchart",
             "description": "d", "category": "algorithm_flow"},
        ]))
        self.assertEqual(items[0]["tool"], "paperbanana")
        self.assertEqual(items[0]["block"], "concept")
        self.assertEqual(items[1]["tool"], "mermaid")

    def test_sequence_in_result_block_is_dropped(self):
        items = ae._normalize_viz_plan(self._plan([
            {"title": "시간 순서", "block": "result", "diagram_type": "sequence",
             "description": "d", "category": "timeline"},
            {"title": "비교", "block": "result", "diagram_type": "flowchart",
             "description": "d", "category": "comparison"},
        ]))
        self.assertEqual([it["title"] for it in items], ["광학 셋업", "비교"])

    def test_method_block_capped_at_three(self):
        items = ae._normalize_viz_plan(self._plan([
            {"title": f"방법{i}", "block": "method", "diagram_type": "flowchart",
             "description": "d", "category": "algorithm_flow"}
            for i in range(4)
        ]))
        self.assertEqual(len([it for it in items if it["block"] == "method"]), 3)
        self.assertEqual(len(items), 4)  # 개념도 1 + method 3


class SchemaShapeTests(unittest.TestCase):
    def test_last_property_is_integer(self):
        """DEC-014 잠금: 마지막 속성이 자유서술 문자열이면 폭주의 자리가 된다."""
        for schema, expected in ((ae._SYNTHESIS_SCHEMA, "equation_count"),
                                 (ae._VIZ_PLAN_SCHEMA, "diagram_count")):
            last = list(schema["properties"])[-1]
            self.assertEqual(last, expected)
            self.assertEqual(schema["properties"][last]["type"], "integer")


class MermaidRenderableTypeTests(unittest.IsolatedAsyncioTestCase):
    async def test_mindmap_is_coerced_to_flowchart(self):
        self.assertNotIn("mindmap", ae._MERMAID_RENDERABLE_TYPES)
        captured = {}

        async def _fake_call(prompt: str, **kwargs):
            captured["prompt"] = prompt
            return {"text": "flowchart TD\nA-->B", "model": "gemini",
                    "tokens_in": 1, "tokens_out": 1}

        with patch("services.analysis_execution.call_interaction", new=_fake_call):
            code = await ae._generate_single_mermaid(
                7,
                {"title": "마인드맵", "diagram_type": "mindmap", "description": "d"},
                "VIZ-CONTEXT",
                [],
            )

        self.assertEqual(code, "flowchart TD\nA-->B")
        self.assertIn("Mermaid flowchart 다이어그램", captured["prompt"])
        self.assertNotIn("mindmap", captured["prompt"])


class RunSynthesisTests(unittest.IsolatedAsyncioTestCase):
    """저장 경로: 검증을 거친 결과에 dropped가 붙어 synthesis phase로 들어간다."""

    async def test_stores_validated_payload_with_dropped_counts(self):
        payload = {
            "problem_sentence": "문제", "method_sentence": "방법",
            "key_metrics": [
                {"label": "손실", "value": "0.35", "unit": "dB",
                 "evidence": "loss was 0.35 dB"},
                {"label": "지어냄", "value": "9.99", "unit": "dB",
                 "evidence": "loss was 9.99 dB"},
            ],
            "equations": [], "result_figures": [{"figure_num": "Fig. 1", "interpretation": "i"}],
            "key_parameters": [{"name": "펌프 출력"}], "equation_count": 0,
        }

        async def _fake_call(contents, **kwargs):
            import json as _json
            return {"text": _json.dumps(payload, ensure_ascii=False), "model": "gemini",
                    "tokens_in": 10, "tokens_out": 20}

        insert = AsyncMock(return_value=1)
        status = ae.AnalysisStatus(
            paper_id=7, overall_status="running", phases=[], progress_pct=0.0,
        )
        with (
            patch("services.analysis_execution.call_interaction", new=_fake_call),
            patch("services.analysis_execution.fetch_all", new=AsyncMock(return_value=[
                {"figure_num": "1", "caption": "첫 그림"},
            ])),
            patch("services.analysis_execution._get_cached_phase_result",
                  new=AsyncMock(return_value=None)),
            patch("services.analysis_execution.execute_insert", new=insert),
        ):
            saved = await ae._run_synthesis(
                7, "VIZ-CONTEXT", ["p1"], status,
                recipe_result='{"parameters": [{"name": "펌프 출력"}]}',
                body_text="loss was 0.35 dB",
            )

        self.assertEqual(saved["dropped"]["key_metrics"], 1)
        self.assertEqual(len(saved["key_metrics"]), 1)
        self.assertEqual(len(saved["result_figures"]), 1)
        self.assertEqual(insert.await_args.args[1][1], "synthesis")
        self.assertGreater(status.total_cost_usd, 0)


if __name__ == "__main__":
    unittest.main()
