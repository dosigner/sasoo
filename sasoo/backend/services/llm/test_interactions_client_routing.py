import asyncio
import unittest
from unittest.mock import AsyncMock, patch


class TestModelPrefixRouting(unittest.TestCase):
    """셔션은 모델 접두사로 클라이언트를 고른다 — 호출부는 분기를 모른다."""

    def test_gpt_model_routes_to_openai(self):
        from services.llm import interactions_client
        openai_mock = AsyncMock(return_value={"text": "ok"})
        with (
            patch("services.llm.openai_client.call_interaction", new=openai_mock),
            patch("services.llm.gemini_client.call_interaction", new=AsyncMock()) as gem,
        ):
            asyncio.run(interactions_client.call_interaction(
                "p", lane="pipeline", model="gpt-5.6-luna", store=False))
        openai_mock.assert_awaited_once()
        gem.assert_not_awaited()

    def test_gemini_model_routes_to_gemini(self):
        from services.llm import interactions_client
        gem = AsyncMock(return_value={"text": "ok"})
        with (
            patch("services.llm.gemini_client.call_interaction", new=gem),
            patch("services.llm.openai_client.call_interaction", new=AsyncMock()) as oai,
        ):
            asyncio.run(interactions_client.call_interaction(
                "p", lane="pipeline", model="gemini-3.6-flash", store=False))
        gem.assert_awaited_once()
        oai.assert_not_awaited()

    def test_gpt_model_streams_via_openai(self):
        from services.llm import interactions_client

        async def _fake_stream(*a, **k):
            yield {"type": "done", "tokens_in": 0, "tokens_out": 0,
                   "tokens_thought": 0, "interaction_id": None}

        with (
            patch("services.llm.openai_client.stream_interaction", new=_fake_stream),
            patch("services.llm.gemini_client.stream_interaction") as gem_stream,
        ):
            async def _run():
                events = []
                async for ev in interactions_client.stream_interaction(
                    "p", lane="chat", model="gpt-5.6-luna", store=False,
                ):
                    events.append(ev)
                return events

            events = asyncio.run(_run())
        self.assertEqual(events[-1]["type"], "done")
        gem_stream.assert_not_called()

    def test_non_gpt_model_streams_via_gemini(self):
        from services.llm import interactions_client

        async def _fake_stream(*a, **k):
            yield {"type": "done", "tokens_in": 0, "tokens_out": 0,
                   "tokens_thought": 0, "interaction_id": None}

        with (
            patch("services.llm.gemini_client.stream_interaction", new=_fake_stream),
            patch("services.llm.openai_client.stream_interaction") as oai_stream,
        ):
            async def _run():
                events = []
                async for ev in interactions_client.stream_interaction(
                    "p", lane="chat", model="gemini-3.6-flash", store=False,
                ):
                    events.append(ev)
                return events

            events = asyncio.run(_run())
        self.assertEqual(events[-1]["type"], "done")
        oai_stream.assert_not_called()


if __name__ == "__main__":
    unittest.main()
