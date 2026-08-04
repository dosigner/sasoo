import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


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
        """OpenAI 경로는 문서 파트를 지원하지 않는다(스펙 R1) — 조용히 떨어뜨리면
        체인 첫 호출이 빈 컨텍스트로 나가므로 시끄럽게 실패한다."""
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


class TestCallInteractionBehavior(unittest.TestCase):
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

    def test_does_not_retry_non_retryable_status(self):
        from services.llm import openai_client

        fake_client = MagicMock()
        fake_client.responses.create.side_effect = _FakeStatusError(400)
        with patch("services.llm.openai_client._get_client", return_value=fake_client), \
             patch("services.llm.openai_client._RETRY_DELAYS", [0, 0]):
            with self.assertRaises(_FakeStatusError):
                asyncio.run(openai_client.call_interaction("필터", lane="pipeline"))
        self.assertEqual(fake_client.responses.create.call_count, 1)


if __name__ == "__main__":
    unittest.main()
