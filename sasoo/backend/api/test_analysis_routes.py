import json
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

        async def _fake_call(prompt: str, **kwargs):
            captured["prompt"] = prompt
            return {
                "text": '{"title":"recipe","parameters":[],"steps":[],"materials":[],"equipment":[],"critical_notes":[],"confidence":0.8,"missing_info":[],"reproducibility_score":0.7}',
                "model": "gemini",
                "tokens_in": 10,
                "tokens_out": 20,
            }

        with (
            patch("api.analysis_routes.fetch_one", new=AsyncMock(side_effect=AssertionError("DB reread should not happen"))),
            patch("api.analysis_routes._get_cached_phase_result", new=AsyncMock(return_value=None)),
            patch("api.analysis_routes._call_gemini", new=_fake_call),
            patch("api.analysis_routes._insert_analysis_result", new=AsyncMock()),
        ):
            await analysis_routes._run_recipe(
                7,
                "Recipe context body",
                status,
                screening_result_text='{"domain":"materials"}',
            )

        self.assertIn("DOMAIN-SPECIFIC PARAMETERS (Materials Science)", captured["prompt"])

    async def test_run_recipe_skips_when_screening_signal_is_weak(self):
        status = AnalysisStatus(
            paper_id=7,
            overall_status="running",
            phases=[],
            progress_pct=0.0,
        )

        with (
            patch("api.analysis_routes._insert_analysis_result", new=AsyncMock()) as insert_mock,
            patch("api.analysis_routes._call_gemini", new=AsyncMock(side_effect=AssertionError("LLM call should be skipped"))),
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

    async def test_store_visualization_progress_updates_existing_row(self):
        items = [
            {"id": 1, "title": "A", "status": "completed", "cost_usd": 0.02},
            {"id": 2, "title": "B", "status": "completed", "cost_usd": 0.03},
        ]

        with (
            patch("api.analysis_routes.fetch_one", new=AsyncMock(return_value={"id": 42})),
            patch("api.analysis_routes.execute_update", new=AsyncMock(return_value=1)) as update_mock,
            patch("api.analysis_routes._insert_analysis_result", new=AsyncMock()) as insert_mock,
        ):
            await analysis_routes._store_visualization_progress(7, items, "cache-input", done=False)

        update_mock.assert_awaited_once()
        args = update_mock.call_args.args
        self.assertIn("UPDATE analysis_results", args[0])
        self.assertIn("cost_usd = ?", args[0])
        self.assertEqual(args[1][-1], 42)
        self.assertAlmostEqual(args[1][-2], 0.05)
        insert_mock.assert_not_awaited()

    async def test_store_visualization_progress_inserts_when_no_row(self):
        items = [
            {"id": 1, "title": "A", "status": "completed", "cost_usd": 0.07},
            {"id": 2, "title": "B", "status": "error"},
        ]

        with (
            patch("api.analysis_routes.fetch_one", new=AsyncMock(return_value=None)),
            patch("api.analysis_routes.execute_update", new=AsyncMock()) as update_mock,
            patch("api.analysis_routes._insert_analysis_result", new=AsyncMock()) as insert_mock,
        ):
            await analysis_routes._store_visualization_progress(7, items, "cache-input", done=True)

        insert_mock.assert_awaited_once()
        self.assertEqual(insert_mock.call_args.args[0], 7)
        self.assertEqual(insert_mock.call_args.args[1], "visualization")
        self.assertAlmostEqual(insert_mock.call_args.args[6], 0.07)
        update_mock.assert_not_awaited()

    async def test_store_visualization_progress_inserts_new_row_for_different_input_hash(self):
        # An existing row belongs to a *different* run (different input_hash). The UPDATE
        # SELECT must not find it, so the store call falls through to INSERT instead of
        # overwriting the previous run's (possibly completed) row.
        items = [{"id": 1, "title": "A", "status": "completed"}]

        with (
            patch("api.analysis_routes.fetch_one", new=AsyncMock(return_value=None)) as fetch_one_mock,
            patch("api.analysis_routes.execute_update", new=AsyncMock()) as update_mock,
            patch("api.analysis_routes._insert_analysis_result", new=AsyncMock()) as insert_mock,
        ):
            await analysis_routes._store_visualization_progress(7, items, "new-run-cache-input", done=False)

        fetch_one_mock.assert_awaited_once()
        query, params = fetch_one_mock.call_args.args
        self.assertIn("input_hash = ?", query)
        self.assertEqual(params[0], 7)
        insert_mock.assert_awaited_once()
        self.assertEqual(insert_mock.call_args.args[0], 7)
        self.assertEqual(insert_mock.call_args.args[1], "visualization")
        update_mock.assert_not_awaited()

    async def test_run_visualizations_ignores_incomplete_cache_hit(self):
        # A checkpoint row saved mid-run (complete=False) shares the same input_hash as a
        # full run. Treating it as a cache hit would report a crashed/partial run as done.
        status = AnalysisStatus(
            paper_id=7,
            overall_status="running",
            phases=[],
            progress_pct=0.0,
        )
        stale_partial_payload = json.dumps(
            {"items": [{"id": 1, "title": "stale partial", "status": "completed"}], "complete": False}
        )

        with (
            patch(
                "api.analysis_routes._get_cached_phase_result",
                new=AsyncMock(return_value={"text": stale_partial_payload}),
            ),
            patch("api.analysis_routes._plan_visualizations", new=AsyncMock(return_value=[])) as plan_mock,
            patch("api.analysis_routes._store_visualization_progress", new=AsyncMock()) as store_mock,
        ):
            result = await analysis_routes._run_visualizations(
                7, "viz input", "folder", [], "recipe result", "deep dive result", status,
            )

        # Cache was rejected, so the regeneration path (plan → store final) ran instead of
        # short-circuiting with the stale cached items.
        plan_mock.assert_awaited_once()
        self.assertEqual(result, [])
        store_mock.assert_awaited_once()
        self.assertEqual(store_mock.call_args.kwargs.get("done"), True)  # done=True final save

    async def test_mermaid_uses_visualization_context_and_latest_recipe_row(self):
        paper = {"id": 7, "title": "Paper", "folder_name": "folder"}
        captured = {}

        async def _fake_call(prompt: str, **kwargs):
            captured["prompt"] = prompt
            return {"text": "flowchart TD\nA-->B", "model": "gemini", "tokens_in": 1, "tokens_out": 1}

        with (
            patch("api.analysis_routes.fetch_one", new=AsyncMock(return_value=paper)),
            patch("api.analysis_routes.get_paper_dir", return_value="/tmp/paper"),
            patch("api.analysis_routes.load_or_build_document_context", return_value={"phase_inputs": {"visualization": "VISUALIZATION-CONTEXT"}}),
            patch("api.analysis_routes.get_latest_completed_phase_row", new=AsyncMock(return_value=_row("recipe", '{"title":"recipe"}'))),
            patch("api.analysis_routes._call_gemini", new=_fake_call),
        ):
            response = await analysis_routes.get_mermaid(7)

        self.assertIn("VISUALIZATION-CONTEXT", captured["prompt"])
        self.assertIn("Recipe data", captured["prompt"])
        self.assertEqual(response.mermaid_code, "flowchart TD\nA-->B")

    async def test_experiment_plan_uses_recipe_phase_input_and_latest_rows(self):
        paper = {"id": 7, "title": "Paper", "folder_name": "folder", "domain": "materials"}
        captured = {}

        async def _fake_call(prompt: str, **kwargs):
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
            patch("api.analysis_routes._call_gemini", new=_fake_call),
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

        class DummyPart:
            @staticmethod
            def from_text(text: str):
                return {"text": text}

        class DummyContent:
            def __init__(self, role, parts):
                self.role = role
                self.parts = parts

        class DummyModels:
            def generate_content_stream(self, *, model, contents, config):
                captured["model"] = model
                captured["contents"] = contents
                captured["config"] = config
                usage = types.SimpleNamespace(prompt_token_count=10, candidates_token_count=20)
                return [
                    types.SimpleNamespace(text="첫", usage_metadata=usage),
                    types.SimpleNamespace(text="답", usage_metadata=usage),
                ]

        class DummyClient:
            def __init__(self):
                self.models = DummyModels()

        genai_types = types.SimpleNamespace(
            Content=DummyContent,
            Part=DummyPart,
            GenerateContentConfig=lambda **kwargs: kwargs,
        )
        google_module = types.ModuleType("google")
        genai_module = types.ModuleType("google.genai")
        genai_module.types = genai_types
        google_module.genai = genai_module

        with (
            patch.dict(sys.modules, {"services.agents": agents_module}),
            patch("api.analysis_routes.fetch_one", new=AsyncMock(return_value=paper)),
            patch("api.analysis_routes.get_paper_dir", return_value="/tmp/paper"),
            patch("api.analysis_routes.load_or_build_document_context", return_value={"phase_inputs": {"chat": "CHAT-CONTEXT"}}),
            patch("api.analysis_routes.get_latest_completed_phase_rows", new=AsyncMock(return_value=latest_rows)),
            patch("api.analysis_routes._get_gemini_client", return_value=DummyClient()),
            patch.dict(sys.modules, {"google": google_module, "google.genai": genai_module}),
        ):
            response = await analysis_routes._chat_with_agent_impl(
                7,
                _FakeRequest({"message": "질문", "history": []}),
            )
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)

        system_prompt = captured["config"]["system_instruction"]
        self.assertIn("CHAT-CONTEXT", system_prompt)
        self.assertIn("스크리닝 결과", system_prompt)
        self.assertTrue(any("done" in str(chunk) for chunk in chunks))


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
            patch("api.figure_service._call_gemini", new=_fake_call),
            patch("api.figure_service.execute_update", new=AsyncMock()),
        ):
            response = await figure_service.explain_figure_handler(7, 9)

        self.assertIn("FIGURE-DETAIL-CONTEXT", captured["prompt"])
        self.assertIn("--- visual ---", captured["prompt"])
        self.assertNotIn("--- PAPER FULL TEXT ---", captured["prompt"])
        self.assertEqual(response.explanation, "설명")


if __name__ == "__main__":
    unittest.main()
