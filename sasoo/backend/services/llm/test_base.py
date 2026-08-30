import unittest

from services.llm.base import LLMResponse, LLMClient


class TestLLMResponse(unittest.TestCase):
    def test_holds_call_result_fields(self):
        resp = LLMResponse(
            text='{"ok": true}',
            interaction_id="resp_abc",
            tokens_in=100,
            tokens_out=20,
            model="gemini-3.6-flash",
        )
        self.assertEqual(resp.text, '{"ok": true}')
        self.assertEqual(resp.interaction_id, "resp_abc")
        self.assertEqual(resp.tokens_in, 100)
        self.assertEqual(resp.tokens_out, 20)
        self.assertEqual(resp.model, "gemini-3.6-flash")

    def test_interaction_id_is_optional(self):
        resp = LLMResponse(text="hi", interaction_id=None, tokens_in=1, tokens_out=1, model="m")
        self.assertIsNone(resp.interaction_id)


class TestLLMClientProtocol(unittest.TestCase):
    def test_conforming_stub_passes_isinstance(self):
        class Stub:
            def available(self) -> bool:
                return True

            async def call(self, **kwargs) -> LLMResponse:
                return LLMResponse(text="", interaction_id=None, tokens_in=0, tokens_out=0, model="m")

            async def stream(self, **kwargs):
                yield ""

        self.assertIsInstance(Stub(), LLMClient)

    def test_missing_method_fails_isinstance(self):
        class Incomplete:
            def available(self) -> bool:
                return True

        self.assertNotIsInstance(Incomplete(), LLMClient)


if __name__ == "__main__":
    unittest.main()
