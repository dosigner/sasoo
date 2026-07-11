import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.llm.interactions_client import call_interaction


def _fake_interaction(text="결과", interaction_id="int_1"):
    return SimpleNamespace(
        id=interaction_id,
        output_text=text,
        usage=SimpleNamespace(total_input_tokens=100, total_output_tokens=50),
        status="completed",
    )


def test_call_interaction_basic():
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = _fake_interaction()
    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        result = asyncio.run(call_interaction("안녕"))
    assert result["text"] == "결과"
    assert result["interaction_id"] == "int_1"
    assert result["tokens_in"] == 100
    kwargs = fake_client.interactions.create.call_args.kwargs
    assert kwargs["model"] == "gemini-3.5-flash"
    assert "temperature" not in str(kwargs)


def test_call_interaction_chains_previous_id():
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = _fake_interaction(interaction_id="int_2")
    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        asyncio.run(call_interaction("후속", previous_interaction_id="int_1"))
    assert fake_client.interactions.create.call_args.kwargs["previous_interaction_id"] == "int_1"


def test_call_interaction_retries_on_error():
    fake_client = MagicMock()
    fake_client.interactions.create.side_effect = [
        RuntimeError("503"), RuntimeError("503"), _fake_interaction(),
    ]
    with patch("services.llm.interactions_client._get_client", return_value=fake_client), \
         patch("services.llm.interactions_client._RETRY_DELAYS", [0, 0]):
        result = asyncio.run(call_interaction("재시도"))
    assert result["text"] == "결과"
    assert fake_client.interactions.create.call_count == 3
