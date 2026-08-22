"""services.evidence_repo 테스트 — 검증기와 evidence_anchors 사이 배선."""

import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import aiosqlite
import fitz

from models.evidence_anchors import EVIDENCE_ANCHORS_DDL, fetch_anchors
from services import evidence_repo


async def _run_inline(fn, *args):
    """run_pipeline_blocking 대체 — 테스트에서 스레드풀을 쓰지 않는다."""
    return fn(*args)


def _write_pdf(path: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), "The samples were annealed at 500 °C for 2 h.", fontsize=10, fontname="helv")
    doc.save(path)
    doc.close()


RECIPE = json.dumps(
    {
        "title": "레시피",
        "parameters": [
            {
                "name": "annealing_temperature",
                "value": "500",
                "unit": "°C",
                "source_tag": "explicit",
                "evidence_quote": "The samples were annealed at 500 °C for 2 h.",
                "evidence_page": 1,
            },
            {"name": "pressure", "value": "1", "source_tag": "explicit"},
        ],
    },
    ensure_ascii=False,
)


class EvidenceRepoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(
            "CREATE TABLE papers (id INTEGER PRIMARY KEY);"
            "CREATE TABLE analysis_results (id INTEGER PRIMARY KEY, paper_id INTEGER);"
        )
        await self.conn.execute("INSERT INTO papers (id) VALUES (7)")
        await self.conn.execute("INSERT INTO analysis_results (id, paper_id) VALUES (41, 7)")
        await self.conn.executescript(EVIDENCE_ANCHORS_DDL)
        await self.conn.commit()

        pdf_handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        pdf_handle.close()
        self.pdf_path = pdf_handle.name
        _write_pdf(self.pdf_path)

        self._patches = [
            patch("services.evidence_repo.get_db", new=AsyncMock(return_value=self.conn)),
            patch("services.evidence_repo.run_pipeline_blocking", new=_run_inline),
        ]
        for item in self._patches:
            item.start()

    async def asyncTearDown(self):
        for item in self._patches:
            item.stop()
        await self.conn.close()
        os.unlink(self.db_path)
        os.unlink(self.pdf_path)

    async def _ensure(self, **overrides):
        kwargs = {
            "paper_id": 7,
            "analysis_result_id": 41,
            "recipe_text": RECIPE,
            "pdf_path": self.pdf_path,
        }
        kwargs.update(overrides)
        return await evidence_repo.ensure_recipe_anchors(**kwargs)

    async def test_writes_one_anchor_per_parameter(self):
        outcome = await self._ensure()
        self.assertEqual(outcome["status"], "verified")
        self.assertEqual(outcome["anchors"], 2)
        rows = await fetch_anchors(self.conn, 41)
        self.assertEqual([row["target_index"] for row in rows], [0, 1])
        self.assertEqual(rows[0]["display_status"], "VERIFIED")
        self.assertEqual(rows[1]["display_status"], "UNVERIFIED_NO_QUOTE")

    async def test_second_run_is_skipped_when_versions_match(self):
        await self._ensure()
        outcome = await self._ensure()
        self.assertEqual(outcome["status"], "up_to_date")

    async def test_force_reverifies(self):
        await self._ensure()
        outcome = await self._ensure(force=True)
        self.assertEqual(outcome["status"], "verified")
        self.assertEqual(len(await fetch_anchors(self.conn, 41)), 2)  # 중복 행이 아니라 갱신

    async def test_unparsable_recipe_is_skipped_without_anchors(self):
        outcome = await self._ensure(recipe_text='{"_raw":"...","_parse_error":"boom"}')
        self.assertEqual(outcome["status"], "skipped_unparsable")
        self.assertEqual(await fetch_anchors(self.conn, 41), [])

    async def test_skipped_phase_result_is_not_anchored(self):
        outcome = await self._ensure(recipe_text='{"skipped": true, "reason": "low_relevance"}')
        self.assertEqual(outcome["status"], "skipped_unparsable")

    async def test_recipe_without_parameters_is_skipped(self):
        outcome = await self._ensure(recipe_text='{"title":"t","parameters":[]}')
        self.assertEqual(outcome["status"], "skipped_no_parameters")

    async def test_missing_pdf_still_records_unverified_anchors(self):
        outcome = await self._ensure(pdf_path=None)
        self.assertEqual(outcome["anchors"], 2)
        rows = await fetch_anchors(self.conn, 41)
        self.assertEqual({row["display_status"] for row in rows}, {"UNVERIFIED_NO_TEXT_LAYER"})

    async def test_build_payload_returns_none_without_anchors(self):
        self.assertIsNone(await evidence_repo.build_evidence_payload(41))
        self.assertIsNone(await evidence_repo.build_evidence_payload(None))

    async def test_build_payload_shapes_read_model(self):
        await self._ensure()
        payload = await evidence_repo.build_evidence_payload(41)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["summary"]["total"], 2)
        self.assertEqual(payload["summary"]["verified"], 1)
        self.assertEqual(payload["summary"]["by_display_status"]["UNVERIFIED_NO_QUOTE"], 1)
        first = payload["anchors"][0]
        self.assertEqual(first["target_label"], "annealing_temperature")
        self.assertEqual(len(first["bbox"]), 4)
        self.assertNotIn("bbox_json", first)  # 프론트에는 파싱된 배열만 준다


if __name__ == "__main__":
    unittest.main()
