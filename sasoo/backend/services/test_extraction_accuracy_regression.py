"""추출 정확도 회귀 게이트 — 결정적 lane을 기준선에 고정한다.

`tools/extraction_audit/measure.py`의 결정적 lane(GEMINI_API_KEY 없음)을 그대로 돌려
그림·표 산출 결과가 기준선에서 벗어나지 않는지 본다. 프로덕션 lane은 게이트로 쓰지
않는다 — VLM 비결정성 때문에 실행마다 표 ±1, 그림 ±2로 흔들려 간헐적 실패가 난다
(캐시 없이 3회 반복해 실측한 노이즈 바닥).

이 테스트는 **라이브러리 12편이 있을 때만** 돌고, 없으면 건너뛴다. CI에는 논문 데이터가
없으므로 자동으로 skip된다. 로컬에서 추출 코드를 건드렸을 때 잡아주는 것이 목적이다.

기준선은 `docs/table_gold.json`(표)과 markdown의 `Figure N` 번호 집합(그림)이다.
표는 결정적 lane에서 격자 복원이 불가능한 논문이 있어 완전 일치가 아니다 — 그건 결함이
아니라 매체 특성이므로(표의 산출물은 격자다) 논문별 기대값을 명시해 고정한다.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

LIBRARY = BACKEND / "library"
GOLD_PATH = BACKEND.parents[1] / "docs" / "table_gold.json"

# 결정적 lane(VLM 없음)의 기준선. 값은 (표 오차, 그림 오차).
# 표 오차가 0이 아닌 논문은 격자 복원이 VLM에 의존해서다 — 프로덕션 lane에서는 전부 0이다.
DETERMINISTIC_BASELINE = {
    "2012_ICSOS_SpaceOpticalNetworks_optics": (0, 0),
    "2013_IEEETIP_ClusterCoSaliency_Quantum": (1, 0),
    "2014_Saliency_Optimization_from_Robust_Backgr_706a9f8d": (0, 0),
    "2017_COMST_OpticalComm_optical_communications": (2, 0),
    "2019_FourierSpaceDNN_optics": (0, 0),
    "2022_ApplOpt_PredictionNet_optics": (1, 0),
    "2022_SciRep_CoherentFsoLeo_optics": (0, 0),
    "2025_OptExpress_UplinkPrecomp_optics": (0, 0),
    "2025_TurboQuant_general": (2, 0),
    "2026_SR_AgileMultiskill_ai_ml": (0, 0),
    "OptFor_RefractiveMCAO_optics": (5, 0),
    "TurPy_OpticTurb_optics": (0, 0),
}


def _library_is_available() -> bool:
    if not GOLD_PATH.exists() or not LIBRARY.exists():
        return False
    present = {
        directory.name
        for directory in LIBRARY.iterdir()
        if (directory / ".odl_manifest.json").exists() and any(directory.glob("*.pdf"))
    }
    return set(DETERMINISTIC_BASELINE) <= present


@unittest.skipUnless(_library_is_available(), "라이브러리 12편이 없어 정확도 회귀 게이트를 건너뛴다")
class ExtractionAccuracyRegressionTests(unittest.TestCase):
    """추출 코드를 건드렸을 때 12편 기준선이 깨지는지 잡는다."""

    @classmethod
    def setUpClass(cls) -> None:
        from tools.extraction_audit.measure import (
            iter_papers,
            load_gold,
            make_scratch_dir,
            prepare_manifest,
            run_pipeline,
            table_metrics,
            figure_metrics,
        )

        saved_key = os.environ.pop("GEMINI_API_KEY", None)
        gold = load_gold()
        cls.results: dict[str, tuple[int, int]] = {}
        cls.details: dict[str, dict] = {}
        try:
            for paper_dir in iter_papers():
                if paper_dir.name not in DETERMINISTIC_BASELINE:
                    continue
                pdf_path = next(paper_dir.glob("*.pdf"))
                markdown_files = sorted(paper_dir.glob("*.odl-reference.md")) or sorted(
                    path for path in paper_dir.glob("*.md") if not path.name.startswith(".")
                )
                markdown_text = (
                    markdown_files[0].read_text(encoding="utf-8", errors="ignore") if markdown_files else ""
                )
                paper_gold = gold.get(paper_dir.name, {"numbers": [], "labels": [], "evidence": []})

                manifest = prepare_manifest(paper_dir, pdf_path)
                scratch = make_scratch_dir(paper_dir, manifest, pdf_path)
                try:
                    outcome = asyncio.run(run_pipeline(manifest, pdf_path=pdf_path, scratch=scratch))
                finally:
                    shutil.rmtree(scratch, ignore_errors=True)

                tables = table_metrics(outcome["tables"], paper_gold["numbers"])
                figures = figure_metrics(outcome["figures"], markdown_text)
                cls.results[paper_dir.name] = (tables["error"], figures["error"])
                cls.details[paper_dir.name] = {"tables": tables, "figures": figures}
        finally:
            if saved_key is not None:
                os.environ["GEMINI_API_KEY"] = saved_key

    def test_figure_extraction_matches_baseline(self):
        """그림은 결정적 lane에서 12편 전부 정확일치여야 한다."""
        for name, (_, expected_error) in DETERMINISTIC_BASELINE.items():
            with self.subTest(paper=name):
                self.assertEqual(
                    self.results[name][1],
                    expected_error,
                    f"{name}: 그림 {self.details[name]['figures']}",
                )

    def test_table_extraction_matches_baseline(self):
        for name, (expected_error, _) in DETERMINISTIC_BASELINE.items():
            with self.subTest(paper=name):
                self.assertEqual(
                    self.results[name][0],
                    expected_error,
                    f"{name}: 표 {self.details[name]['tables']}",
                )

    def test_every_emitted_table_has_a_caption(self):
        """캡션 게이트(계약 11)를 지표로 고정한다 — 캡션 없는 표는 하나도 나오면 안 된다."""
        for name, detail in self.details.items():
            with self.subTest(paper=name):
                tables = detail["tables"]
                self.assertEqual(
                    tables["caption_linked"],
                    tables["extracted_count"],
                    f"{name}: 캡션 없는 표가 {tables['extracted_count'] - tables['caption_linked']}개 나왔다",
                )


if __name__ == "__main__":
    unittest.main()
