import asyncio
import os
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.llm.interactions_client import call_interaction, upload_pdf_for_paper
import services.llm.interactions_client as interactions_client
from services.models import MODEL_FLASH_HQ


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
    assert kwargs["model"] == MODEL_FLASH_HQ
    assert set(kwargs.keys()) == {"model", "input", "system_instruction", "store"}


def test_call_interaction_tokens_out_sums_output_and_thought_tokens():
    """청구 기준: tokens_out은 total_output_tokens + total_thought_tokens여야 한다
    (라이브 실측 — total_output_tokens는 thinking 토큰을 포함하지 않지만
    Gemini는 thinking 토큰도 출력 단가로 과금한다)."""
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = _fake_interaction(total_thought_tokens=762)
    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        result = asyncio.run(call_interaction("안녕", lane="pipeline"))
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


class _FakeApiError(Exception):
    """google-genai의 ClientError/ServerError를 흉내낸다 — 판정 근거는 int인 .code."""

    def __init__(self, code):
        super().__init__(f"{code} error")
        self.code = code


def test_call_interaction_does_not_retry_non_retryable_status():
    """400(저작권 필터 등)은 몇 번 보내도 같은 응답이다 — 1회로 끝내야 한다.

    기존에는 400도 3회 시도 + 10초 대기를 했고, 상위 gemini_parser의 페이지 재시도까지
    곱해져 실패 페이지 하나당 API 6회 + 순수 대기 20초를 버렸다.
    """
    fake_client = MagicMock()
    fake_client.interactions.create.side_effect = _FakeApiError(400)

    with patch("services.llm.interactions_client._get_client", return_value=fake_client), \
         patch("services.llm.interactions_client._RETRY_DELAYS", [0, 0]):
        with pytest.raises(RuntimeError, match="non-retryable"):
            asyncio.run(call_interaction("필터", lane="pipeline"))

    assert fake_client.interactions.create.call_count == 1


@pytest.mark.parametrize("code", [429, 500, 503, 408])
def test_call_interaction_retries_transient_status(code):
    """쿼터(429)·서버(5xx)·타임아웃(408)은 시간이 지나면 풀리므로 계속 재시도한다."""
    fake_client = MagicMock()
    fake_client.interactions.create.side_effect = [
        _FakeApiError(code), _FakeApiError(code), _fake_interaction(),
    ]

    with patch("services.llm.interactions_client._get_client", return_value=fake_client), \
         patch("services.llm.interactions_client._RETRY_DELAYS", [0, 0]):
        result = asyncio.run(call_interaction("일시 오류", lane="pipeline"))

    assert result["text"] == "결과"
    assert fake_client.interactions.create.call_count == 3


def test_call_interaction_releases_pipeline_sem_while_backing_off():
    """백오프 대기 중에는 pipeline 세마포어 슬롯을 반납해야 한다.

    예전에는 _sync_call 안의 time.sleep이 슬롯을 쥔 채 잠들어, 4개뿐인 동시 호출
    슬롯 하나가 대기 시간 내내 놀았다. 재시도 루프가 코루틴 레벨로 올라왔으므로
    대기 중 세마포어 값이 원상 복구돼 있어야 한다.
    """
    from services.concurrency import PIPELINE_LLM_CONCURRENCY, pipeline_llm_sem

    observed: list[int] = []

    async def _probe(delay):
        # 백오프 대기 시점에 세마포어가 비어 있는지(=슬롯이 반납됐는지) 관찰한다.
        observed.append(pipeline_llm_sem()._value)

    fake_client = MagicMock()
    fake_client.interactions.create.side_effect = [_FakeApiError(503), _fake_interaction()]

    async def _run():
        with patch("services.llm.interactions_client._get_client", return_value=fake_client), \
             patch("services.llm.interactions_client.asyncio.sleep", _probe):
            return await call_interaction("백오프", lane="pipeline")

    result = asyncio.run(_run())

    assert result["text"] == "결과"
    assert observed == [PIPELINE_LLM_CONCURRENCY], "백오프 중 세마포어 슬롯이 반납되지 않았다"


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
    assert kwargs["model"] == MODEL_FLASH_HQ
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
        result = asyncio.run(_collect(interactions_client.stream_interaction("hi", lane="chat")))

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


def _write_pdf(tmp_path, name="fake.pdf"):
    """실제 파일을 만든다 — 업로드가 경로가 아니라 열린 파일 객체를 넘기므로 존재해야 한다."""
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.4 fake")
    return str(path)


def test_upload_pdf_for_paper_expired_reuploads_and_updates(tmp_path):
    pdf_path = _write_pdf(tmp_path)
    past_expiry = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    fake_fetch_one = AsyncMock(return_value=_paper_row(uri="uri-expired", expires_at=past_expiry))
    fake_execute_update = AsyncMock()
    fake_client = MagicMock()
    fake_client.files.upload.return_value = SimpleNamespace(uri="uri-new")

    with patch("models.database.fetch_one", fake_fetch_one), \
         patch("models.database.execute_update", fake_execute_update), \
         patch("services.llm.interactions_client._get_client", return_value=fake_client):
        uri = asyncio.run(upload_pdf_for_paper(2, pdf_path))

    assert uri == "uri-new"
    fake_client.files.upload.assert_called_once()
    kwargs = fake_client.files.upload.call_args.kwargs
    assert kwargs["config"]["mime_type"] == "application/pdf"
    fake_execute_update.assert_called_once()
    update_args = fake_execute_update.call_args.args[1]
    assert update_args[0] == "uri-new"
    assert update_args[2] == 2


def test_upload_pdf_for_paper_no_cache_uploads_and_updates(tmp_path):
    pdf_path = _write_pdf(tmp_path)
    fake_fetch_one = AsyncMock(return_value=None)
    fake_execute_update = AsyncMock()
    fake_client = MagicMock()
    fake_client.files.upload.return_value = SimpleNamespace(uri="uri-fresh")

    with patch("models.database.fetch_one", fake_fetch_one), \
         patch("models.database.execute_update", fake_execute_update), \
         patch("services.llm.interactions_client._get_client", return_value=fake_client):
        uri = asyncio.run(upload_pdf_for_paper(3, pdf_path))

    assert uri == "uri-fresh"
    fake_client.files.upload.assert_called_once()
    fake_execute_update.assert_called_once()


def test_upload_pdf_for_paper_non_ascii_filename_passes_file_object(tmp_path):
    """한글 파일명 회귀 방지.

    경로를 넘기면 SDK가 os.path.basename을 X-Goog-Upload-File-Name 헤더에 싣고
    (google/genai/_extra_utils.py), HTTP 헤더는 ASCII만 담을 수 있어 한글이면
    'ascii' codec can't encode로 죽는다 → pdf_uri=None → 분석 5단계가 논문 전문을
    매번 재전송한다. 열린 파일 객체를 넘겨 그 헤더 분기 자체를 타지 않아야 한다.
    """
    pdf_path = _write_pdf(tmp_path, "2026-06-06_참고논문_OAM.pdf")
    fake_fetch_one = AsyncMock(return_value=None)
    fake_execute_update = AsyncMock()
    fake_client = MagicMock()
    fake_client.files.upload.return_value = SimpleNamespace(uri="uri-korean")

    with patch("models.database.fetch_one", fake_fetch_one), \
         patch("models.database.execute_update", fake_execute_update), \
         patch("services.llm.interactions_client._get_client", return_value=fake_client):
        uri = asyncio.run(upload_pdf_for_paper(7, pdf_path))

    assert uri == "uri-korean"
    kwargs = fake_client.files.upload.call_args.kwargs
    # 경로가 아니라 읽기 가능한 파일 객체여야 한다(헤더 분기 회피의 핵심).
    assert not isinstance(kwargs["file"], (str, os.PathLike))
    assert hasattr(kwargs["file"], "read")
    # 원본 한글 이름은 JSON 본문으로 가는 display_name에 보존된다.
    assert kwargs["config"]["display_name"] == "2026-06-06_참고논문_OAM.pdf"


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


def test_upload_pdf_for_paper_concurrent_calls_upload_once(tmp_path):
    """동시 호출 시 두 번째 호출은 락 대기 후 캐시를 재확인하고 업로드를 건너뛰어야 한다.

    파일 업로드(스레드풀에서 실행)를 threading.Event로 실제 블로킹시켜, 두 번째
    호출이 락 획득을 시도하는 동안 첫 번째 호출이 확실히 업로드 중이도록 만든다
    (타이밍에 의존하는 레이스 대신 결정적으로 동시성을 재현).
    """
    interactions_client._upload_locks.clear()
    pdf_path = _write_pdf(tmp_path)

    started = threading.Event()
    proceed = threading.Event()
    table = _FakePapersTable()

    def fake_upload(file, config=None):
        started.set()
        assert proceed.wait(timeout=2), "두 번째 호출이 락 대기에 들어가지 않았다"
        return SimpleNamespace(uri="uri-concurrent")

    fake_client = MagicMock()
    fake_client.files.upload.side_effect = fake_upload

    async def _run_concurrently():
        t1 = asyncio.create_task(upload_pdf_for_paper(4, pdf_path))
        for _ in range(200):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set(), "첫 번째 호출이 업로드를 시작하지 않았다"

        t2 = asyncio.create_task(upload_pdf_for_paper(4, pdf_path))
        # t2가 락 획득을 시도하고 대기 상태로 들어갈 시간을 준다.
        await asyncio.sleep(0.1)
        proceed.set()
        return await asyncio.gather(t1, t2)

    with patch("models.database.fetch_one", table.fetch_one), \
         patch("models.database.execute_update", table.execute_update), \
         patch("services.llm.interactions_client._get_client", return_value=fake_client):
        results = asyncio.run(_run_concurrently())

    assert results == ["uri-concurrent", "uri-concurrent"]
    fake_client.files.upload.assert_called_once()
    assert table.update_calls == 1


# ---------------------------------------------------------------------------
# Lane isolation — 채팅이 파이프라인 풀·세마포어에 절대 얽히지 않음을 고정한다.
# ---------------------------------------------------------------------------

def test_call_interaction_requires_lane():
    with pytest.raises(TypeError):
        asyncio.run(call_interaction("안녕"))  # lane 없이는 호출 자체가 성립하지 않는다


def test_chat_lane_runs_on_chat_executor_and_skips_pipeline_sem():
    from services.concurrency import pipeline_llm_sem
    seen = {}

    async def _run():
        # 같은 루프 안에서 accessor를 부르면 call_interaction이 쓰는 것과 동일한
        # 루프별 세마포어 객체를 얻는다(크로스루프 바인딩 방지 리팩터 후 계약).
        sem = pipeline_llm_sem()
        seen["baseline"] = sem._value

        def fake_create(**kwargs):
            seen["thread"] = threading.current_thread().name
            seen["sem_during"] = sem._value
            return _fake_interaction()

        fake_client = MagicMock()
        fake_client.interactions.create.side_effect = fake_create
        with patch("services.llm.interactions_client._get_client", return_value=fake_client):
            await call_interaction("안녕", lane="chat")

    asyncio.run(_run())
    assert seen["thread"].startswith("sasoo-chat")
    assert seen["sem_during"] == seen["baseline"]  # chat lane은 파이프라인 세마포어를 잡지 않는다


def test_pipeline_lane_runs_on_pipeline_executor_and_holds_sem():
    from services.concurrency import pipeline_llm_sem
    seen = {}

    async def _run():
        sem = pipeline_llm_sem()  # 같은 루프 → call_interaction이 쓰는 것과 동일 객체
        seen["baseline"] = sem._value

        def fake_create(**kwargs):
            seen["thread"] = threading.current_thread().name
            seen["sem_during"] = sem._value
            return _fake_interaction()

        fake_client = MagicMock()
        fake_client.interactions.create.side_effect = fake_create
        with patch("services.llm.interactions_client._get_client", return_value=fake_client):
            await call_interaction("안녕", lane="pipeline")
        seen["after"] = sem._value

    asyncio.run(_run())
    assert seen["thread"].startswith("sasoo-pipeline")
    assert seen["sem_during"] == seen["baseline"] - 1  # 호출 중 슬롯 하나 점유
    assert seen["after"] == seen["baseline"]  # 종료 후 반납


def test_pipeline_sem_survives_separate_event_loops():
    """F0 회귀: 서로 다른 asyncio.run 루프가 순차로 pipeline 세마포어를 경합해도
    'bound to a different event loop' RuntimeError가 나지 않아야 한다.

    (리뷰어가 경험적으로 재현한 시나리오의 역: 중첩 asyncio.run 루프의 gemini 파서와
    메인 루프의 pipeline 호출이 같은 전역 세마포어를 경합하면, 먼저 대기 경로를 밟은
    루프에 세마포어가 영구 바인딩되어 이후 다른 루프의 모든 pipeline 호출이 죽었다.)
    """
    from services.concurrency import pipeline_llm_sem

    async def _contend():
        # 대기 경로(value<=0)를 강제로 태워야 루프 바인딩이 일어난다.
        sem = pipeline_llm_sem()
        # 전체 슬롯을 소진한 뒤 한 acquire를 더 걸어 실제로 대기시킨다.
        for _ in range(sem._value):
            await sem.acquire()
        waiter = asyncio.ensure_future(sem.acquire())
        await asyncio.sleep(0)  # waiter가 대기 경로에 진입 → 이 루프에 바인딩
        sem.release()
        await waiter
        # 복구 불필요: 루프별 세마포어는 asyncio.run 종료 시 루프와 함께 폐기된다.

    # 두 개의 완전히 별개인 asyncio.run 루프에서 순차로 경합한다.
    asyncio.run(_contend())
    asyncio.run(_contend())  # 크로스루프 바인딩이면 여기서 RuntimeError로 죽는다

    # (teeth) 같은 시나리오를 프로세스-전역 세마포어 하나로 돌리면 실제로 죽는지 확인해,
    # 위 통과가 우연이 아니라 루프별 레지스트리 덕분임을 문서화한다.
    shared = asyncio.Semaphore(1)

    async def _contend_shared():
        await shared.acquire()
        w = asyncio.ensure_future(shared.acquire())
        await asyncio.sleep(0)
        shared.release()
        await w
        shared.release()

    asyncio.run(_contend_shared())
    with pytest.raises(RuntimeError, match="bound to a different event loop"):
        asyncio.run(_contend_shared())


# ---------------------------------------------------------------------------
# SDK 계약 테스트 — 한글 파일명 업로드 수정이 기대는 google-genai 내부 분기를 고정한다.
#
# 서드파티 동작을 테스트하는 것이 보통은 범위 밖이지만, 여기서는 우리 수정이 성립하는
# 근거 그 자체다. SDK가 이 분기를 바꾸면 수정이 조용히 무력화되고 한글 파일명 논문이
# 다시 텍스트 폴백으로 떨어진다(사용자 눈엔 그냥 느려질 뿐 아무 에러도 안 보인다).
# 네트워크 없이 SDK의 요청 준비 단계만 호출한다.
# ---------------------------------------------------------------------------

def test_sdk_path_upload_puts_non_ascii_filename_in_header(tmp_path):
    """경로를 넘기면 SDK가 파일명을 HTTP 헤더에 싣고, 한글이면 ascii 인코딩이 깨진다."""
    from google.genai import _extra_utils

    pdf = tmp_path / "2026_참고논문_OAM.pdf"
    pdf.write_bytes(b"%PDF-1.4 x")

    options, _, _ = _extra_utils.prepare_resumable_upload(
        str(pdf), user_mime_type="application/pdf"
    )
    header = options.headers.get("X-Goog-Upload-File-Name")

    assert header == "2026_참고논문_OAM.pdf"
    with pytest.raises(UnicodeEncodeError):
        header.encode("ascii")  # 프로덕션에서 관측된 바로 그 실패


def test_sdk_file_object_upload_omits_the_filename_header(tmp_path):
    """파일 객체를 넘기면 그 헤더 분기를 아예 타지 않아 한글 파일명이 안전하다."""
    from google.genai import _extra_utils

    pdf = tmp_path / "2026_참고논문_OAM.pdf"
    pdf.write_bytes(b"%PDF-1.4 x")

    with open(pdf, "rb") as handle:
        options, size_bytes, mime_type = _extra_utils.prepare_resumable_upload(
            handle, user_mime_type="application/pdf"
        )

    assert "X-Goog-Upload-File-Name" not in options.headers
    assert all(str(value).isascii() for value in options.headers.values())
    assert size_bytes == len(b"%PDF-1.4 x")
    assert mime_type == "application/pdf"


def test_sdk_file_object_upload_requires_mime_type(tmp_path):
    """파일 객체 경로에선 mime_type이 필수다 — 빠뜨리면 업로드가 성립하지 않는다."""
    from google.genai import _extra_utils

    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4 x")

    with open(pdf, "rb") as handle:
        with pytest.raises(ValueError, match="mime type"):
            _extra_utils.prepare_resumable_upload(handle)


def test_call_interaction_passes_max_output_tokens():
    """출력 상한을 generation_config에 실어 보낸다.

    폭주 반복(마지막 자유서술 필드에서 종료 토큰을 못 내는 실패)이 나면 모델은
    64K 출력 상한까지 필러를 뱉는다. 실측 2026-08-16: 시도당 65,522 토큰,
    그중 92.4%가 `(Fin). (End). Done!` 류 필러였다. 상한을 걸면 그 낭비가
    결정론적으로 묶인다. API 레퍼런스(ai.google.dev/static/api/interactions.md.txt,
    2026-08-17 확인)의 GenerationConfig에 max_output_tokens가 있다.
    """
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = _fake_interaction()
    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        asyncio.run(call_interaction(
            "안녕", lane="pipeline", thinking_level="medium", max_output_tokens=24000,
        ))
    generation_config = fake_client.interactions.create.call_args.kwargs["generation_config"]
    assert generation_config["max_output_tokens"] == 24000
    assert generation_config["thinking_level"] == "medium"


def test_call_interaction_max_output_tokens_alone_builds_generation_config():
    """thinking_level 없이 상한만 줘도 generation_config이 만들어져야 한다."""
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = _fake_interaction()
    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        asyncio.run(call_interaction("안녕", lane="pipeline", max_output_tokens=1000))
    assert fake_client.interactions.create.call_args.kwargs["generation_config"] == {
        "max_output_tokens": 1000
    }


def test_call_interaction_omits_max_output_tokens_when_not_given():
    """상한을 안 주면 키 자체가 없어야 한다 — 기본값을 우리가 정하지 않는다."""
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = _fake_interaction()
    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        asyncio.run(call_interaction("안녕", lane="pipeline", thinking_level="low"))
    assert fake_client.interactions.create.call_args.kwargs["generation_config"] == {
        "thinking_level": "low"
    }
