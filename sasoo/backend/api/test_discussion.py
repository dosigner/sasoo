"""토의 기록과 맥락 예산(2단계 게이트 1번). 실제 SQLite에 쓰고 모델 호출만 바꿔 끼운다."""

import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api import analysis_routes
from models import database
from services import discussion


class _FakeRequest:
    def __init__(self, payload, disconnect_after_tokens=None):
        self._payload = payload
        self._disconnect_after = disconnect_after_tokens
        self.tokens_seen = 0

    async def json(self):
        return self._payload

    async def is_disconnected(self):
        return self._disconnect_after is not None and self.tokens_seen >= self._disconnect_after


def _stream(tokens, *, tokens_in=1000, fail_after=None, captured=None, request=None):
    def fake_stream(chat_input, **kwargs):
        if captured is not None:
            captured.append(chat_input)

        async def _gen():
            for index, token in enumerate(tokens):
                if fail_after is not None and index == fail_after:
                    raise RuntimeError("stream boom")
                yield {"type": "token", "text": token}
                if request is not None:
                    request.tokens_seen += 1
            yield {"type": "done", "tokens_in": tokens_in, "tokens_out": 10}

        return _gen()

    return fake_stream


class DiscussionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = ExitStack()
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.dict(os.environ, {"SASOO_APP_DATA_ROOT": str(root)}))
        self.stack.enter_context(patch.object(database, "APP_DATA_ROOT", root))
        self.stack.enter_context(patch.object(database, "DB_PATH", root / "test.db"))
        self.stack.enter_context(patch.object(database, "_get_default_library_root", return_value=root / "papers"))
        self.stack.enter_context(patch.object(database, "_db_connection", None))
        self.stack.enter_context(patch.object(database, "_library_root_cache", None))
        await database.init_db()
        self.addCleanup(self.stack.close)
        self.addAsyncCleanup(database.close_db)
        self.paper_id = await database.execute_insert(
            "INSERT INTO papers (title, folder_name, domain, agent_used) VALUES ('Paper', 'folder', 'optics', 'photon')"
        )
        self.stack.enter_context(patch.object(
            analysis_routes, "_build_chat_context", new=AsyncMock(return_value=("SYS", []))
        ))
        self.stack.enter_context(patch.object(analysis_routes, "active_provider", new=AsyncMock(return_value="openai")))
        self.stack.enter_context(patch.object(
            analysis_routes, "resolve_model", return_value=SimpleNamespace(model="gpt-6-luna", effort="low")
        ))
        self.stack.enter_context(patch.object(analysis_routes, "calc_result_cost", return_value=0.001))

    async def _send(self, message, stream, request=None, **body):
        request = request or _FakeRequest({"message": message, **body})
        with patch.object(analysis_routes, "stream_interaction", new=stream):
            response = await analysis_routes._chat_with_agent_impl(self.paper_id, request)
            events = [json.loads(chunk[len("data: "):]) async for chunk in response.body_iterator]
        return events

    async def _rows(self):
        return [(row["kind"], row["status"], row["content"], row["reset_reason"])
                for row in await discussion.list_messages(self.paper_id)]

    async def test_answers_are_saved_and_next_turn_uses_server_history(self):
        captured = []
        events = await self._send("첫 질문", _stream(["첫 ", "답"], captured=captured))
        self.assertEqual(events[0]["type"], "meta")
        self.assertIsNone(events[0]["reset"])
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["context_tokens"], 1000)
        self.assertIsNotNone(events[-1]["message_id"])

        await self._send("둘째 질문", _stream(["둘째 답"], captured=captured), history=[{"role": "user", "content": "무시"}])
        self.assertEqual(captured[1], "사용자: 첫 질문\n사수: 첫 답\n사용자: 둘째 질문")
        self.assertEqual(await self._rows(), [
            ("user", "complete", "첫 질문", None), ("sasoo", "complete", "첫 답", None),
            ("user", "complete", "둘째 질문", None), ("sasoo", "complete", "둘째 답", None),
        ])

    async def test_interrupted_answer_is_kept_but_left_out_of_context(self):
        events = await self._send("질문", _stream(["받은 ", "데까지", "못 받음"], fail_after=2))
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual((await self._rows())[-1], ("sasoo", "interrupted", "받은 데까지", None))

        captured = []
        await self._send("다시", _stream(["답"], captured=captured))
        self.assertEqual(captured[0], "사용자: 질문\n사용자: 다시")

    async def test_client_disconnect_saves_partial_answer_as_interrupted(self):
        request = _FakeRequest({"message": "질문"}, disconnect_after_tokens=1)
        await self._send("질문", _stream(["앞", "뒤"], request=request), request=request)
        self.assertEqual((await self._rows())[-1], ("sasoo", "interrupted", "앞", None))

    async def test_budget_boundary_triggers_reset_only_past_260k(self):
        await discussion.append_user(self.paper_id, "예전 질문")
        await discussion.append_sasoo(self.paper_id, "예전 답", status="complete", tokens_in=259_000)

        precount = AsyncMock(return_value=259_500)
        with patch.object(analysis_routes, "count_input_tokens", new=precount):
            captured = []
            events = await self._send("아래", _stream(["답"], tokens_in=259_400, captured=captured))
        precount.assert_awaited_once()
        self.assertIsNone(events[0]["reset"])
        self.assertIn("예전 질문", captured[0])

        with patch.object(analysis_routes, "count_input_tokens", new=AsyncMock(return_value=260_001)):
            captured = []
            events = await self._send("넘김", _stream(["새 답"], tokens_in=7000, captured=captured))
        self.assertEqual(events[0]["reset"]["reset_reason"], discussion.RESET_BUDGET)
        self.assertEqual(captured[0], "사용자: 넘김")

    async def test_small_conversation_skips_precount(self):
        await discussion.append_user(self.paper_id, "q")
        await discussion.append_sasoo(self.paper_id, "a", status="complete", tokens_in=7000)
        precount = AsyncMock(return_value=1)
        with patch.object(analysis_routes, "count_input_tokens", new=precount):
            await self._send("다음", _stream(["답"]))
        precount.assert_not_awaited()

    async def test_reanalysis_inserts_reset_but_first_completion_does_not(self):
        db = await database.get_db()
        await db.execute(
            "INSERT INTO analysis_results (paper_id, phase, result, created_at) VALUES (?, 'deep_dive', 'old', '2026-10-01 00:00:00')",
            (self.paper_id,),
        )
        await db.execute(
            "INSERT INTO discussion_messages (paper_id, kind, content, created_at) VALUES (?, 'user', 'q', '2026-10-02 00:00:00')",
            (self.paper_id,),
        )
        # 처음 끝난 단계(이전 결과 없음)는 맥락을 더할 뿐이다.
        await db.execute(
            "INSERT INTO analysis_results (paper_id, phase, result, created_at) VALUES (?, 'recipe', 'first', '2026-10-03 00:00:00')",
            (self.paper_id,),
        )
        await db.commit()
        self.assertFalse(await discussion.reanalysis_reset_needed(self.paper_id))

        await db.execute(
            "INSERT INTO analysis_results (paper_id, phase, result, created_at) VALUES (?, 'deep_dive', 'new', '2026-10-04 00:00:00')",
            (self.paper_id,),
        )
        await db.commit()
        events = await self._send("재분석 뒤 질문", _stream(["답"]))
        self.assertEqual(events[0]["reset"]["reset_reason"], discussion.RESET_REANALYSIS)
        self.assertFalse(await discussion.reanalysis_reset_needed(self.paper_id))

    async def test_paper_delete_cascades_to_discussion(self):
        await discussion.append_user(self.paper_id, "q")
        await database.execute_update("DELETE FROM papers WHERE id = ?", (self.paper_id,))
        self.assertEqual(await discussion.list_messages(self.paper_id), [])

    async def test_persist_false_uses_body_history_and_saves_nothing(self):
        captured = []
        events = await self._send(
            "안내", _stream(["가이드"], captured=captured), persist=False,
            history=[{"role": "user", "content": "body 질문"}],
        )
        self.assertNotEqual(events[0]["type"], "meta")
        self.assertEqual(captured[0], "사용자: body 질문\n사용자: 안내")
        self.assertEqual(await self._rows(), [])

    async def test_discussion_endpoints_reset_and_delete(self):
        await discussion.append_user(self.paper_id, "질문")
        await discussion.append_sasoo(self.paper_id, "답", status="complete", tokens_in=8000)
        payload = await analysis_routes.get_discussion(self.paper_id)
        self.assertEqual(payload["context"]["budget"], 260_000)
        self.assertEqual(payload["context"]["context_tokens"], 8000)
        conversation = next(s for s in payload["context"]["sources"] if s["key"] == "conversation")
        self.assertEqual(conversation["chars"], 3)

        reset = await analysis_routes.reset_discussion(self.paper_id)
        self.assertEqual(reset["reset_reason"], discussion.RESET_MANUAL)
        self.assertEqual(await discussion.active_context(self.paper_id), [])
        self.assertIsNone((await analysis_routes.get_discussion(self.paper_id))["context"]["context_tokens"])

        await analysis_routes.delete_discussion(self.paper_id)
        self.assertEqual(await discussion.list_messages(self.paper_id), [])


if __name__ == "__main__":
    unittest.main()
