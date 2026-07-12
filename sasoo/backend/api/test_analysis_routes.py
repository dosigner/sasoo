import contextlib
import sys
import types
import unittest
from dataclasses import dataclass, field
from enum import Enum
from unittest.mock import AsyncMock, patch

_TEMP_MODULE_NAMES = (
    "aiosqlite",
    "fastapi",
    "fastapi.responses",
    "models.schemas",
    "services.agents",
    "services.odl_parser",
    "api.report_service",
)
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in _TEMP_MODULE_NAMES}

aiosqlite_module = types.ModuleType("aiosqlite")
aiosqlite_module.Connection = object
aiosqlite_module.Row = dict

async def _unused_connect(*args, **kwargs):
    raise RuntimeError("aiosqlite.connect should not be called in these tests")

aiosqlite_module.connect = _unused_connect
sys.modules.setdefault("aiosqlite", aiosqlite_module)


class _StubHTTPException(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _StubAPIRouter:
    def __init__(self, *args, **kwargs):
        pass

    def get(self, *args, **kwargs):
        def decorator(fn):
            return fn
        return decorator

    def post(self, *args, **kwargs):
        def decorator(fn):
            return fn
        return decorator


class _StubBackgroundTasks:
    def add_task(self, *args, **kwargs):
        return None


def _stub_query(default=None, **kwargs):
    return default


fastapi_module = types.ModuleType("fastapi")
fastapi_module.APIRouter = _StubAPIRouter
fastapi_module.BackgroundTasks = _StubBackgroundTasks
fastapi_module.HTTPException = _StubHTTPException
fastapi_module.Query = _stub_query
fastapi_module.Request = object
sys.modules.setdefault("fastapi", fastapi_module)


class _StubStreamingResponse:
    def __init__(self, body_iterator, media_type=None, headers=None):
        self.body_iterator = body_iterator
        self.media_type = media_type
        self.headers = headers or {}


fastapi_responses_module = types.ModuleType("fastapi.responses")
fastapi_responses_module.StreamingResponse = _StubStreamingResponse
sys.modules.setdefault("fastapi.responses", fastapi_responses_module)

odl_parser_module = types.ModuleType("services.odl_parser")

class _StubOdlParserError(RuntimeError):
    pass


class _StubOdlRuntimeError(_StubOdlParserError):
    pass


async def _stub_async_noop(*args, **kwargs):
    return None


odl_parser_module.OdlParserError = _StubOdlParserError
odl_parser_module.OdlRuntimeError = _StubOdlRuntimeError
odl_parser_module.ensure_text_artifacts = lambda *args, **kwargs: {}
odl_parser_module.ensure_text_artifacts_async = _stub_async_noop
odl_parser_module.ensure_paper_artifacts = _stub_async_noop
odl_parser_module.explain_odl_failure = lambda exc: (500, str(exc))
odl_parser_module.figure_row_to_api_dict = lambda row: row
odl_parser_module.table_row_to_api_dict = lambda row: row
odl_parser_module.get_pdf_signature = lambda pdf_path: {
    "pdf_mtime_ns": getattr(pdf_path.stat(), "st_mtime_ns", 0),
    "pdf_size": getattr(pdf_path.stat(), "st_size", 0),
}
odl_parser_module.get_artifact_refresh_error = lambda paper_id: None
odl_parser_module.is_artifact_refresh_running = lambda paper_id: False
odl_parser_module.paper_text_is_current = lambda paper_dir: True
odl_parser_module.paper_visuals_are_current = lambda paper_dir: True
odl_parser_module.schedule_paper_artifacts_refresh = _stub_async_noop
sys.modules.setdefault("services.odl_parser", odl_parser_module)

report_service_module = types.ModuleType("api.report_service")
report_service_module._format_phase_data = lambda phase, data: str(data)
report_service_module._generate_paperbanana_image = _stub_async_noop
report_service_module._wrap_text = lambda text, font, width: [text]
sys.modules.setdefault("api.report_service", report_service_module)


agents_module = types.ModuleType("services.agents")


class _StubAgentProfile:
    display_name_ko = "크리스탈"
    display_name = "Crystal"
    personality = "precise"


class _StubAgent:
    profile = _StubAgentProfile()


agents_module.get_agent_for_domain = lambda domain: _StubAgent()
sys.modules.setdefault("services.agents", agents_module)


class _AnalysisPhase(str, Enum):
    SCREENING = "screening"
    CITATION = "citation"
    VISUAL = "visual"
    RECIPE = "recipe"
    DEEP_DIVE = "deep_dive"


@dataclass
class _PhaseStatus:
    phase: _AnalysisPhase
    status: str = "pending"
    started_at: str | None = None
    completed_at: str | None = None
    model_used: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    error_message: str | None = None


@dataclass
class _AnalysisStatus:
    paper_id: int
    overall_status: str = "pending"
    phases: list[_PhaseStatus] = field(default_factory=list)
    progress_pct: float = 0.0
    current_phase: _AnalysisPhase | None = None
    total_cost_usd: float = 0.0
    total_tokens_in: int = 0
    total_tokens_out: int = 0


@dataclass
class _SimpleModel:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


schemas_module = types.ModuleType("models.schemas")
schemas_module.AnalysisPhase = _AnalysisPhase
schemas_module.AnalysisResult = _SimpleModel
schemas_module.AnalysisStatus = _AnalysisStatus
schemas_module.DomainResult = _SimpleModel
schemas_module.FigureExplanationResponse = _SimpleModel
schemas_module.FigureInfo = _SimpleModel
schemas_module.FigureListResponse = _SimpleModel
schemas_module.FullAnalysisResponse = _SimpleModel
schemas_module.MermaidResult = _SimpleModel
schemas_module.PaperBananaRequest = _SimpleModel
schemas_module.PaperBananaResponse = _SimpleModel
schemas_module.PhaseStatus = _PhaseStatus
schemas_module.RecipeCard = _SimpleModel
schemas_module.ReportResponse = _SimpleModel
schemas_module.TableInfo = _SimpleModel
schemas_module.TableListResponse = _SimpleModel
schemas_module.VisualizationItem = _SimpleModel
schemas_module.VisualizationPlanResponse = _SimpleModel
sys.modules.setdefault("models.schemas", schemas_module)

from api import analysis_routes, figure_service
from models.schemas import AnalysisStatus

for _module_name, _original in _ORIGINAL_MODULES.items():
    if _original is None:
        sys.modules.pop(_module_name, None)
    else:
        sys.modules[_module_name] = _original


def _row(phase: str, result: str, **extra):
    base = {
        "id": extra.pop("id", 1),
        "paper_id": extra.pop("paper_id", 7),
        "phase": phase,
        "result": result,
        "parsed_result": extra.pop("parsed_result", None),
        "model_used": extra.pop("model_used", "gemini"),
        "tokens_in": extra.pop("tokens_in", 10),
        "tokens_out": extra.pop("tokens_out", 20),
        "cost_usd": extra.pop("cost_usd", 0.3),
        "created_at": extra.pop("created_at", "2026-03-26T12:00:00"),
    }
    if base["parsed_result"] is None:
        base["parsed_result"] = {"raw_text": result}
    base.update(extra)
    return base


class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


class AnalysisRouteSemanticTests(unittest.IsolatedAsyncioTestCase):
    def test_screening_gate_decision_flags_low_relevance(self):
        should_skip, reason = analysis_routes._screening_gate_decision(
            '{"relevance_score":0.2,"domain":"general","key_topics":[],"is_experimental":false}'
        )

        self.assertTrue(should_skip)
        self.assertEqual(reason, "low_relevance_screening")

    def test_screening_gate_decision_flags_low_confidence(self):
        should_skip, reason = analysis_routes._screening_gate_decision(
            '{"relevance_score":0.45,"domain":"general","key_topics":["주제1"],"is_experimental":false}'
        )

        self.assertTrue(should_skip)
        self.assertEqual(reason, "low_confidence_screening")

    async def test_status_results_and_report_use_latest_phase_rows(self):
        paper = {"id": 7, "title": "Latest Paper", "status": "completed", "authors": "Kim", "year": 2026, "journal": "Nature", "doi": None, "domain": "materials", "agent_used": "crystal", "analyzed_at": "2026-03-26T12:00:00"}
        latest_rows = {
            "screening": _row("screening", '{"summary":"latest screening"}', parsed_result={"summary": "latest screening"}, cost_usd=0.1),
            "recipe": _row("recipe", '{"title":"latest recipe"}', parsed_result={"title": "latest recipe"}, cost_usd=0.2),
            "deep_dive": _row("deep_dive", '{"detailed_analysis":"latest deep dive"}', parsed_result={"detailed_analysis": "latest deep dive"}, cost_usd=0.4),
        }

        with (
            patch("api.analysis_routes.fetch_one", new=AsyncMock(return_value=paper)),
            patch("api.analysis_routes.fetch_all", new=AsyncMock(return_value=[])) as fetch_all_mock,
            patch("api.analysis_routes.get_latest_completed_phase_rows", new=AsyncMock(return_value=latest_rows)),
        ):
            status = await analysis_routes.get_analysis_status(7)
            results = await analysis_routes.get_analysis_results(7)
            report = await analysis_routes.get_report(7)

        self.assertIsInstance(status, AnalysisStatus)
        self.assertAlmostEqual(status.total_cost_usd, 0.7)
        self.assertEqual(results.recipe["title"], "latest recipe")
        self.assertIn("latest screening", report.markdown)
        self.assertIn("latest deep dive", report.markdown)
        fetch_all_mock.assert_not_awaited()

    async def test_run_recipe_uses_current_screening_data_without_db_read(self):
        status = AnalysisStatus(
            paper_id=7,
            overall_status="running",
            phases=[],
            progress_pct=0.0,
        )
        captured = {}

        async def _fake_call(prompt, **kwargs):
            captured["prompt"] = prompt
            captured.update(kwargs)
            return {
                "text": '{"title":"recipe","parameters":[],"steps":[],"materials":[],"equipment":[],"critical_notes":[],"confidence":0.8,"missing_info":[],"reproducibility_score":0.7}',
                "model": "gemini",
                "tokens_in": 10,
                "tokens_out": 20,
                "interaction_id": None,
            }

        with (
            patch("api.analysis_routes.fetch_one", new=AsyncMock(side_effect=AssertionError("DB reread should not happen"))),
            patch("api.analysis_routes._get_cached_phase_result", new=AsyncMock(return_value=None)),
            patch("api.analysis_routes.call_interaction", new=_fake_call),
            patch("api.analysis_routes._insert_analysis_result", new=AsyncMock()),
        ):
            await analysis_routes._run_recipe(
                7,
                "Recipe context body",
                status,
                screening_result_text='{"domain":"materials"}',
            )

        # 폴백 경로(pdf_uri 없음): 도메인 힌트 + 논문 텍스트가 프롬프트에 들어가고 store=False
        self.assertIn("DOMAIN-SPECIFIC PARAMETERS (Materials Science)", captured["prompt"])
        self.assertIs(captured["store"], False)

    async def test_run_recipe_skips_when_screening_signal_is_weak(self):
        status = AnalysisStatus(
            paper_id=7,
            overall_status="running",
            phases=[],
            progress_pct=0.0,
        )

        with (
            patch("api.analysis_routes._insert_analysis_result", new=AsyncMock()) as insert_mock,
            patch("api.analysis_routes.call_interaction", new=AsyncMock(side_effect=AssertionError("LLM call should be skipped"))),
        ):
            result = await analysis_routes._run_recipe(
                7,
                "Recipe context body",
                status,
                screening_result_text='{"relevance_score":0.2,"domain":"general","key_topics":[],"is_experimental":false}',
            )

        self.assertIn('"skipped": true', result["text"])
        insert_mock.assert_awaited_once()

    async def test_cached_phase_lookup_records_cache_event(self):
        cached = types.SimpleNamespace(
            result_text='{"summary":"cached"}',
            model_used="gemini-cache",
            tokens_in=12,
            tokens_out=34,
            cost_usd=0.56,
            input_hash="hash1234",
        )

        with (
            patch("api.analysis_routes.find_cached_phase_result", new=AsyncMock(return_value=cached)),
            patch("api.analysis_routes.execute_insert", new=AsyncMock()) as insert_mock,
        ):
            result = await analysis_routes._get_cached_phase_result(7, "screening", "input text")

        self.assertEqual(result["model"], "gemini-cache")
        insert_mock.assert_awaited_once()

    async def test_screening_uses_interactions_stateless(self):
        status = AnalysisStatus(
            paper_id=7,
            overall_status="running",
            phases=[],
            progress_pct=0.0,
        )
        calls = {}

        async def _fake_call(prompt, **kwargs):
            calls["prompt"] = prompt
            calls.update(kwargs)
            return {
                "text": '{"domain": "optics", "agent_recommended": "photon", '
                        '"relevance_score": 0.9, "key_topics": [], '
                        '"methodology_type": "experimental", "summary": "요약", '
                        '"is_experimental": true, "has_figures": true, '
                        '"estimated_complexity": "low"}',
                "model": "gemini-3.1-flash-lite",
                "tokens_in": 10,
                "tokens_out": 10,
                "interaction_id": None,
            }

        with (
            patch("api.analysis_routes._get_cached_phase_result", new=AsyncMock(return_value=None)),
            patch("api.analysis_routes.call_interaction", new=_fake_call),
            patch("api.analysis_routes._insert_analysis_result", new=AsyncMock()) as insert_mock,
        ):
            result = await analysis_routes._run_screening(7, "논문 텍스트", status)

        self.assertEqual(calls["model"], "gemini-3.1-flash-lite")
        self.assertEqual(calls["thinking_level"], "minimal")
        self.assertIs(calls["store"], False)
        self.assertIn("domain", calls["response_schema"]["properties"])
        # 프롬프트에서 JSON 골격/펜스 지시는 제거되었지만 논문 텍스트는 유지
        self.assertIn("논문 텍스트", calls["prompt"])
        self.assertNotIn("Return ONLY valid JSON", calls["prompt"])
        self.assertEqual(result["model"], "gemini-3.1-flash-lite")
        self.assertEqual(result["interaction_id"], None)
        insert_mock.assert_awaited_once()

    async def test_mermaid_uses_visualization_context_and_latest_recipe_row(self):
        paper = {"id": 7, "title": "Paper", "folder_name": "folder"}
        captured = {}

        async def _fake_call(prompt, **kwargs):
            captured["prompt"] = prompt
            return {"text": "flowchart TD\nA-->B", "model": "gemini", "tokens_in": 1, "tokens_out": 1}

        with (
            patch("api.analysis_routes.fetch_one", new=AsyncMock(return_value=paper)),
            patch("api.analysis_routes.get_paper_dir", return_value="/tmp/paper"),
            patch("api.analysis_routes.load_or_build_document_context", return_value={"phase_inputs": {"visualization": "VISUALIZATION-CONTEXT"}}),
            patch("api.analysis_routes.get_latest_completed_phase_row", new=AsyncMock(return_value=_row("recipe", '{"title":"recipe"}'))),
            patch("api.analysis_routes.call_interaction", new=_fake_call),
        ):
            response = await analysis_routes.get_mermaid(7)

        self.assertIn("VISUALIZATION-CONTEXT", captured["prompt"])
        self.assertIn("Recipe data", captured["prompt"])
        self.assertEqual(response.mermaid_code, "flowchart TD\nA-->B")

    async def test_experiment_plan_uses_recipe_phase_input_and_latest_rows(self):
        paper = {"id": 7, "title": "Paper", "folder_name": "folder", "domain": "materials"}
        captured = {}

        async def _fake_call(prompt, **kwargs):
            captured["prompt"] = prompt
            return {"text": '{"title":"plan"}', "model": "gemini", "tokens_in": 1, "tokens_out": 1}

        with (
            patch.dict(sys.modules, {"services.agents": agents_module}),
            patch("api.analysis_routes.fetch_one", new=AsyncMock(return_value=paper)),
            patch("api.analysis_routes.get_paper_dir", return_value="/tmp/paper"),
            patch("api.analysis_routes.load_or_build_document_context", return_value={"phase_inputs": {"recipe": "RECIPE-PHASE-INPUT"}}),
            patch("api.analysis_routes.get_latest_completed_phase_row", new=AsyncMock(side_effect=[
                _row("recipe", '{"title":"latest recipe"}'),
                _row("visual", '{"figure_count":3}'),
            ])),
            patch("api.analysis_routes.call_interaction", new=_fake_call),
            patch("api.analysis_routes.execute_insert", new=AsyncMock(return_value=1)),
        ):
            response = await analysis_routes._generate_experiment_plan_impl(7)

        self.assertIn("RECIPE-PHASE-INPUT", captured["prompt"])
        self.assertIn("시각 검증 결과", captured["prompt"])
        self.assertEqual(response["id"], 1)

    async def test_chat_uses_chat_phase_input(self):
        paper = {"id": 7, "title": "Paper", "folder_name": "folder", "domain": "materials"}
        latest_rows = {
            "screening": _row("screening", '{"summary":"screening"}'),
            "recipe": _row("recipe", '{"title":"recipe"}'),
        }
        captured = {}

        async def fake_stream(prompt, **kwargs):
            captured["prompt"] = prompt
            captured.update(kwargs)
            yield {"type": "token", "text": "첫"}
            yield {"type": "token", "text": "답"}
            yield {"type": "done", "tokens_in": 10, "tokens_out": 20,
                   "tokens_thought": 0, "interaction_id": None}

        with (
            patch.dict(sys.modules, {"services.agents": agents_module}),
            patch("api.analysis_routes.fetch_one", new=AsyncMock(return_value=paper)),
            patch("api.analysis_routes.get_paper_dir", return_value="/tmp/paper"),
            patch("api.analysis_routes.load_or_build_document_context", return_value={"phase_inputs": {"chat": "CHAT-CONTEXT"}}),
            patch("api.analysis_routes.get_latest_completed_phase_rows", new=AsyncMock(return_value=latest_rows)),
            patch("api.analysis_routes.stream_interaction", new=fake_stream),
            patch("api.analysis_routes.calc_cost", return_value=0.0001),
        ):
            response = await analysis_routes._chat_with_agent_impl(
                7,
                _FakeRequest({"message": "질문", "history": [{"role": "user", "content": "이전질문"}]}),
            )
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)

        # stateless 전환: stream_interaction으로 넘어간 계약 검증
        self.assertEqual(captured["model"], "gemini-3.5-flash")
        self.assertIs(captured["store"], False)
        system_prompt = captured["system_instruction"]
        self.assertIn("CHAT-CONTEXT", system_prompt)
        self.assertIn("스크리닝 결과", system_prompt)
        # 히스토리는 요청 텍스트로 조립되어 input에 포함
        self.assertIn("이전질문", captured["prompt"])
        self.assertIn("질문", captured["prompt"])
        # SSE 이벤트 스키마 불변: token(content) / done(tokens_in,tokens_out,cost_usd)
        joined = "".join(chunks)
        self.assertIn('"type": "token"', joined)
        self.assertIn('"content": "첫"', joined)
        self.assertIn('"type": "done"', joined)
        self.assertIn('"cost_usd"', joined)
        self.assertNotIn('"type": "error"', joined)


class FigurePromptContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_figure_prompt_uses_figure_detail_context_and_latest_phase_snippets(self):
        paper = {"id": 7, "title": "Paper", "folder_name": "folder", "domain": "materials", "agent_used": "crystal"}
        figure = {"id": 9, "paper_id": 7, "figure_num": "Figure 1", "caption": "Caption", "file_path": None}
        captured = {}

        async def _fake_call(prompt: str, **kwargs):
            captured["prompt"] = prompt
            return {"text": "설명", "model": "gemini", "tokens_in": 1, "tokens_out": 1}

        with (
            patch("api.figure_service.fetch_one", new=AsyncMock(side_effect=[paper, figure])),
            patch("api.figure_service.fetch_all", new=AsyncMock(return_value=[{"figure_num": "Figure 1", "caption": "Caption"}])),
            patch("api.figure_service.get_paper_dir", return_value="/tmp/paper"),
            patch("api.figure_service.ensure_text_artifacts_async", new=AsyncMock()),
            patch("api.figure_service.load_or_build_document_context", return_value={"phase_inputs": {"figure_detail": "FIGURE-DETAIL-CONTEXT"}}),
            patch(
                "api.figure_service.get_latest_completed_phase_rows",
                new=AsyncMock(
                    return_value={
                        "visual": _row("visual", '{"figure_count": 3}'),
                        "recipe": _row("recipe", '{"title": "recipe"}'),
                        "deep_dive": _row("deep_dive", '{"detailed_analysis":"deep"}'),
                    }
                ),
            ),
            patch("api.figure_service.call_interaction", new=_fake_call),
            patch("api.figure_service.execute_update", new=AsyncMock()),
        ):
            response = await figure_service.explain_figure_handler(7, 9)

        self.assertIn("FIGURE-DETAIL-CONTEXT", captured["prompt"])
        self.assertIn("--- visual ---", captured["prompt"])
        self.assertNotIn("--- PAPER FULL TEXT ---", captured["prompt"])
        self.assertEqual(response.explanation, "설명")


class ChainStageTests(unittest.IsolatedAsyncioTestCase):
    """상태 유지 체인 전환의 핵심 계약 검증: 체인 연결 / PDF 첫 호출 / 폴백."""

    def _capturing_fake(self, captured):
        async def _fake(contents, **kwargs):
            captured["contents"] = contents
            captured.update(kwargs)
            return {"text": '{"quality_summary":"ok","key_findings_from_visuals":[]}',
                    "model": "gemini-3.5-flash", "tokens_in": 5, "tokens_out": 5,
                    "interaction_id": "int_new"}
        return _fake

    async def test_chain_first_call_includes_pdf_document(self):
        captured = {}
        with patch("api.analysis_routes.call_interaction", new=self._capturing_fake(captured)):
            result = await analysis_routes._run_chain_stage(
                phase="visual",
                prompt_chain="CHAIN-PROMPT",
                prompt_fallback="FALLBACK-PROMPT",
                system_instruction="SI",
                previous_interaction_id=None,
                pdf_uri="files/uri-123",
                response_schema={"type": "object"},
            )
        # 첫 호출은 PDF 문서 + 텍스트 content 리스트, store=True, previous=None
        self.assertIsInstance(captured["contents"], list)
        self.assertEqual(captured["contents"][0]["type"], "document")
        self.assertEqual(captured["contents"][0]["uri"], "files/uri-123")
        self.assertEqual(captured["contents"][1]["text"], "CHAIN-PROMPT")
        self.assertIs(captured["store"], True)
        self.assertIsNone(captured["previous_interaction_id"])
        self.assertEqual(captured["thinking_level"], "low")
        self.assertEqual(result["interaction_id"], "int_new")

    async def test_chain_continuation_uses_previous_id_and_no_pdf(self):
        captured = {}
        with patch("api.analysis_routes.call_interaction", new=self._capturing_fake(captured)):
            await analysis_routes._run_chain_stage(
                phase="deep_dive",
                prompt_chain="CHAIN-PROMPT",
                prompt_fallback="FALLBACK-PROMPT",
                system_instruction="SI",
                previous_interaction_id="int_prev",
                pdf_uri="files/uri-123",
                response_schema={"type": "object"},
            )
        # 이후 스테이지는 지시문만(문자열), previous_interaction_id로 서버 상태 이어감
        self.assertEqual(captured["contents"], "CHAIN-PROMPT")
        self.assertEqual(captured["previous_interaction_id"], "int_prev")
        self.assertIs(captured["store"], True)
        self.assertEqual(captured["thinking_level"], "high")

    async def test_fallback_is_stateless_text_path(self):
        captured = {}
        with patch("api.analysis_routes.call_interaction", new=self._capturing_fake(captured)):
            await analysis_routes._run_chain_stage(
                phase="recipe",
                prompt_chain="CHAIN-PROMPT",
                prompt_fallback="FALLBACK-PROMPT",
                system_instruction="SI",
                previous_interaction_id=None,
                pdf_uri=None,
                response_schema={"type": "object"},
            )
        # PDF 없음 → 텍스트 프롬프트, store=False, previous_interaction_id 미전달
        self.assertEqual(captured["contents"], "FALLBACK-PROMPT")
        self.assertIs(captured["store"], False)
        self.assertNotIn("previous_interaction_id", captured)
        self.assertEqual(captured["thinking_level"], "medium")

    async def test_recipe_stage_forwards_chain_params(self):
        status = AnalysisStatus(paper_id=7, overall_status="running", phases=[], progress_pct=0.0)
        captured = {}

        async def _fake_call(contents, **kwargs):
            captured["contents"] = contents
            captured.update(kwargs)
            return {"text": '{"title":"r","objective":"o","parameters":[],"steps":[]}',
                    "model": "gemini-3.5-flash", "tokens_in": 1, "tokens_out": 1,
                    "interaction_id": "int_recipe"}

        insert_mock = AsyncMock()
        with (
            patch("api.analysis_routes._get_cached_phase_result", new=AsyncMock(return_value=None)),
            patch("api.analysis_routes.call_interaction", new=_fake_call),
            patch("api.analysis_routes._insert_analysis_result", new=insert_mock),
        ):
            await analysis_routes._run_recipe(
                7,
                "Recipe body",
                status,
                screening_result_text='{"domain":"materials"}',
                system_instruction="SI-CHAIN",
                previous_interaction_id="int_visual",
                pdf_uri="files/uri-123",
            )

        # 체인 모드: 이전 스테이지 interaction_id를 그대로 이어받고, 지시문만 전송
        self.assertEqual(captured["previous_interaction_id"], "int_visual")
        self.assertEqual(captured["system_instruction"], "SI-CHAIN")
        self.assertIsInstance(captured["contents"], str)  # 지시문만(대용량 텍스트 미포함)
        self.assertIs(captured["store"], True)
        # 완료 시 interaction_id를 analysis_results에 저장
        self.assertEqual(insert_mock.await_args.kwargs.get("interaction_id"), "int_recipe")


class _OrchStubProfile:
    personality = "precise"


class _OrchStubAgent:
    name = "crystal"
    profile = _OrchStubProfile()
    description = "정밀한 페르소나"


class FullAnalysisChainOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    """`_run_full_analysis` 오케스트레이션: 체인 선형 전진 + 캐시 히트 재시작 복원 검증.

    스크리닝·인용은 heavy/비초점이라 러너를 목킹하고, 체인 fix 대상인
    visual→recipe→deep_dive→viz 경로는 실제 실행하면서 call_interaction만 목킹한다.
    """

    _SCREENING_TEXT = (
        '{"domain":"materials","relevance_score":0.9,"summary":"요약",'
        '"is_experimental":true,"key_topics":["박막","증착"]}'
    )
    _CITATION_TEXT = '{"citation_summary":"인용 분석 결과 텍스트"}'
    _VISUAL_CACHED_TEXT = '{"quality_summary":"CACHED-VISUAL-MARKER","key_findings_from_visuals":[]}'

    def _orch_call_fake(self, calls):
        state = {"n": 0}

        async def _fake(contents, **kwargs):
            state["n"] += 1
            iid = f"int_{state['n']}"
            calls.append({
                "contents": contents,
                "previous_interaction_id": kwargs.get("previous_interaction_id"),
                "store": kwargs.get("store"),
                "interaction_id": iid,
            })
            return {
                "text": '{"visualizations": []}',
                "model": "gemini-3.5-flash",
                "tokens_in": 1,
                "tokens_out": 1,
                "interaction_id": iid,
            }

        return _fake

    @contextlib.contextmanager
    def _orchestration_patches(self, *, cache_fake, call_fake, visual_result=None):
        paper = {
            "id": 7,
            "folder_name": "folder",
            "authors": "Kim",
            "domain": "materials",
            "analysis_focus": None,
            "explanation_level": "masters",
            "title": "Paper",
        }
        phase_inputs = {
            "screening": "SCREENING-INPUT",
            "citation_body": "CITE-BODY",
            "citation_references": "CITE-REFS",
            "visual": "VISUAL-INPUT",
            "recipe": "RECIPE-INPUT",
            "deep_dive": "DEEPDIVE-INPUT",
            "visualization": "VIZ-INPUT",
        }
        figures = [{
            "figure_num": "Figure 1", "quality": "good",
            "confidence": 0.9, "resolver_version": "v1",
        }]
        tables = []

        analysis_context_stub = types.ModuleType("api.analysis_context")
        analysis_context_stub.build_chain_system_instruction = lambda **kw: "SYS-INSTRUCTION"

        async def _upload_stub(paper_id, path):
            return "files/uri-abc"

        interactions_stub = types.ModuleType("services.llm.interactions_client")
        interactions_stub.upload_pdf_for_paper = _upload_stub

        agents_stub = types.ModuleType("services.agents")
        agents_stub.get_agent_for_domain = lambda domain: _OrchStubAgent()

        async def _settings_stub(*a, **k):
            return {}

        settings_stub = types.ModuleType("api.settings")
        settings_stub.get_raw_settings = _settings_stub

        screening_mock = AsyncMock(return_value={
            "text": self._SCREENING_TEXT, "model": "g", "tokens_in": 1,
            "tokens_out": 1, "interaction_id": None,
        })
        citation_mock = AsyncMock(return_value={
            "text": self._CITATION_TEXT, "model": "g", "tokens_in": 1,
            "tokens_out": 1, "interaction_id": None,
        })
        visual_ready_contract = (
            {"visual_ready": True, "visual_state": "ready", "visual_error": None,
             "artifacts_ready": True, "artifacts_error": None},
            1, 0,
        )

        stack = contextlib.ExitStack()
        stack.enter_context(patch.dict(sys.modules, {
            "api.analysis_context": analysis_context_stub,
            "services.llm.interactions_client": interactions_stub,
            "services.agents": agents_stub,
            "api.settings": settings_stub,
        }))
        stack.enter_context(patch("api.analysis_routes.fetch_one", new=AsyncMock(return_value=paper)))
        stack.enter_context(patch("api.analysis_routes.fetch_all", new=AsyncMock(side_effect=[figures, tables])))
        stack.enter_context(patch("api.analysis_routes.get_paper_dir", return_value="/tmp/paper"))
        stack.enter_context(patch("api.analysis_routes.load_or_build_document_context",
                                  return_value={"phase_inputs": phase_inputs, "sections": {}}))
        stack.enter_context(patch("api.analysis_routes.schedule_paper_artifacts_refresh", new=AsyncMock()))
        stack.enter_context(patch("api.analysis_routes.execute_update", new=AsyncMock()))
        stack.enter_context(patch("api.analysis_routes.execute_insert", new=AsyncMock(return_value=1)))
        stack.enter_context(patch("api.analysis_routes._insert_analysis_result", new=AsyncMock()))
        stack.enter_context(patch("api.analysis_routes._find_paper_pdf", return_value="/tmp/paper/x.pdf"))
        stack.enter_context(patch("api.analysis_routes._run_screening", new=screening_mock))
        stack.enter_context(patch("api.analysis_routes._run_citation", new=citation_mock))
        stack.enter_context(patch("api.analysis_routes._get_visual_contract",
                                  new=AsyncMock(return_value=visual_ready_contract)))
        stack.enter_context(patch("api.analysis_routes._get_cached_phase_result", new=cache_fake))
        stack.enter_context(patch("api.analysis_routes.call_interaction", new=call_fake))
        if visual_result is not None:
            stack.enter_context(patch("api.analysis_routes._run_visual",
                                      new=AsyncMock(return_value=visual_result)))
        with stack:
            yield

    async def test_chain_forwards_previous_interaction_id_linearly(self):
        calls = []
        call_fake = self._orch_call_fake(calls)

        async def _cache_none(*a, **k):
            return None

        with self._orchestration_patches(cache_fake=_cache_none, call_fake=call_fake):
            await analysis_routes._run_full_analysis(7)

        # 체인 스테이지(store=True) 호출만 추출: visual→recipe→deep_dive→viz
        chain_calls = [c for c in calls if c["store"] is True]
        self.assertEqual(len(chain_calls), 4)
        # 첫 스테이지(visual)는 PDF 문서를 포함하고 previous=None
        self.assertIsNone(chain_calls[0]["previous_interaction_id"])
        self.assertIsInstance(chain_calls[0]["contents"], list)
        self.assertEqual(chain_calls[0]["contents"][0]["type"], "document")
        # 각 스테이지가 직전 스테이지의 interaction_id를 이어받음 (선형 전진)
        self.assertEqual(chain_calls[1]["previous_interaction_id"], chain_calls[0]["interaction_id"])
        self.assertEqual(chain_calls[2]["previous_interaction_id"], chain_calls[1]["interaction_id"])
        self.assertEqual(chain_calls[3]["previous_interaction_id"], chain_calls[2]["interaction_id"])
        # 체인 이어감 스테이지는 지시문 문자열만 전송(대용량 재전송 없음)
        self.assertIsInstance(chain_calls[1]["contents"], str)

    async def test_cache_hit_restart_reincludes_pdf_and_prev_context(self):
        calls = []
        call_fake = self._orch_call_fake(calls)

        async def _cache_visual_hit(paper_id, phase, input_text):
            if phase == "visual":
                return {
                    "text": self._VISUAL_CACHED_TEXT, "model": "gemini-cache",
                    "tokens_in": 1, "tokens_out": 1, "cost_usd": 0.01, "input_hash": "h",
                }
            return None

        with self._orchestration_patches(cache_fake=_cache_visual_hit, call_fake=call_fake):
            await analysis_routes._run_full_analysis(7)

        # visual 캐시 히트 → interaction_id 유실 → recipe가 체인 재시작 케이스로 첫 call_interaction
        self.assertTrue(calls)
        recipe_call = calls[0]
        self.assertIsNone(recipe_call["previous_interaction_id"])
        # PDF document dict가 다시 포함되고
        self.assertIsInstance(recipe_call["contents"], list)
        self.assertEqual(recipe_call["contents"][0]["type"], "document")
        self.assertEqual(recipe_call["contents"][0]["uri"], "files/uri-abc")
        # 캐시된 visual 결과 텍스트가 프롬프트에 복원됨
        restored_text = recipe_call["contents"][1]["text"]
        self.assertIn("CACHED-VISUAL-MARKER", restored_text)


class RewriteSectionTests(unittest.IsolatedAsyncioTestCase):
    """섹션 재작성(수준 변경 = 체인 연장) 엔드포인트 계약 검증."""

    def _wiring(self, *, chain_id="int_chain_prev"):
        """fetch_one/_insert_analysis_result를 인메모리 캐시로 시뮬레이션한다.

        - cache 조회(phase에 '#level=' 포함): cache_store에서 반환(첫 요청 None → 두 번째 히트)
        - original 조회(원문 phase): 원문 result/interaction_id 반환
        - chain_id 조회(params 길이 1): 가장 최근 non-null interaction_id 반환(None이면 폴백)
        """
        cache_store: dict = {}

        async def fake_fetch_one(sql, params):
            if len(params) == 1:  # 최근 non-null interaction_id 조회
                return {"interaction_id": chain_id} if chain_id else None
            phase_param = params[1]
            if "#level=" in phase_param:  # 캐시 조회
                return cache_store.get(phase_param)
            return {"result": "원문 딥다이브 분석", "interaction_id": "int_orig"}

        async def fake_insert(paper_id, phase, result_text, *args, **kwargs):
            cache_store[phase] = {"result": result_text}

        return fake_fetch_one, fake_insert, cache_store

    async def test_rewrite_section_extends_chain(self):
        captured = {}

        async def fake_call(prompt, **kwargs):
            captured["prompt"] = prompt
            captured.update(kwargs)
            return {"text": "쉬운 설명", "model": "gemini-3.5-flash",
                    "tokens_in": 10, "tokens_out": 10, "interaction_id": "int_rw"}

        fake_fetch_one, fake_insert, _ = self._wiring()

        with (
            patch("api.analysis_routes.fetch_one", new=fake_fetch_one),
            patch("api.analysis_routes.call_interaction", new=fake_call),
            patch("api.analysis_routes._insert_analysis_result", new=fake_insert),
            patch("api.analysis_routes.calc_cost", return_value=0.0),
        ):
            req = analysis_routes.RewriteRequest(phase="deep_dive", level="high")
            resp = await analysis_routes.rewrite_section(7, req)
            self.assertEqual(resp["text"], "쉬운 설명")
            self.assertIs(resp["cached"], False)
            # 체인 연장: previous_interaction_id로 최근 interaction_id를 이어받음
            self.assertEqual(captured["previous_interaction_id"], "int_chain_prev")
            self.assertEqual(captured["thinking_level"], "low")
            self.assertEqual(captured["model"], "gemini-3.5-flash")

            # 두 번째 호출은 캐시 히트
            req2 = analysis_routes.RewriteRequest(phase="deep_dive", level="high")
            resp2 = await analysis_routes.rewrite_section(7, req2)
            self.assertIs(resp2["cached"], True)
            self.assertEqual(resp2["text"], "쉬운 설명")

    async def test_rewrite_invalid_level_rejected(self):
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            analysis_routes.RewriteRequest(phase="deep_dive", level="toddler")

    async def test_rewrite_invalid_phase_rejected(self):
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            analysis_routes.RewriteRequest(phase="citation", level="high")

    async def test_rewrite_falls_back_to_stateless_when_no_chain(self):
        captured = {}

        async def fake_call(prompt, **kwargs):
            captured["prompt"] = prompt
            captured.update(kwargs)
            return {"text": "폴백 설명", "model": "gemini-3.5-flash",
                    "tokens_in": 5, "tokens_out": 5, "interaction_id": None}

        # chain_id=None → 최근 non-null interaction_id 없음 → 폴백 경로
        fake_fetch_one, fake_insert, _ = self._wiring(chain_id=None)

        with (
            patch("api.analysis_routes.fetch_one", new=fake_fetch_one),
            patch("api.analysis_routes.call_interaction", new=fake_call),
            patch("api.analysis_routes._insert_analysis_result", new=fake_insert),
            patch("api.analysis_routes.calc_cost", return_value=0.0),
        ):
            req = analysis_routes.RewriteRequest(phase="deep_dive", level="elementary")
            resp = await analysis_routes.rewrite_section(7, req)

        self.assertEqual(resp["text"], "폴백 설명")
        self.assertIs(resp["cached"], False)
        # 폴백: stateless(store=False), 원문 텍스트를 프롬프트에 포함, 체인 id 미전달
        self.assertIs(captured["store"], False)
        self.assertNotIn("previous_interaction_id", captured)
        self.assertIn("원문 딥다이브 분석", captured["prompt"])


if __name__ == "__main__":
    unittest.main()
