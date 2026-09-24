import asyncio
import os
import threading
import unittest
import base64
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


class _FakeStatusError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class TestAvailability(unittest.TestCase):
    def test_available_true_when_key_present(self):
        from services.llm import openai_client
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            self.assertTrue(openai_client.available())

    def test_available_false_when_key_absent(self):
        from services.llm import openai_client
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(openai_client.available())


class TestChainGuard(unittest.TestCase):
    def test_chain_without_store_raises(self):
        from services.llm import openai_client
        with self.assertRaises(ValueError):
            asyncio.run(openai_client.call_interaction(
                "prompt", lane="pipeline", store=False,
                previous_interaction_id="resp_abc",
            ))


class TestRetryPolicy(unittest.TestCase):
    def test_408_429_5xx_retryable_4xx_not(self):
        from services.llm.openai_client import _is_retryable
        for status, expected in ((408, True), (429, True), (503, True),
                                 (400, False), (401, False), (403, False), (404, False)):
            with self.subTest(status=status):
                self.assertEqual(_is_retryable(_FakeStatusError(status)), expected)

    def test_exception_without_status_is_retryable(self):
        from services.llm.openai_client import _is_retryable
        self.assertTrue(_is_retryable(RuntimeError("connection reset")))


class TestPartTranslator(unittest.TestCase):
    """Gemini 파트 dict를 Responses API input으로 번역 — 이미지 파트를 넘기는
    호출부가 7곳이다(리졸버 3종·subfigure·figure_service 등)."""

    def test_plain_string_passes_through(self):
        from services.llm.openai_client import _translate_parts
        self.assertEqual(_translate_parts("질문"), "질문")

    def test_image_part_becomes_input_image_data_url(self):
        from services.llm.openai_client import _translate_parts
        out = _translate_parts([
            {"type": "image", "data": "QUJD", "mime_type": "image/png"},
            {"type": "text", "text": "이 그림은?"},
        ])
        content = out[0]["content"]
        self.assertEqual(content[0]["type"], "input_image")
        self.assertEqual(content[0]["image_url"], "data:image/png;base64,QUJD")
        self.assertEqual(content[1], {"type": "input_text", "text": "이 그림은?"})

    def test_document_part_raises(self):
        """Gemini file URIs cannot be consumed by OpenAI."""
        from services.llm.openai_client import _translate_parts
        with self.assertRaises(ValueError):
            _translate_parts([{"type": "document", "uri": "files/abc",
                               "mime_type": "application/pdf"}])


class TestClientCaching(unittest.TestCase):
    def test_same_key_reuses_client(self):
        from services.llm import openai_client
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-cache-test"}, clear=False):
            openai_client._clients.clear()
            c1 = openai_client._get_client()
            c2 = openai_client._get_client()
            self.assertIs(c1, c2)


def _fake_response(text="결과", response_id="resp_1", reasoning_tokens=0, cached_tokens=0):
    return SimpleNamespace(
        id=response_id,
        output_text=text,
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            output_tokens_details=SimpleNamespace(reasoning_tokens=reasoning_tokens),
            input_tokens_details=SimpleNamespace(cached_tokens=cached_tokens),
        ),
    )


class TestReturnShape(unittest.TestCase):
    """gemini_client.call_interaction과 동형 dict인지 — 셔션이 분기 없이 위임하려면
    두 provider가 정확히 같은 키 집합을 돌려줘야 한다."""

    def test_return_dict_key_set_matches_gemini_client(self):
        """openai_client가 gemini_client의 키 집합을 최소한 다 포함해야 셔션이
        분기 없이 위임할 수 있다(추가 정보용 키는 허용: tokens_thought는 gemini에도
        있고, tokens_cached는 openai 전용 추가)."""
        from types import SimpleNamespace as NS

        from services.llm import gemini_client, openai_client

        fake_gemini_client = MagicMock()
        fake_gemini_client.interactions.create.return_value = NS(
            id="int_1", output_text="결과",
            usage=NS(total_input_tokens=10, total_output_tokens=5, total_thought_tokens=0),
            status="completed",
        )
        with patch("services.llm.gemini_client._get_client", return_value=fake_gemini_client):
            gemini_result = asyncio.run(gemini_client.call_interaction("안녕", lane="pipeline"))

        fake_openai_client = MagicMock()
        fake_openai_client.responses.create.return_value = _fake_response()
        with patch("services.llm.openai_client._get_client", return_value=fake_openai_client):
            openai_result = asyncio.run(openai_client.call_interaction("안녕", lane="pipeline"))

        self.assertTrue(set(gemini_result.keys()).issubset(set(openai_result.keys())))

    def test_incomplete_response_status_is_preserved(self):
        from services.llm import openai_client

        fake_client = MagicMock()
        response = _fake_response()
        response.status = "incomplete"
        fake_client.responses.create.return_value = response
        with patch("services.llm.openai_client._get_client", return_value=fake_client):
            result = asyncio.run(openai_client.call_interaction("source", lane="pipeline"))
        self.assertTrue(result["incomplete"])
        self.assertEqual(result["tokens_out"], 50)

    def test_returns_text_model_tokens_and_interaction_id(self):
        from services.llm import openai_client

        fake_client = MagicMock()
        fake_client.responses.create.return_value = _fake_response(
            text="결과", response_id="resp_1", reasoning_tokens=30,
        )
        with patch("services.llm.openai_client._get_client", return_value=fake_client):
            result = asyncio.run(openai_client.call_interaction("안녕", lane="pipeline"))

        self.assertEqual(result["text"], "결과")
        self.assertEqual(result["interaction_id"], "resp_1")
        self.assertEqual(result["tokens_in"], 100)
        # R7-2: output_tokens는 이미 reasoning을 포함 — gemini처럼 재합산하지 않는다.
        self.assertEqual(result["tokens_out"], 50)
        self.assertEqual(result["tokens_thought"], 30)

    def test_tokens_cached_reflects_input_tokens_details(self):
        """정보용 필드 — Task 12(측정 도구)가 캐시 적중률 집계에 쓴다."""
        from services.llm import openai_client

        fake_client = MagicMock()
        fake_client.responses.create.return_value = _fake_response(cached_tokens=64)
        with patch("services.llm.openai_client._get_client", return_value=fake_client):
            result = asyncio.run(openai_client.call_interaction("안녕", lane="pipeline"))

        self.assertEqual(result["tokens_cached"], 64)
        self.assertIsNone(result["tokens_cache_write"])


class TestCallInteractionBehavior(unittest.TestCase):
    def test_strict_schema_closes_nested_objects_without_mutating_deep_dive_schema(self):
        from services.analysis_execution import _DEEP_DIVE_SCHEMA
        from services.llm import openai_client

        # Given the shared schema also used by Gemini.
        original = deepcopy(_DEEP_DIVE_SCHEMA)
        fake_client = MagicMock()
        fake_client.responses.create.return_value = _fake_response()

        # When only this request opts into strict structured output.
        with patch("services.llm.openai_client._get_client", return_value=fake_client):
            asyncio.run(openai_client.call_interaction(
                "source", lane="pipeline", response_schema=_DEEP_DIVE_SCHEMA,
                strict_schema=True,
            ))

        # Then the wire schema closes every object and keeps string semantics.
        format_config = fake_client.responses.create.call_args.kwargs["text"]["format"]
        wire_schema = format_config["schema"]
        self.assertIs(format_config["strict"], True)
        for node in (
            wire_schema,
            wire_schema["properties"]["section_answers"]["items"],
            wire_schema["properties"]["transfer_checks"]["items"],
        ):
            self.assertIs(node["additionalProperties"], False)
            self.assertEqual(node["required"], list(node["properties"]))
        self.assertEqual(wire_schema["properties"]["as_is"], {"type": "string"})
        self.assertEqual(wire_schema["properties"]["to_be"], {"type": "string"})
        self.assertEqual(_DEEP_DIVE_SCHEMA, original)

    def test_schema_remains_non_strict_when_flag_is_omitted(self):
        from services.analysis_execution import _DEEP_DIVE_SCHEMA
        from services.llm import openai_client

        # Given a schema with optional string fields.
        original = deepcopy(_DEEP_DIVE_SCHEMA)
        fake_client = MagicMock()
        fake_client.responses.create.return_value = _fake_response()

        # When the caller keeps the existing default.
        with patch("services.llm.openai_client._get_client", return_value=fake_client):
            asyncio.run(openai_client.call_interaction(
                "source", lane="pipeline", response_schema=_DEEP_DIVE_SCHEMA,
            ))

        # Then neither strict mode nor schema normalization is applied.
        format_config = fake_client.responses.create.call_args.kwargs["text"]["format"]
        self.assertIs(format_config["strict"], False)
        self.assertEqual(format_config["schema"], original)

    def test_thinking_level_maps_to_reasoning_effort(self):
        from services.llm import openai_client

        fake_client = MagicMock()
        fake_client.responses.create.return_value = _fake_response()
        with patch("services.llm.openai_client._get_client", return_value=fake_client):
            asyncio.run(openai_client.call_interaction(
                "안녕", lane="pipeline", thinking_level="high",
            ))
        kwargs = fake_client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["reasoning"], {"effort": "high"})

    def test_previous_interaction_id_maps_to_previous_response_id(self):
        from services.llm import openai_client

        fake_client = MagicMock()
        fake_client.responses.create.return_value = _fake_response()
        with patch("services.llm.openai_client._get_client", return_value=fake_client):
            asyncio.run(openai_client.call_interaction(
                "후속", lane="pipeline", previous_interaction_id="resp_prev",
            ))
        kwargs = fake_client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["previous_response_id"], "resp_prev")

    def test_max_output_tokens_is_passed_through(self):
        """analysis_routes가 recipe phase에서 이 값을 넘긴다(_STAGE_MAX_OUTPUT_TOKENS).

        파라미터가 없으면 디스패처의 **kwargs가 그대로 전달돼 TypeError가 난다.
        Gemini 쪽만 고치고 여기를 빼면 provider=openai에서만 조용히 터진다.
        """
        from services.llm import openai_client

        fake_client = MagicMock()
        fake_client.responses.create.return_value = _fake_response()
        with patch("services.llm.openai_client._get_client", return_value=fake_client):
            asyncio.run(openai_client.call_interaction(
                "안녕", lane="pipeline", thinking_level="low", max_output_tokens=24000,
            ))
        kwargs = fake_client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["max_output_tokens"], 24000)

    def test_max_output_tokens_omitted_when_not_given(self):
        """안 주면 키를 안 보낸다 — 기본값을 우리가 정하지 않는다."""
        from services.llm import openai_client

        fake_client = MagicMock()
        fake_client.responses.create.return_value = _fake_response()
        with patch("services.llm.openai_client._get_client", return_value=fake_client):
            asyncio.run(openai_client.call_interaction("안녕", lane="pipeline"))
        kwargs = fake_client.responses.create.call_args.kwargs
        self.assertNotIn("max_output_tokens", kwargs)
        self.assertNotIn("service_tier", kwargs)
        fake_client.with_options.assert_not_called()

    def test_media_resolution_is_ignored(self):
        """media_resolution은 Gemini 전용 — 시그니처 호환을 위해 받되 무시한다."""
        from services.llm import openai_client

        fake_client = MagicMock()
        fake_client.responses.create.return_value = _fake_response()
        with patch("services.llm.openai_client._get_client", return_value=fake_client):
            asyncio.run(openai_client.call_interaction(
                "안녕", lane="pipeline", media_resolution="high",
            ))
        kwargs = fake_client.responses.create.call_args.kwargs
        self.assertNotIn("media_resolution", kwargs)

    def test_retries_on_retryable_error_then_succeeds(self):
        from services.llm import openai_client

        fake_client = MagicMock()
        fake_client.responses.create.side_effect = [
            _FakeStatusError(503), _fake_response(),
        ]
        with patch("services.llm.openai_client._get_client", return_value=fake_client), \
             patch("services.llm.openai_client._RETRY_DELAYS", [0, 0]):
            result = asyncio.run(openai_client.call_interaction("재시도", lane="pipeline"))
        self.assertEqual(result["text"], "결과")
        self.assertEqual(fake_client.responses.create.call_count, 2)
        fake_client.with_options.assert_not_called()

    def test_does_not_retry_non_retryable_status(self):
        from services.llm import openai_client

        fake_client = MagicMock()
        fake_client.responses.create.side_effect = _FakeStatusError(400)
        with patch("services.llm.openai_client._get_client", return_value=fake_client), \
             patch("services.llm.openai_client._RETRY_DELAYS", [0, 0]):
            # gemini_client와 동형 래핑(RuntimeError) — 셔션 배선 이후 소비자가 provider를
            # 구분하지 않고 예외를 다루므로 두 클라이언트의 예외 타입이 같아야 한다.
            with self.assertRaisesRegex(RuntimeError, "non-retryable"):
                asyncio.run(openai_client.call_interaction("필터", lane="pipeline"))
        self.assertEqual(fake_client.responses.create.call_count, 1)

    def test_raises_runtime_error_after_retries_exhausted(self):
        """재시도 가능한 오류(503 등)가 모든 attempt에서 반복되면, 마지막 원인을
        RuntimeError로 감싸 던진다 — gemini_client.call_interaction의 "after retries"
        폴백과 동형이다."""
        from services.llm import openai_client

        fake_client = MagicMock()
        fake_client.responses.create.side_effect = _FakeStatusError(503)
        with patch("services.llm.openai_client._get_client", return_value=fake_client), \
             patch("services.llm.openai_client._RETRY_DELAYS", [0, 0]):
            with self.assertRaisesRegex(RuntimeError, "after retries"):
                asyncio.run(openai_client.call_interaction("재시도소진", lane="pipeline"))
        self.assertEqual(fake_client.responses.create.call_count, 3)


class _FakeStreamEvent:
    def __init__(self, type_, delta=None, response=None):
        self.type = type_
        self.delta = delta
        self.response = response


def _fake_stream_response(response_id="resp_x", input_tokens=7, output_tokens=3,
                           reasoning_tokens=0):
    return SimpleNamespace(
        id=response_id,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            output_tokens_details=SimpleNamespace(reasoning_tokens=reasoning_tokens),
        ),
    )


class _FakeResponseStream:
    """`client.responses.stream(**kwargs)`가 돌려주는 컨텍스트 매니저를 흉내."""

    def __init__(self, events):
        self._events = events

    def __enter__(self):
        return iter(self._events)

    def __exit__(self, *a):
        return False


class _FailingResponseStream:
    """스트림 진입 자체가 실패하는 경우(첫 토큰 전 오류)를 흉내."""

    def __enter__(self):
        raise RuntimeError("boom")

    def __exit__(self, *a):
        return False


async def _collect_stream(agen):
    out = []
    async for ev in agen:
        out.append(ev)
    return out


class TestStreamContract(unittest.TestCase):
    """Preserve required token/done fields while allowing provider metadata."""

    def test_stream_yields_tokens_then_done(self):
        from services.llm import openai_client

        events = [
            _FakeStreamEvent("response.output_text.delta", delta="안"),
            _FakeStreamEvent("response.output_text.delta", delta="녕"),
            _FakeStreamEvent("response.completed", response=_fake_stream_response()),
        ]
        fake_client = MagicMock()
        fake_client.responses.stream.return_value = _FakeResponseStream(events)

        with patch.object(openai_client, "_get_client", return_value=fake_client):
            result = asyncio.run(_collect_stream(
                openai_client.stream_interaction("질문", lane="chat", store=False)
            ))

        token_events = [e for e in result if e["type"] == "token"]
        self.assertEqual([e["text"] for e in token_events], ["안", "녕"])

        done = result[-1]
        self.assertEqual(done["type"], "done")
        self.assertEqual(done["tokens_in"], 7)
        self.assertEqual(done["tokens_out"], 3)
        self.assertEqual(done["interaction_id"], "resp_x")
        self.assertTrue({"type", "tokens_in", "tokens_out", "tokens_thought",
                         "interaction_id"}.issubset(done))

    def test_stream_done_key_set_matches_gemini_stream(self):
        from services.llm import gemini_client, openai_client

        gemini_events = [
            SimpleNamespace(event_type="step.delta",
                             delta=SimpleNamespace(type="text", text="안")),
            SimpleNamespace(
                event_type="interaction.completed",
                interaction=SimpleNamespace(
                    id="int_1",
                    usage=SimpleNamespace(
                        total_input_tokens=1, total_output_tokens=1, total_thought_tokens=0,
                    ),
                ),
            ),
        ]
        fake_gemini_client = MagicMock()
        fake_gemini_client.interactions.create.return_value = iter(gemini_events)
        with patch.object(gemini_client, "_get_client", return_value=fake_gemini_client):
            gemini_result = asyncio.run(_collect_stream(
                gemini_client.stream_interaction("hi", lane="chat")
            ))
        gemini_done = [e for e in gemini_result if e["type"] == "done"][-1]

        openai_events = [
            _FakeStreamEvent("response.output_text.delta", delta="안"),
            _FakeStreamEvent("response.completed", response=_fake_stream_response()),
        ]
        fake_openai_client = MagicMock()
        fake_openai_client.responses.stream.return_value = _FakeResponseStream(openai_events)
        with patch.object(openai_client, "_get_client", return_value=fake_openai_client):
            openai_result = asyncio.run(_collect_stream(
                openai_client.stream_interaction("질문", lane="chat", store=False)
            ))
        openai_done = [e for e in openai_result if e["type"] == "done"][-1]

        self.assertTrue(set(gemini_done.keys()).issubset(openai_done))

    def test_stream_tokens_thought_reflects_reasoning_tokens(self):
        from services.llm import openai_client

        events = [
            _FakeStreamEvent("response.output_text.delta", delta="t"),
            _FakeStreamEvent(
                "response.completed",
                response=_fake_stream_response(output_tokens=50, reasoning_tokens=30),
            ),
        ]
        fake_client = MagicMock()
        fake_client.responses.stream.return_value = _FakeResponseStream(events)

        with patch.object(openai_client, "_get_client", return_value=fake_client):
            result = asyncio.run(_collect_stream(
                openai_client.stream_interaction("질문", lane="chat", store=False)
            ))

        done = [e for e in result if e["type"] == "done"][0]
        # R7-2: output_tokens는 이미 reasoning을 포함 — gemini처럼 재합산하지 않는다.
        self.assertEqual(done["tokens_out"], 50)
        self.assertEqual(done["tokens_thought"], 30)

    def test_stream_raises_before_done_on_error(self):
        """done 이전 예외는 소비자에게 재던져야 한다 — 채팅 라우트의 '첫 토큰
        전 실패만 재시도' 정책(analysis_routes.py event_generator)이 이
        예외 전파에 의존한다."""
        from services.llm import openai_client

        fake_client = MagicMock()
        fake_client.responses.stream.return_value = _FailingResponseStream()

        with patch.object(openai_client, "_get_client", return_value=fake_client):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                asyncio.run(_collect_stream(
                    openai_client.stream_interaction("질문", lane="chat", store=False)
                ))

    def test_stream_thinking_level_maps_to_reasoning_effort(self):
        from services.llm import openai_client

        events = [_FakeStreamEvent("response.completed", response=_fake_stream_response())]
        fake_client = MagicMock()
        fake_client.responses.stream.return_value = _FakeResponseStream(events)

        with patch.object(openai_client, "_get_client", return_value=fake_client):
            asyncio.run(_collect_stream(
                openai_client.stream_interaction(
                    "질문", lane="chat", store=False, thinking_level="high",
                )
            ))

        kwargs = fake_client.responses.stream.call_args.kwargs
        self.assertEqual(kwargs["reasoning"], {"effort": "high"})
        self.assertNotIn("max_output_tokens", kwargs)
        self.assertNotIn("service_tier", kwargs)
        fake_client.with_options.assert_not_called()

    def test_stream_yields_fallback_done_when_stream_ends_without_completed(self):
        """SDK 스트림이 response.completed 없이 예외 없이 끝나도(예: 서버가 종료
        이벤트를 누락) done 없이 조용히 끝나면 안 된다 — 프론트 onDone(비용
        집계·액션 버튼)이 영영 호출되지 않는다. gemini_client와 같은 폴백."""
        from services.llm import openai_client

        events = [
            _FakeStreamEvent("response.output_text.delta", delta="안"),
            _FakeStreamEvent("response.output_text.delta", delta="녕"),
        ]
        fake_client = MagicMock()
        fake_client.responses.stream.return_value = _FakeResponseStream(events)

        with patch.object(openai_client, "_get_client", return_value=fake_client):
            result = asyncio.run(_collect_stream(
                openai_client.stream_interaction("질문", lane="chat", store=False)
            ))

        self.assertEqual(result[0], {"type": "token", "text": "안"})
        self.assertEqual(result[1], {"type": "token", "text": "녕"})
        self.assertEqual(len(result), 3)
        self.assertEqual(result[2]["type"], "done")
        self.assertTrue({"tokens_in", "tokens_out", "tokens_thought",
                         "interaction_id"}.issubset(result[2]))
        self.assertIsNone(result[2]["tokens_in"])
        self.assertIsNone(result[2]["tokens_out"])
        self.assertIsNone(result[2]["tokens_cached"])
        self.assertIsNone(result[2]["tokens_cache_write"])
        self.assertFalse(result[2]["usage_complete"])
        self.assertTrue(result[2]["incomplete"])
        self.assertEqual(result[2]["incomplete_reason"], "missing_completion")

    def test_stream_raises_after_tokens_before_done_without_fallback(self):
        """토큰이 이미 나간 뒤 done 전에 실패하면 예외를 그대로 재던지고,
        폴백 done을 끼워넣지 않는다 — 채팅 라우트는 이 경우를 terminal 실패로
        취급한다(streamed_any=True라 재시도 없이 SSE error를 보낸다)."""
        from services.llm import openai_client

        def fake_events():
            yield _FakeStreamEvent("response.output_text.delta", delta="안")
            yield _FakeStreamEvent("response.output_text.delta", delta="녕")
            raise RuntimeError("mid-stream boom")

        class _FakeResponseStreamMidError:
            def __enter__(self):
                return fake_events()

            def __exit__(self, *a):
                return False

        fake_client = MagicMock()
        fake_client.responses.stream.return_value = _FakeResponseStreamMidError()

        collected = []

        async def run():
            with patch.object(openai_client, "_get_client", return_value=fake_client):
                async for ev in openai_client.stream_interaction(
                    "질문", lane="chat", store=False,
                ):
                    collected.append(ev)

        with self.assertRaisesRegex(RuntimeError, "mid-stream boom"):
            asyncio.run(run())

        self.assertEqual(collected, [
            {"type": "token", "text": "안"},
            {"type": "token", "text": "녕"},
        ])

    def test_stream_chat_lane_skips_pipeline_sem(self):
        """chat lane은 파이프라인 세마포어를 절대 건드리지 않는다 — 파이프라인
        팬아웃이 세마포어 슬롯을 다 채워도 채팅이 걸려선 안 된다."""
        from services.concurrency import pipeline_llm_sem
        from services.llm import openai_client

        events = [_FakeStreamEvent("response.completed", response=_fake_stream_response())]
        fake_client = MagicMock()
        fake_client.responses.stream.return_value = _FakeResponseStream(events)
        seen = {}

        async def run():
            sem = pipeline_llm_sem()
            seen["baseline"] = sem._value
            with patch.object(openai_client, "_get_client", return_value=fake_client):
                await _collect_stream(
                    openai_client.stream_interaction("질문", lane="chat", store=False)
                )
            seen["after"] = sem._value

        asyncio.run(run())
        self.assertEqual(seen["after"], seen["baseline"])

    def test_stream_pipeline_lane_holds_pipeline_sem_during_stream(self):
        """pipeline lane은 gemini_client.stream_interaction과 동형으로 스트림이
        살아있는 전체 구간 동안 세마포어 슬롯 하나를 점유해야 한다(429 방지) —
        call_interaction의 pipeline 분기와 같은 정책."""
        from services.concurrency import pipeline_llm_sem
        from services.llm import openai_client

        proceed = threading.Event()
        seen = {}

        def fake_events():
            yield _FakeStreamEvent("response.output_text.delta", delta="첫")
            assert proceed.wait(timeout=2), "소비자가 첫 토큰 후 proceed를 풀지 못했다"
            yield _FakeStreamEvent("response.completed", response=_fake_stream_response())

        class _FakeResponseStreamBlocking:
            def __enter__(self):
                return fake_events()

            def __exit__(self, *a):
                return False

        fake_client = MagicMock()
        fake_client.responses.stream.return_value = _FakeResponseStreamBlocking()

        async def run():
            sem = pipeline_llm_sem()
            seen["baseline"] = sem._value
            with patch.object(openai_client, "_get_client", return_value=fake_client):
                agen = openai_client.stream_interaction("질문", lane="pipeline", store=False)
                await agen.__anext__()  # 첫 토큰
                seen["sem_during"] = sem._value
                proceed.set()
                async for _ in agen:
                    pass
            seen["after"] = sem._value

        asyncio.run(run())
        self.assertEqual(seen["sem_during"], seen["baseline"] - 1)  # 스트림 중 슬롯 하나 점유
        self.assertEqual(seen["after"], seen["baseline"])  # 종료 후 반납


def test_pdf_data_is_sent_as_input_file():
    from services.llm.openai_client import _translate_parts

    # Given an inline PDF with audit metadata.
    part = {"type": "document", "mime_type": "application/pdf",
            "filename": "paper.pdf", "data": "JVBERi0=",
            "detail": "high", "sha256": "audit-only"}
    # When the adapter prepares the wire input.
    sent = _translate_parts([part])[0]["content"][0]
    # Then only supported PDF fields reach the API.
    assert sent == {"type": "input_file", "filename": "paper.pdf",
                    "file_data": "data:application/pdf;base64,JVBERi0=",
                    "detail": "high"}


def test_load_pdf_preserves_source_bytes_and_basename(tmp_path: Path):
    from services.llm import openai_client

    # Given a PDF at a local path.
    source = b"%PDF-1.7\nsource bytes\n%%EOF"
    path = tmp_path / "paper.pdf"
    path.write_bytes(source)
    # When the PDF is loaded.
    part = openai_client.load_pdf_part(path)
    # Then the payload and audit hash refer to the exact source.
    assert part == {"type": "document", "mime_type": "application/pdf",
                    "filename": "paper.pdf", "data": base64.b64encode(source).decode("ascii"),
                    "detail": "high", "sha256": hashlib.sha256(source).hexdigest()}


@pytest.mark.parametrize("source", [b"", b"not a PDF"])
def test_load_pdf_rejects_invalid_bytes(tmp_path: Path, source: bytes):
    from services.llm import openai_client

    # Given invalid local input.
    path = tmp_path / "paper.pdf"
    path.write_bytes(source)
    # When it is loaded, then it fails before any API access.
    with pytest.raises(ValueError):
        openai_client.load_pdf_part(path)


def test_load_pdf_rejects_size_limit_before_reading(tmp_path: Path):
    from services.llm import openai_client

    # Given a sparse PDF exactly at the exclusive size limit.
    path = tmp_path / "paper.pdf"
    with path.open("wb") as source:
        source.write(b"%PDF-")
        source.truncate(50_000_000)
    # When it is loaded, then it is rejected without reading the body.
    with patch.object(Path, "read_bytes", side_effect=AssertionError("must not read")):
        with pytest.raises(ValueError):
            openai_client.load_pdf_part(path)


def test_count_and_create_use_identical_model_input():
    from services.llm import openai_client

    # Given a chained strict PDF request.
    request = dict(model="gpt-6-luna", system_instruction="system",
                   thinking_level="high", previous_interaction_id="resp_previous",
                   strict_schema=True,
                   response_schema={"type": "object", "properties": {"answer": {"type": "string"}}})
    prompt = [{"type": "document", "mime_type": "application/pdf",
               "filename": "paper.pdf", "data": "JVBERi0=", "detail": "high"}]
    fake = MagicMock()
    fake.responses.create.return_value = _fake_response()
    fake.responses.input_tokens.count.return_value = SimpleNamespace(input_tokens=1234)
    # When count and generation prepare the same request.
    with patch.object(openai_client, "_get_client", return_value=fake):
        count = asyncio.run(openai_client.count_input_tokens(prompt, **request))
        asyncio.run(openai_client.call_interaction(
            prompt, lane="pipeline", max_output_tokens=16000, service_tier="default", **request))
    # Then all model-input fields agree, and generation-only fields are omitted.
    assert count == 1234
    expected = fake.responses.create.call_args.kwargs.copy()
    for field in ("store", "max_output_tokens", "service_tier"):
        expected.pop(field)
    assert fake.responses.input_tokens.count.call_args.kwargs == expected


def test_single_attempt_disables_sdk_and_adapter_retries():
    from services.llm import openai_client

    # Given a retryable failure and a per-call client override.
    fake = MagicMock()
    attempt = fake.with_options.return_value
    attempt.responses.create.side_effect = RuntimeError("connection reset")
    # When validation requests a single attempt.
    with patch.object(openai_client, "_get_client", return_value=fake):
        with pytest.raises(RuntimeError, match="connection reset"):
            asyncio.run(openai_client.call_interaction(
                "source", lane="pipeline", single_attempt=True, service_tier="default"))
    # Then there is one create and SDK retry is explicitly disabled.
    fake.with_options.assert_called_once_with(max_retries=0)
    assert attempt.responses.create.call_count == 1
    assert attempt.responses.create.call_args.kwargs["service_tier"] == "default"
    fake.responses.create.assert_not_called()


def test_call_preserves_response_status_and_cache_write_usage():
    from services.llm import openai_client

    # Given an incomplete response with explicit cache usage and returned model.
    response = _fake_response(cached_tokens=20, reasoning_tokens=30)
    response.usage.input_tokens_details.cache_write_tokens = 40
    response.model = "gpt-6-luna-snapshot"
    response.status = "incomplete"
    response.incomplete_details = SimpleNamespace(reason="max_output_tokens")
    response.service_tier = "default"
    fake = MagicMock()
    fake.responses.create.return_value = response
    # When it is returned to the caller.
    with patch.object(openai_client, "_get_client", return_value=fake):
        result = asyncio.run(openai_client.call_interaction("source", lane="pipeline", model="gpt-6-luna"))
    # Then provenance and billable totals remain intact.
    assert result["model"] == "gpt-6-luna"
    assert result["response_model"] == response.model
    assert result["response_status"] == "incomplete"
    assert result["incomplete_reason"] == "max_output_tokens"
    assert result["service_tier"] == "default"
    assert (result["tokens_cached"], result["tokens_cache_write"], result["tokens_out"]) == (20, 40, 50)
    assert result["usage_complete"] is True


def test_call_keeps_missing_usage_unknown():
    from services.llm import openai_client

    # Given a failure response without usage.
    fake = MagicMock()
    fake.responses.create.return_value = SimpleNamespace(status="failed", output_text="")
    # When it crosses the adapter boundary.
    with patch.object(openai_client, "_get_client", return_value=fake):
        result = asyncio.run(openai_client.call_interaction("source", lane="pipeline"))
    # Then no missing count is reported as zero.
    for field in ("tokens_in", "tokens_out", "tokens_cached", "tokens_cache_write"):
        assert result[field] is None
    assert result["usage_complete"] is False
    assert result["incomplete"] is True


@pytest.mark.parametrize("event_type,status", [("response.completed", "completed"),
                                             ("response.incomplete", "incomplete"),
                                             ("response.failed", "failed")])
def test_stream_preserves_terminal_usage_and_bounded_request(event_type: str, status: str):
    from services.llm import openai_client

    # Given a terminal stream response and validation client.
    response = _fake_stream_response()
    response.status = status
    response.model = "gpt-6-luna"
    response.service_tier = "default"
    response.usage.input_tokens_details = SimpleNamespace(cached_tokens=1, cache_write_tokens=2)
    response.incomplete_details = SimpleNamespace(reason="max_output_tokens") if status == "incomplete" else None
    fake = MagicMock()
    attempt = fake.with_options.return_value
    attempt.responses.stream.return_value = _FakeResponseStream([_FakeStreamEvent(event_type, response=response)])
    # When streaming is bounded and single-attempt.
    with patch.object(openai_client, "_get_client", return_value=fake):
        events = asyncio.run(_collect_stream(openai_client.stream_interaction(
            "source", lane="chat", single_attempt=True, service_tier="default", max_output_tokens=2000)))
    # Then terminal state and usage are not replaced by a fallback completion.
    fake.with_options.assert_called_once_with(max_retries=0)
    assert attempt.responses.stream.call_args.kwargs["max_output_tokens"] == 2000
    assert attempt.responses.stream.call_args.kwargs["service_tier"] == "default"
    assert len(events) == 1
    assert events[0]["response_status"] == status
    assert events[0]["tokens_cache_write"] == 2
    assert events[0]["tokens_cached"] == 1
    assert events[0]["incomplete"] is (status != "completed")


def test_installed_sdk_count_and_generation_wire_inputs_match():
    import httpx2
    from openai import OpenAI
    from services.llm import openai_client

    # Given the installed SDK with an in-memory HTTP transport.
    requests = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith("input_tokens"):
            return httpx2.Response(200, json={"object": "response.input_tokens", "input_tokens": 42})
        return httpx2.Response(200, json={
            "id": "resp_wire", "object": "response", "created_at": 1,
            "model": "gpt-6-luna", "status": "completed", "output": [],
            "service_tier": "default", "usage": {
                "input_tokens": 42, "output_tokens": 3, "total_tokens": 45,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 4},
                "output_tokens_details": {"reasoning_tokens": 2},
            },
        })

    options = dict(model="gpt-6-luna", thinking_level="high", system_instruction="system",
                   previous_interaction_id="resp_previous", strict_schema=True,
                   response_schema={"type": "object", "properties": {"answer": {"type": "string"}}})
    prompt = [{"type": "document", "mime_type": "application/pdf", "filename": "paper.pdf",
               "data": "JVBERi0=", "sha256": "audit-only"}]
    # When both requests pass through the real SDK serialization path.
    with httpx2.Client(transport=httpx2.MockTransport(handle)) as transport:
        with OpenAI(api_key="test-key", http_client=transport) as client:
            with patch.object(openai_client, "_get_client", return_value=client):
                count = asyncio.run(openai_client.count_input_tokens(prompt, **options))
                result = asyncio.run(openai_client.call_interaction(
                    prompt, lane="pipeline", single_attempt=True, service_tier="default",
                    max_output_tokens=16000, **options))
    # Then count sees precisely the supported subset of the generation wire input.
    assert count == result["tokens_in"] == 42
    assert [path for path, _ in requests] == ["/v1/responses/input_tokens", "/v1/responses"]
    count_body, create_body = [body for _, body in requests]
    assert count_body == {key: value for key, value in create_body.items()
                          if key not in {"store", "service_tier", "max_output_tokens"}}
    assert create_body["input"][0]["content"][0] == {
        "type": "input_file", "filename": "paper.pdf", "detail": "high",
        "file_data": "data:application/pdf;base64,JVBERi0="}
    assert result["tokens_cache_write"] == 4
    assert result["tokens_out"] == 3


@pytest.mark.parametrize("streaming", [False, True])
def test_installed_sdk_single_attempt_sends_only_one_http_request(streaming: bool):
    import httpx2
    from openai import APIConnectionError, OpenAI
    from services.llm import openai_client

    # Given an SDK transport that fails before a response is available.
    requests = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request.url.path)
        raise httpx2.ConnectError("mock network failure", request=request)

    # When a single-attempt validation call encounters the network error.
    with httpx2.Client(transport=httpx2.MockTransport(handle)) as transport:
        with OpenAI(api_key="test-key", http_client=transport) as client:
            with patch.object(openai_client, "_get_client", return_value=client):
                with pytest.raises((RuntimeError, APIConnectionError)):
                    if streaming:
                        asyncio.run(_collect_stream(openai_client.stream_interaction(
                            "source", lane="chat", single_attempt=True, max_output_tokens=100)))
                    else:
                        asyncio.run(openai_client.call_interaction(
                            "source", lane="pipeline", single_attempt=True, max_output_tokens=100))
            assert client.max_retries == 2
    # Then neither SDK nor adapter issued a hidden retry.
    assert requests == ["/v1/responses"]


if __name__ == "__main__":
    unittest.main()
