import asyncio
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.llm.interactions_client import call_interaction, upload_pdf_for_paper
import services.llm.interactions_client as interactions_client


def _fake_interaction(text="결과", interaction_id="int_1", total_thought_tokens=0):
    return SimpleNamespace(
        id=interaction_id,
        output_text=text,
        usage=SimpleNamespace(
            total_input_tokens=100,
            total_output_tokens=50,
            total_thought_tokens=total_thought_tokens,
        ),
        status="completed",
    )


def test_call_interaction_basic():
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = _fake_interaction(total_thought_tokens=50)
    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        result = asyncio.run(call_interaction("안녕", lane="pipeline"))
    assert result["text"] == "결과"
    assert result["interaction_id"] == "int_1"
    assert result["tokens_in"] == 100
    # 라이브 실측: total_output_tokens는 thinking 미포함, 과금은 출력 단가로
    # thinking 토큰도 청구되므로 tokens_out은 output+thought 합산값이어야 한다.
    assert result["tokens_out"] == 100  # total_output_tokens(50) + total_thought_tokens(50)
    assert result["tokens_thought"] == 50
    kwargs = fake_client.interactions.create.call_args.kwargs
    assert kwargs["model"] == "gemini-3.5-flash"
    assert set(kwargs.keys()) == {"model", "input", "system_instruction", "store"}


def test_call_interaction_tokens_out_sums_output_and_thought_tokens():
    """청구 기준: tokens_out은 total_output_tokens + total_thought_tokens여야 한다
    (라이브 실측 — total_output_tokens는 thinking 토큰을 포함하지 않지만
    Gemini는 thinking 토큰도 출력 단가로 과금한다)."""
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = _fake_interaction(total_thought_tokens=762)
    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        result = asyncio.run(call_interaction("안녕"))
    assert result["tokens_out"] == 50 + 762
    assert result["tokens_thought"] == 762


def test_call_interaction_no_disallowed_params_with_thinking_level():
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = _fake_interaction()
    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        asyncio.run(call_interaction("안녕", lane="pipeline", thinking_level="high"))
    kwargs = fake_client.interactions.create.call_args.kwargs
    assert set(kwargs.keys()) == {"model", "input", "system_instruction", "store", "generation_config"}
    generation_config = kwargs["generation_config"]
    for disallowed in ("temperature", "top_p", "top_k", "thinking_budget"):
        assert disallowed not in generation_config


def test_call_interaction_chains_previous_id():
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = _fake_interaction(interaction_id="int_2")
    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        asyncio.run(call_interaction("후속", lane="pipeline", previous_interaction_id="int_1"))
    assert fake_client.interactions.create.call_args.kwargs["previous_interaction_id"] == "int_1"


def test_call_interaction_retries_on_error():
    fake_client = MagicMock()
    fake_client.interactions.create.side_effect = [
        RuntimeError("503"), RuntimeError("503"), _fake_interaction(),
    ]
    with patch("services.llm.interactions_client._get_client", return_value=fake_client), \
         patch("services.llm.interactions_client._RETRY_DELAYS", [0, 0]):
        result = asyncio.run(call_interaction("재시도", lane="pipeline"))
    assert result["text"] == "결과"
    assert fake_client.interactions.create.call_count == 3


def test_call_interaction_store_false_with_previous_id_raises():
    with pytest.raises(ValueError, match="previous_interaction_id requires store=True"):
        asyncio.run(
            call_interaction("후속", lane="pipeline", previous_interaction_id="int_1", store=False)
        )


# ---------------------------------------------------------------------------
# stream_interaction: 스트리밍 이벤트 → token/done 변환, 비차단 브릿지
# ---------------------------------------------------------------------------

def _delta_event(text):
    # VERIFY(확인됨, streaming.md.txt): step.delta + delta.type=="text" + delta.text
    return SimpleNamespace(
        event_type="step.delta",
        delta=SimpleNamespace(type="text", text=text),
    )


def _completed_event(tokens_in=11, tokens_out=90, tokens_thought=245, iid="int_stream"):
    # VERIFY(확인됨, streaming.md.txt): interaction.completed + interaction.usage.total_*_tokens
    usage = SimpleNamespace(
        total_input_tokens=tokens_in,
        total_output_tokens=tokens_out,
        total_thought_tokens=tokens_thought,
    )
    return SimpleNamespace(
        event_type="interaction.completed",
        interaction=SimpleNamespace(id=iid, usage=usage),
    )


async def _collect(agen):
    out = []
    async for ev in agen:
        out.append(ev)
    return out


def test_stream_interaction_yields_tokens_then_done():
    events = [_delta_event("안"), _delta_event("녕"), _completed_event()]
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = iter(events)

    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        result = asyncio.run(_collect(interactions_client.stream_interaction("hi", lane="chat")))

    assert result[0] == {"type": "token", "text": "안"}
    assert result[1] == {"type": "token", "text": "녕"}
    done = result[2]
    assert done["type"] == "done"
    assert done["tokens_in"] == 11
    # 라이브 실측: total_output_tokens는 thinking 미포함, 과금은 출력 단가로
    # thinking 토큰도 청구되므로 tokens_out은 output+thought 합산값이어야 한다.
    assert done["tokens_out"] == 90 + 245
    assert done["tokens_thought"] == 245
    assert done["interaction_id"] == "int_stream"
    # stream=True 전달 + 금지 파라미터 부재
    kwargs = fake_client.interactions.create.call_args.kwargs
    assert kwargs["stream"] is True
    assert kwargs["model"] == "gemini-3.5-flash"
    for disallowed in ("temperature", "top_p", "top_k", "thinking_budget", "generation_config"):
        assert disallowed not in kwargs


def test_stream_interaction_tokens_out_sums_output_and_thought_tokens():
    """청구 기준: done의 tokens_out은 total_output_tokens + total_thought_tokens여야 한다
    (라이브 실측 — total_output_tokens는 thinking 토큰을 포함하지 않지만
    Gemini는 thinking 토큰도 출력 단가로 과금한다)."""
    events = [
        _delta_event("본문"),
        _completed_event(tokens_in=5, tokens_out=358, tokens_thought=762, iid="int_live"),
    ]
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = iter(events)

    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        result = asyncio.run(_collect(interactions_client.stream_interaction("hi")))

    done = result[-1]
    assert done["type"] == "done"
    assert done["tokens_out"] == 358 + 762
    assert done["tokens_thought"] == 762
    assert done["interaction_id"] == "int_live"


def test_stream_interaction_ignores_non_text_events():
    events = [
        SimpleNamespace(event_type="interaction.created", interaction=SimpleNamespace(id="x")),
        SimpleNamespace(event_type="step.start", step=SimpleNamespace(type="model_output")),
        SimpleNamespace(event_type="step.delta",
                        delta=SimpleNamespace(type="thought_summary", text="생각중")),
        _delta_event("본문"),
        SimpleNamespace(event_type="step.stop", index=0),
        _completed_event(),
    ]
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = iter(events)

    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        result = asyncio.run(_collect(interactions_client.stream_interaction("hi", lane="chat")))

    tokens = [e for e in result if e["type"] == "token"]
    assert tokens == [{"type": "token", "text": "본문"}]
    assert result[-1]["type"] == "done"


def test_stream_interaction_thinking_level_passed_without_disallowed_params():
    events = [_delta_event("t"), _completed_event()]
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = iter(events)

    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        asyncio.run(_collect(interactions_client.stream_interaction("hi", lane="chat", thinking_level="low")))

    kwargs = fake_client.interactions.create.call_args.kwargs
    assert kwargs["generation_config"] == {"thinking_level": "low"}
    for disallowed in ("temperature", "top_p", "top_k", "thinking_budget"):
        assert disallowed not in kwargs["generation_config"]


def test_stream_interaction_store_false_with_previous_id_raises():
    with pytest.raises(ValueError, match="previous_interaction_id requires store=True"):
        asyncio.run(
            _collect(
                interactions_client.stream_interaction(
                    "후속", lane="chat", previous_interaction_id="int_1", store=False
                )
            )
        )


def test_stream_interaction_does_not_block_event_loop():
    """sync 스트림은 스레드에서 돌아야 한다: 생산자 스레드가 블록된 동안에도
    이벤트 루프(소비자)가 계속 돌아 첫 토큰을 받고 proceed를 풀 수 있어야 한다.
    만약 sync 제너레이터가 이벤트 루프에서 돌면 여기서 데드락이 난다."""
    proceed = threading.Event()

    def fake_events():
        yield _delta_event("첫")
        assert proceed.wait(timeout=2), "소비자가 첫 토큰 후 proceed를 풀지 못했다"
        yield _delta_event("둘")
        yield _completed_event()

    fake_client = MagicMock()
    fake_client.interactions.create.return_value = fake_events()

    async def _run():
        agen = interactions_client.stream_interaction("hi", lane="chat")
        first = await agen.__anext__()
        # 이 지점에 도달했다는 것 자체가 생산자 스레드가 블록된 동안
        # 이벤트 루프가 살아 있었다는 증거다.
        proceed.set()
        rest = [ev async for ev in agen]
        return [first, *rest]

    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        result = asyncio.run(_run())

    assert [e for e in result if e["type"] == "token"] == [
        {"type": "token", "text": "첫"},
        {"type": "token", "text": "둘"},
    ]
    assert result[-1]["type"] == "done"


def test_stream_interaction_yields_fallback_done_when_stream_ends_without_completed():
    """SDK 스트림이 interaction.completed 없이 정상 종료(__end__만 도달)해도
    done을 조용히 누락시키지 않고 폴백 done을 yield해야 한다 —
    안 그러면 프론트 onDone(비용 집계·액션 버튼)이 영영 호출되지 않는다."""
    events = [_delta_event("안"), _delta_event("녕")]
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = iter(events)

    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        result = asyncio.run(_collect(interactions_client.stream_interaction("hi", lane="chat")))

    assert result[0] == {"type": "token", "text": "안"}
    assert result[1] == {"type": "token", "text": "녕"}
    assert len(result) == 3
    assert result[2] == {
        "type": "done",
        "tokens_in": 0,
        "tokens_out": 0,
        "tokens_thought": 0,
        "interaction_id": None,
    }


def test_stream_interaction_raises_on_stream_error():
    fake_client = MagicMock()
    fake_client.interactions.create.side_effect = RuntimeError("boom")

    async def _run():
        return await _collect(interactions_client.stream_interaction("hi", lane="chat"))

    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(_run())


def _paper_row(uri="uri-old", expires_at=None):
    return {"pdf_file_uri": uri, "pdf_file_expires_at": expires_at}


def test_upload_pdf_for_paper_cache_hit_skips_upload():
    future_expiry = (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat()
    fake_fetch_one = AsyncMock(return_value=_paper_row(uri="uri-cached", expires_at=future_expiry))
    fake_execute_update = AsyncMock()
    fake_client = MagicMock()

    with patch("models.database.fetch_one", fake_fetch_one), \
         patch("models.database.execute_update", fake_execute_update), \
         patch("services.llm.interactions_client._get_client", return_value=fake_client):
        uri = asyncio.run(upload_pdf_for_paper(1, "/tmp/fake.pdf"))

    assert uri == "uri-cached"
    fake_client.files.upload.assert_not_called()
    fake_execute_update.assert_not_called()


def test_upload_pdf_for_paper_expired_reuploads_and_updates():
    past_expiry = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    fake_fetch_one = AsyncMock(return_value=_paper_row(uri="uri-expired", expires_at=past_expiry))
    fake_execute_update = AsyncMock()
    fake_client = MagicMock()
    fake_client.files.upload.return_value = SimpleNamespace(uri="uri-new")

    with patch("models.database.fetch_one", fake_fetch_one), \
         patch("models.database.execute_update", fake_execute_update), \
         patch("services.llm.interactions_client._get_client", return_value=fake_client):
        uri = asyncio.run(upload_pdf_for_paper(2, "/tmp/fake.pdf"))

    assert uri == "uri-new"
    fake_client.files.upload.assert_called_once_with(file="/tmp/fake.pdf")
    fake_execute_update.assert_called_once()
    update_args = fake_execute_update.call_args.args[1]
    assert update_args[0] == "uri-new"
    assert update_args[2] == 2


def test_upload_pdf_for_paper_no_cache_uploads_and_updates():
    fake_fetch_one = AsyncMock(return_value=None)
    fake_execute_update = AsyncMock()
    fake_client = MagicMock()
    fake_client.files.upload.return_value = SimpleNamespace(uri="uri-fresh")

    with patch("models.database.fetch_one", fake_fetch_one), \
         patch("models.database.execute_update", fake_execute_update), \
         patch("services.llm.interactions_client._get_client", return_value=fake_client):
        uri = asyncio.run(upload_pdf_for_paper(3, "/tmp/fake.pdf"))

    assert uri == "uri-fresh"
    fake_client.files.upload.assert_called_once_with(file="/tmp/fake.pdf")
    fake_execute_update.assert_called_once()


class _FakePapersTable:
    """fetch_one/execute_update을 흉내내는 in-memory 상태 저장소.

    double-checked locking이 실제로 캐시 재확인 시 갱신된 값을 보도록,
    execute_update가 쓴 값을 fetch_one이 그대로 읽어야 한다(정적 AsyncMock으로는
    이 왕복을 표현할 수 없다).
    """

    def __init__(self):
        self.rows: dict[int, dict] = {}
        self.update_calls = 0

    async def fetch_one(self, query, params=()):
        paper_id = params[0]
        row = self.rows.get(paper_id)
        return dict(row) if row is not None else None

    async def execute_update(self, query, params=()):
        uri, expires_at, paper_id = params
        self.rows[paper_id] = {"pdf_file_uri": uri, "pdf_file_expires_at": expires_at}
        self.update_calls += 1
        return 1


def test_upload_pdf_for_paper_concurrent_calls_upload_once():
    """동시 호출 시 두 번째 호출은 락 대기 후 캐시를 재확인하고 업로드를 건너뛰어야 한다.

    파일 업로드(스레드풀에서 실행)를 threading.Event로 실제 블로킹시켜, 두 번째
    호출이 락 획득을 시도하는 동안 첫 번째 호출이 확실히 업로드 중이도록 만든다
    (타이밍에 의존하는 레이스 대신 결정적으로 동시성을 재현).
    """
    interactions_client._upload_locks.clear()

    started = threading.Event()
    proceed = threading.Event()
    table = _FakePapersTable()

    def fake_upload(file):
        started.set()
        assert proceed.wait(timeout=2), "두 번째 호출이 락 대기에 들어가지 않았다"
        return SimpleNamespace(uri="uri-concurrent")

    fake_client = MagicMock()
    fake_client.files.upload.side_effect = fake_upload

    async def _run_concurrently():
        t1 = asyncio.create_task(upload_pdf_for_paper(4, "/tmp/fake.pdf"))
        for _ in range(200):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set(), "첫 번째 호출이 업로드를 시작하지 않았다"

        t2 = asyncio.create_task(upload_pdf_for_paper(4, "/tmp/fake.pdf"))
        # t2가 락 획득을 시도하고 대기 상태로 들어갈 시간을 준다.
        await asyncio.sleep(0.1)
        proceed.set()
        return await asyncio.gather(t1, t2)

    with patch("models.database.fetch_one", table.fetch_one), \
         patch("models.database.execute_update", table.execute_update), \
         patch("services.llm.interactions_client._get_client", return_value=fake_client):
        results = asyncio.run(_run_concurrently())

    assert results == ["uri-concurrent", "uri-concurrent"]
    fake_client.files.upload.assert_called_once_with(file="/tmp/fake.pdf")
    assert table.update_calls == 1


# ---------------------------------------------------------------------------
# Lane isolation — 채팅이 파이프라인 풀·세마포어에 절대 얽히지 않음을 고정한다.
# ---------------------------------------------------------------------------

def test_call_interaction_requires_lane():
    with pytest.raises(TypeError):
        asyncio.run(call_interaction("안녕"))  # lane 없이는 호출 자체가 성립하지 않는다


def test_chat_lane_runs_on_chat_executor_and_skips_pipeline_sem():
    from services.concurrency import PIPELINE_LLM_SEM
    baseline = PIPELINE_LLM_SEM._value
    seen = {}

    def fake_create(**kwargs):
        seen["thread"] = threading.current_thread().name
        seen["sem_during"] = PIPELINE_LLM_SEM._value
        return _fake_interaction()

    fake_client = MagicMock()
    fake_client.interactions.create.side_effect = fake_create
    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        asyncio.run(call_interaction("안녕", lane="chat"))

    assert seen["thread"].startswith("sasoo-chat")
    assert seen["sem_during"] == baseline  # chat lane은 파이프라인 세마포어를 잡지 않는다


def test_pipeline_lane_runs_on_pipeline_executor_and_holds_sem():
    from services.concurrency import PIPELINE_LLM_SEM
    baseline = PIPELINE_LLM_SEM._value
    seen = {}

    def fake_create(**kwargs):
        seen["thread"] = threading.current_thread().name
        seen["sem_during"] = PIPELINE_LLM_SEM._value
        return _fake_interaction()

    fake_client = MagicMock()
    fake_client.interactions.create.side_effect = fake_create
    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        asyncio.run(call_interaction("안녕", lane="pipeline"))

    assert seen["thread"].startswith("sasoo-pipeline")
    assert seen["sem_during"] == baseline - 1  # 호출 중 슬롯 하나 점유
    assert PIPELINE_LLM_SEM._value == baseline  # 종료 후 반납
