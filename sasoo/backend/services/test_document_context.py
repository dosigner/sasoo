import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

_TEMP_MODULE_NAMES = (
    "fitz",
    "PIL",
    "aiosqlite",
    "services.odl_parser",
)
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in _TEMP_MODULE_NAMES}

sys.modules.setdefault("fitz", types.SimpleNamespace())
pil_module = types.ModuleType("PIL")
pil_module.Image = types.SimpleNamespace()
sys.modules.setdefault("PIL", pil_module)
aiosqlite_module = types.ModuleType("aiosqlite")
aiosqlite_module.Connection = object
aiosqlite_module.Row = dict

async def _unused_connect(*args, **kwargs):
    raise RuntimeError("aiosqlite.connect should not be called in these tests")

aiosqlite_module.connect = _unused_connect
sys.modules.setdefault("aiosqlite", aiosqlite_module)
odl_parser_module = types.ModuleType("services.odl_parser")

class _StubOdlParserError(RuntimeError):
    pass

class _StubOdlRuntimeError(_StubOdlParserError):
    pass

def _stub_explain_odl_failure(exc):
    return 500, str(exc)

async def _stub_schedule_refresh(*args, **kwargs):
    return None

odl_parser_module.OdlParserError = _StubOdlParserError
odl_parser_module.OdlRuntimeError = _StubOdlRuntimeError
odl_parser_module.ensure_text_artifacts = lambda *args, **kwargs: {}
odl_parser_module.get_pdf_signature = lambda pdf_path: {
    "pdf_mtime_ns": pdf_path.stat().st_mtime_ns,
    "pdf_size": pdf_path.stat().st_size,
}
odl_parser_module.explain_odl_failure = _stub_explain_odl_failure
odl_parser_module.get_artifact_refresh_error = lambda paper_id: None
odl_parser_module.is_artifact_refresh_running = lambda paper_id: False
odl_parser_module.paper_text_is_current = lambda paper_dir: True
odl_parser_module.paper_visuals_are_current = lambda paper_dir: True
odl_parser_module.schedule_paper_artifacts_refresh = _stub_schedule_refresh
sys.modules.setdefault("services.odl_parser", odl_parser_module)

from services.artifact_status import resolve_artifact_status_contract
from services.document_context import (
    CONTEXT_BUILDER_VERSION,
    DOCUMENT_CONTEXT_FILENAME,
    build_document_context_from_text,
    compute_input_hash,
    find_cached_phase_result,
    load_or_build_document_context,
)
from services.section_splitter import SectionSplitter

for _module_name, _original in _ORIGINAL_MODULES.items():
    if _original is None:
        sys.modules.pop(_module_name, None)
    else:
        sys.modules[_module_name] = _original


class DocumentContextTests(unittest.TestCase):
    def test_reuses_current_document_context_sidecar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paper_dir = Path(tmpdir)
            (paper_dir / "paper.pdf").write_bytes(b"%PDF-1.4\n")
            manifest = {
                "full_text": "ABSTRACT\nLaser power was 10 mW.\nCONCLUSION\nIt worked.",
                "parser_version": "odl-v3",
            }

            with patch("services.document_context.ensure_text_artifacts", return_value=manifest):
                first = load_or_build_document_context(paper_dir)
                self.assertEqual(first["context_builder_version"], CONTEXT_BUILDER_VERSION)

                sidecar_path = paper_dir / DOCUMENT_CONTEXT_FILENAME
                cached = json.loads(sidecar_path.read_text(encoding="utf-8"))
                cached["sentinel"] = "reuse-hit"
                sidecar_path.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")

                second = load_or_build_document_context(paper_dir)

            self.assertEqual(second["sentinel"], "reuse-hit")

    def test_rebuilds_when_builder_version_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paper_dir = Path(tmpdir)
            (paper_dir / "paper.pdf").write_bytes(b"%PDF-1.4\n")
            manifest = {
                "full_text": "ABSTRACT\nVoltage was 5 V.\nCONCLUSION\nDone.",
                "parser_version": "odl-v3",
            }

            with patch("services.document_context.ensure_text_artifacts", return_value=manifest):
                load_or_build_document_context(paper_dir)

                sidecar_path = paper_dir / DOCUMENT_CONTEXT_FILENAME
                cached = json.loads(sidecar_path.read_text(encoding="utf-8"))
                cached["context_builder_version"] = "old-version"
                cached["sentinel"] = "stale"
                sidecar_path.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")

                rebuilt = load_or_build_document_context(paper_dir)

            self.assertEqual(rebuilt["context_builder_version"], CONTEXT_BUILDER_VERSION)
            self.assertNotIn("sentinel", rebuilt)
            self.assertIn("phase_inputs", rebuilt)
            self.assertIn("quantitative_candidates", rebuilt)

    def test_phase_inputs_include_chat_and_figure_detail(self):
        context = build_document_context_from_text(
            """
ABSTRACT
This paper studies laser annealing.
INTRODUCTION
We discuss motivation.
METHODS
The sample was heated to 500 C for 10 min.
RESULTS
Efficiency improved to 92%.
DISCUSSION
The mechanism is discussed here.
CONCLUSION
It worked.
            """.strip()
        )

        phase_inputs = context["phase_inputs"]
        self.assertIn("chat", phase_inputs)
        self.assertIn("figure_detail", phase_inputs)
        self.assertIn("METHOD", phase_inputs["chat"])
        self.assertIn("RESULTS", phase_inputs["figure_detail"])

    def test_chat_and_figure_detail_are_bounded_and_reproducible(self):
        long_text = (
            "ABSTRACT\n" + ("A" * 6000) +
            "\nMETHODS\n" + ("B" * 6000) +
            "\nRESULTS\n" + ("C" * 6000) +
            "\nDISCUSSION\n" + ("D" * 6000)
        )

        first = build_document_context_from_text(long_text)
        second = build_document_context_from_text(long_text)

        self.assertEqual(first["phase_inputs"]["chat"], second["phase_inputs"]["chat"])
        self.assertEqual(first["phase_inputs"]["figure_detail"], second["phase_inputs"]["figure_detail"])
        self.assertLessEqual(len(first["phase_inputs"]["chat"]), 7015)
        self.assertLessEqual(len(first["phase_inputs"]["figure_detail"]), 9015)

    def test_reference_recovery_handles_stray_entries_and_supplementary_tail(self):
        splitter = SectionSplitter()
        sections = {
            "conclusion": """
The system remains compact and practical for portable adaptive optics deployment.
1. R. K. Tyson, Introduction to Adaptive Optics, 2nd ed. (SPIE Press, 2000).
2. M. J. Booth, Adaptive optical microscopy, Light: Science & Applications 3, e165 (2014).
3. A. Roorda and D. R. Williams, Nature 397, 520-522 (1999).
4. Bonora S, Pilar J, Lucianetti A, High Power Laser Science and Engineering 4, e16 (2016).
            """.strip(),
            "references": """
--- Page 12 ---
5. Ragazzoni, R., Marchetti, E. & Rigaut, F. Astron. Astrophys. 342, L53-L56 (1999).
6. Ragazzoni, R., Marchetti, E. & Valente, G. Nature 403, 54-56 (2000). https://doi.org/10.1038/47425
Supplementary materials
Deformable lenses and control matrix derivation.
            """.strip(),
        }

        refs = splitter.get_references_text(sections)
        body = splitter.get_body_text_without_references(sections)

        self.assertIn("1. R. K. Tyson", refs)
        self.assertIn("6. Ragazzoni, R., Marchetti, E. & Valente, G.", refs)
        self.assertNotIn("Supplementary materials", refs)
        self.assertLess(refs.index("1. R. K. Tyson"), refs.index("5. Ragazzoni"))
        self.assertNotIn("1. R. K. Tyson", body)
        self.assertNotIn("4. Bonora S", body)


class ArtifactStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_visuals_with_rows_schedule_refresh(self):
        schedule_refresh = AsyncMock()
        with (
            patch("services.artifact_status.paper_text_is_current", return_value=True),
            patch("services.artifact_status.paper_visuals_are_current", return_value=False),
            patch("services.artifact_status.get_artifact_refresh_error", return_value=None),
            patch("services.artifact_status.is_artifact_refresh_running", side_effect=[False, True]),
            patch("services.artifact_status.schedule_paper_artifacts_refresh", new=schedule_refresh),
        ):
            contract = await resolve_artifact_status_contract(
                paper_id=1,
                paper_dir=Path("/tmp/paper"),
                row_count=3,
                schedule_if_needed=True,
            )

        self.assertTrue(contract.text_ready)
        self.assertFalse(contract.visual_ready)
        self.assertEqual(contract.visual_state, "running")
        schedule_refresh.assert_awaited_once_with(1, Path("/tmp/paper"))

    async def test_running_when_visual_refresh_in_progress(self):
        with (
            patch("services.artifact_status.paper_text_is_current", return_value=True),
            patch("services.artifact_status.paper_visuals_are_current", return_value=False),
            patch("services.artifact_status.get_artifact_refresh_error", return_value=None),
            patch("services.artifact_status.is_artifact_refresh_running", return_value=True),
        ):
            contract = await resolve_artifact_status_contract(
                paper_id=1,
                paper_dir=Path("/tmp/paper"),
                row_count=0,
                schedule_if_needed=True,
            )

        self.assertEqual(contract.visual_state, "running")

    async def test_error_when_visual_refresh_failed(self):
        with (
            patch("services.artifact_status.paper_text_is_current", return_value=True),
            patch("services.artifact_status.paper_visuals_are_current", return_value=False),
            patch("services.artifact_status.get_artifact_refresh_error", return_value=(500, "refresh failed")),
            patch("services.artifact_status.is_artifact_refresh_running", return_value=False),
        ):
            contract = await resolve_artifact_status_contract(
                paper_id=1,
                paper_dir=Path("/tmp/paper"),
                row_count=0,
                schedule_if_needed=True,
            )

        self.assertEqual(contract.visual_state, "error")
        self.assertEqual(contract.visual_error, "refresh failed")

    async def test_ready_when_text_and_visual_are_current(self):
        with (
            patch("services.artifact_status.paper_text_is_current", return_value=True),
            patch("services.artifact_status.paper_visuals_are_current", return_value=True),
            patch("services.artifact_status.get_artifact_refresh_error", return_value=None),
            patch("services.artifact_status.is_artifact_refresh_running", return_value=False),
        ):
            contract = await resolve_artifact_status_contract(
                paper_id=1,
                paper_dir=Path("/tmp/paper"),
                row_count=0,
                schedule_if_needed=True,
            )

        self.assertTrue(contract.artifacts_ready)
        self.assertEqual(contract.visual_state, "ready")


class CachedPhaseLookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_find_cached_phase_result_uses_input_hash(self):
        input_text = "final prompt string"
        expected_hash = compute_input_hash(input_text)

        with patch(
            "services.document_context.fetch_one",
            new=AsyncMock(
                return_value={
                    "result": '{"ok": true}',
                    "model_used": "gemini",
                    "tokens_in": 10,
                    "tokens_out": 20,
                    "cost_usd": 0.3,
                    "input_hash": expected_hash,
                }
            ),
        ) as fetch_one_mock:
            cached = await find_cached_phase_result(7, "screening", input_text)

        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertEqual(cached.input_hash, expected_hash)
        fetch_one_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
