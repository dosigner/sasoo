"""Evidence 검증기 회귀 게이트 — 실제 라이브러리가 있을 때만 돈다.

CI에는 논문 데이터도 앱 DB도 없으므로 자동 skip된다(services/test_extraction_accuracy_regression.py와
같은 관례). CI에서 항상 도는 결정론 게이트는 services/test_evidence_verifier.py의 합성 PDF
테스트다 — 위조 인용 false-verify=0은 거기서 고정된다.

여기서 보는 것은 "실제 데이터에서도 불변식이 깨지지 않는가"다.
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
