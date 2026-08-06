import os
import tempfile
import unittest

import aiosqlite

from models import evidence_anchors as ea


def _draft(**overrides) -> dict:
    base = {
        "target_kind": "recipe_parameter",
        "target_key": "p000:wavelength",
        "target_index": 0,
        "target_label": "wavelength",
        "source_tag": "explicit",
        "claimed_quote": "a wavelength of 1550 nm",
        "claimed_page": 4,
        "quote_status": "verified_normalized",
        "page_status": "match",
        "value_status": "value_in_quote",
        "display_status": "VERIFIED",
        "match_method": "normalized",
        "match_ratio": 1.0,
        "matched_quote": "a wave-\nlength of 1550 nm",
        "matched_page": 4,
        "bbox_json": "[72.0, 700.1, 300.5, 715.2]",
        "corpus": "pdf_text",
        "failure_detail": None,
        "verifier_version": "ev1",
        "normalizer_version": "norm-v1",
    }
    base.update(overrides)
    return base


class EvidenceAnchorsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.conn = await aiosqlite.connect(self.tmp.name)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.executescript(
            "CREATE TABLE papers (id INTEGER PRIMARY KEY);"
            "CREATE TABLE analysis_results (id INTEGER PRIMARY KEY, paper_id INTEGER);"
        )
        await self.conn.execute("INSERT INTO papers (id) VALUES (7)")
        await self.conn.execute("INSERT INTO analysis_results (id, paper_id) VALUES (41, 7)")
        await self.conn.executescript(ea.EVIDENCE_ANCHORS_DDL)
        await self.conn.commit()

    async def asyncTearDown(self):
        await self.conn.close()
        os.unlink(self.tmp.name)

    async def test_ddl_is_idempotent(self):
        await self.conn.executescript(ea.EVIDENCE_ANCHORS_DDL)
        await self.conn.commit()  # 두 번 실행해도 예외가 없어야 한다

    async def test_upsert_then_reverify_updates_in_place(self):
        written = await ea.upsert_anchors(
            self.conn, paper_id=7, analysis_result_id=41, phase="recipe",
            anchors=[_draft(), _draft(target_key="p001:power", target_index=1, target_label="power")],
        )
        self.assertEqual(written, 2)

        # 검증기 버전업 후 재검증 — 같은 target_key는 새 행이 아니라 갱신이어야 한다
        await ea.upsert_anchors(
            self.conn, paper_id=7, analysis_result_id=41, phase="recipe",
            anchors=[_draft(quote_status="not_found", display_status="UNVERIFIED_NOT_FOUND",
                            verifier_version="ev2")],
        )
        rows = await ea.fetch_anchors(self.conn, 41)
        self.assertEqual(len(rows), 2)
        first = next(r for r in rows if r["target_key"] == "p000:wavelength")
        self.assertEqual(first["display_status"], "UNVERIFIED_NOT_FOUND")
        self.assertEqual(first["verifier_version"], "ev2")

    async def test_fetch_anchors_is_ordered_by_target_index(self):
        await ea.upsert_anchors(
            self.conn, paper_id=7, analysis_result_id=41, phase="recipe",
            anchors=[
                _draft(target_key="p002:c", target_index=2, target_label="c"),
                _draft(target_key="p000:a", target_index=0, target_label="a"),
                _draft(target_key="p001:b", target_index=1, target_label="b"),
            ],
        )
        rows = await ea.fetch_anchors(self.conn, 41)
        self.assertEqual([r["target_index"] for r in rows], [0, 1, 2])

    async def test_anchor_versions_reports_count_and_version_set(self):
        await ea.upsert_anchors(
            self.conn, paper_id=7, analysis_result_id=41, phase="recipe",
            anchors=[_draft(), _draft(target_key="p001:b", target_index=1, target_label="b")],
        )
        count, versions = await ea.anchor_versions(self.conn, 41)
        self.assertEqual(count, 2)
        self.assertEqual(versions, {"ev1/norm-v1"})

    async def test_deleting_analysis_result_cascades(self):
        await ea.upsert_anchors(
            self.conn, paper_id=7, analysis_result_id=41, phase="recipe", anchors=[_draft()],
        )
        await self.conn.execute("DELETE FROM analysis_results WHERE id = 41")
        await self.conn.commit()
        self.assertEqual(await ea.fetch_anchors(self.conn, 41), [])


if __name__ == "__main__":
    unittest.main()
