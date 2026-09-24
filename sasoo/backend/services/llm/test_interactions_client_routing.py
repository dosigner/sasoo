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
        openai_mock.assert_awaited_once_with(
            "p", lane="pipeline", model="gpt-5.6-luna", store=False)
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
        gem.assert_awaited_once_with(
            "p", lane="pipeline", model="gemini-3.6-flash", store=False)
        oai.assert_not_awaited()

    def test_strict_schema_is_forwarded_to_openai(self):
        from services.llm import interactions_client

        # Given a request using an OpenAI model.
        with patch("services.llm.openai_client.call_interaction", new_callable=AsyncMock) as call:
            # When strict structured output is requested.
            asyncio.run(interactions_client.call_interaction(
                "p", lane="pipeline", model="gpt-5.6-luna", strict_schema=True))
        # Then the OpenAI client receives the opt-in flag.
        call.assert_awaited_once_with(
            "p", lane="pipeline", model="gpt-5.6-luna", strict_schema=True)

    def test_pdf_validation_controls_are_forwarded_to_openai(self):
        from services.llm import interactions_client

        prompt = [{"type": "document", "mime_type": "application/pdf",
                   "filename": "paper.pdf", "data": "JVBERi0="}]
        options = dict(lane="pipeline", model="gpt-6-luna", single_attempt=True,
                       service_tier="default", max_output_tokens=16000)
        with patch("services.llm.openai_client.call_interaction", new_callable=AsyncMock) as call:
            asyncio.run(interactions_client.call_interaction(prompt, **options))
        call.assert_awaited_once_with(prompt, **options)

    def test_stream_validation_controls_are_forwarded_to_openai(self):
        from services.llm import interactions_client

        options = dict(lane="chat", model="gpt-6-luna", single_attempt=True,
                       service_tier="default", max_output_tokens=2000)
        received = []

        async def fake_stream(prompt, **kwargs):
            received.append((prompt, kwargs))
            yield {"type": "done", "tokens_in": None, "tokens_out": None,
                   "tokens_thought": None, "interaction_id": None, "usage_complete": False}

        async def run():
            return [event async for event in interactions_client.stream_interaction("p", **options)]

        with patch("services.llm.openai_client.stream_interaction", new=fake_stream):
            events = asyncio.run(run())
        self.assertEqual(received, [("p", options)])
        self.assertIsNone(events[-1]["tokens_in"])
        self.assertFalse(events[-1]["usage_complete"])

    def test_strict_schema_is_not_forwarded_to_gemini(self):
        from services.llm import interactions_client

        # Given a request using a Gemini model.
        with patch("services.llm.gemini_client.call_interaction", autospec=True) as call:
            # When a shared caller supplies the OpenAI-only option.
            asyncio.run(interactions_client.call_interaction(
                "p", lane="pipeline", model="gemini-3.6-flash", strict_schema=True))
        # Then Gemini receives only its supported arguments.
        call.assert_awaited_once_with("p", lane="pipeline", model="gemini-3.6-flash")

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
