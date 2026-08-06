"""Evidence 검증기 회귀 게이트 — 실제 라이브러리가 있을 때만 돈다.

CI에는 논문 데이터도 앱 DB도 없으므로 자동 skip된다(services/test_extraction_accuracy_regression.py와
같은 관례). CI에서 항상 도는 결정론 게이트는 services/test_evidence_verifier.py의 합성 PDF
테스트다 — 위조 인용 false-verify=0은 거기서 고정된다.

여기서 보는 것은 "실제 데이터에서도 불변식이 깨지지 않는가"다.

`AggregateAxisSeparationTests`는 예외다 — `tools.evidence_audit.measure.aggregate()`/`_ratio()`는
DB도 PDF도 필요 없는 순수 함수라 합성 dict만으로 검증할 수 있다. 그래서 로컬 코퍼스 skip
가드 밖에 두고 CI에서 항상 돈다(집계 분모 분리 버그는 실제 논문 없이도 잡을 수 있어야
한다).
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from models.database import DB_PATH  # noqa: E402
from tools.evidence_audit.measure import aggregate, _ratio  # noqa: E402


def _synthetic_paper(
    *,
    engine: str = "odl-java",
    folder_name: str = "synthetic",
    parameters: int,
    offered: int,
    verified: int,
    exact: int = 0,
    normalized: int = 0,
    partial: int = 0,
    not_found: int = 0,
    value_present: int = 0,
    page_confirmed: int = 0,
    bbox: int = 0,
    by_source_tag: dict | None = None,
    forged_attempts: int = 0,
    forged_false_verify: int = 0,
    elapsed_ms: float = 1.0,
) -> dict:
    """measure_paper()가 반환하는 것과 같은 모양의 합성 결과 — aggregate()만 순수하게 찌른다."""
    return {
        "paper_id": 1,
        "folder_name": folder_name,
        "engine": engine,
        "pdf": None,
        "parameters": parameters,
        "offered": offered,
        "by_display_status": {},
        "by_quote_status": {},
        "by_source_tag": by_source_tag or {},
        "verified": verified,
        "exact": exact,
        "normalized": normalized,
        "partial": partial,
        "not_found": not_found,
        "value_present": value_present,
        "page_confirmed": page_confirmed,
        "bbox": bbox,
        "forged_attempts": forged_attempts,
        "forged_false_verify": forged_false_verify,
        "elapsed_ms": elapsed_ms,
    }


class AggregateAxisSeparationTests(unittest.TestCase):
    """aggregate()/_ratio()는 DB·PDF 없이 도는 순수 함수 — 스킵 없이 CI에서 항상 돈다."""

    def test_ratio_zero_denominator_is_explicit_not_a_crash(self):
        self.assertEqual(_ratio(0, 0), "n/a (0/0)")
        self.assertEqual(_ratio(3, 10), "0.300 (3/10)")
        self.assertEqual(_ratio(2, 2), "1.000 (2/2)")

    def test_source_tag_verified_rate_does_not_mix_with_inferred(self):
        # explicit 2/2 VERIFIED + inferred 0/3 VERIFIED가 뭉치면 2/5=0.400로 보인다.
        # source_tag별로 쪼갰을 때 explicit=1.000, inferred=0.000이 따로 나와야 한다 —
        # 뭉친 값과 같아지면(오염되면) 이 테스트가 잡는다.
        paper = _synthetic_paper(
            parameters=5, offered=2, verified=2,
            exact=2, not_found=3,
            value_present=2, page_confirmed=2, bbox=1,
            by_source_tag={
                "explicit": {
                    "parameters": 2, "offered": 2, "verified": 2, "located": 2,
                    "value_present": 2, "page_confirmed": 2, "bbox": 1,
                },
                "inferred": {
                    "parameters": 3, "offered": 0, "verified": 0, "located": 0,
                    "value_present": 0, "page_confirmed": 0, "bbox": 0,
                },
            },
        )
        summary = aggregate([paper])

        self.assertEqual(summary["parameter_verified_rate"], "0.400 (2/5)")
        self.assertEqual(summary["by_source_tag"]["explicit"]["parameter_verified_rate"], "1.000 (2/2)")
        self.assertEqual(summary["by_source_tag"]["inferred"]["parameter_verified_rate"], "0.000 (0/3)")
        self.assertNotEqual(
            summary["by_source_tag"]["inferred"]["parameter_verified_rate"],
            summary["parameter_verified_rate"],
        )

    def test_source_tag_breakdown_carries_value_page_bbox_axes(self):
        paper = _synthetic_paper(
            parameters=5, offered=2, verified=2,
            exact=2, not_found=3,
            value_present=2, page_confirmed=2, bbox=1,
            by_source_tag={
                "explicit": {
                    "parameters": 2, "offered": 2, "verified": 2, "located": 2,
                    "value_present": 2, "page_confirmed": 2, "bbox": 1,
                },
                "inferred": {
                    "parameters": 3, "offered": 0, "verified": 0, "located": 0,
                    "value_present": 0, "page_confirmed": 0, "bbox": 0,
                },
            },
        )
        summary = aggregate([paper])

        explicit = summary["by_source_tag"]["explicit"]
        self.assertEqual(explicit["value_present_rate"], "1.000 (2/2)")
        self.assertEqual(explicit["page_confirm_rate"], "1.000 (2/2)")
        self.assertEqual(explicit["bbox_rate"], "0.500 (1/2)")

        # inferred는 located=0 — value_present_rate가 0/0으로 "0%"가 아니라 "n/a"여야 한다.
        # 0%로 나오면 "inferred가 검증에 실패했다"로 오독되는데, 실제로는 애초에 채점 대상이
        # 아니라는 뜻이라 구분해야 한다.
        inferred = summary["by_source_tag"]["inferred"]
        self.assertEqual(inferred["value_present_rate"], "n/a (0/0)")
        self.assertEqual(inferred["page_confirm_rate"], "n/a (0/0)")
        self.assertEqual(inferred["bbox_rate"], "n/a (0/0)")

    def test_engine_breakdown_does_not_cross_contaminate(self):
        paper_odl = _synthetic_paper(
            engine="odl-java", folder_name="paper-odl",
            parameters=4, offered=4, verified=3,
            exact=3, not_found=1,
            value_present=3, page_confirmed=3, bbox=3,
        )
        paper_gemini = _synthetic_paper(
            engine="gemini", folder_name="paper-gemini",
            parameters=2, offered=2, verified=0,
            not_found=2,
        )
        summary = aggregate([paper_odl, paper_gemini])

        self.assertEqual(summary["by_engine"]["odl-java"]["parameter_verified_rate"], "0.750 (3/4)")
        self.assertEqual(summary["by_engine"]["gemini"]["parameter_verified_rate"], "0.000 (0/2)")
        self.assertEqual(summary["by_engine"]["odl-java"]["page_confirm_rate"], "1.000 (3/3)")
        # gemini 쪽은 located=0(아무 것도 못 찾음) — odl-java의 100%가 새어 들어오면 안 된다.
        self.assertEqual(summary["by_engine"]["gemini"]["page_confirm_rate"], "n/a (0/0)")
        self.assertEqual(summary["by_engine"]["gemini"]["value_present_rate"], "n/a (0/0)")
        self.assertEqual(summary["by_engine"]["gemini"]["bbox_rate"], "n/a (0/0)")


def _has_local_corpus() -> bool:
    if not Path(DB_PATH).exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM analysis_results WHERE phase = 'recipe'"
            ).fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return count > 0


@unittest.skipUnless(_has_local_corpus(), "로컬 DB에 recipe 결과가 없어 Evidence 회귀 게이트를 건너뛴다")
class EvidenceRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools.evidence_audit.measure import latest_recipe_rows, measure_paper

        cls.results = [measure_paper(row) for row in latest_recipe_rows(DB_PATH, limit=3)]

    def test_corpus_is_not_empty(self):
        self.assertGreater(len(self.results), 0)

    def test_every_parameter_gets_exactly_one_anchor(self):
        for result in self.results:
            self.assertEqual(
                sum(result["by_display_status"].values()),
                result["parameters"],
                result["folder_name"],
            )

    def test_forged_quotes_never_verify_on_real_papers(self):
        total = sum(result["forged_false_verify"] for result in self.results)
        self.assertEqual(total, 0)

    def test_verifier_stays_within_synchronous_budget(self):
        # 동기 실행을 유지할 수 있는지 보는 지표. 넘으면 별도 phase 분리를 검토한다.
        for result in self.results:
            self.assertLess(result["elapsed_ms"], 5000, result["folder_name"])


if __name__ == "__main__":
    unittest.main()
