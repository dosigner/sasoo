from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import AsyncMock

import anyio
import pytest

from tools import luna_compare as compare


@pytest.fixture
def campaign_env(tmp_path, monkeypatch):
    evidence = tmp_path / "historical"
    (evidence / "models").mkdir(parents=True)
    (evidence / "papers").mkdir()
    compare.write_once(evidence / "models/theory-current.json", {"cost_usd": 0.3568868})
    compare.write_once(evidence / "models/all-usage.json", {"total": {"cost": 0.3568868}})
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7\nmock source")
    paper = {"id": "theory", "pdf_path": str(pdf), "pdf_sha256": sha256(pdf.read_bytes()).hexdigest()}
    compare.write_once(evidence / "papers/manifest.json", {"papers": [paper]})
    monkeypatch.setattr(compare, "EVIDENCE", evidence)
    monkeypatch.setattr(compare, "source_hashes", lambda: {"test": "unchanged"})
    from services.llm import openai_client
    count = AsyncMock(return_value=100_000)
    generate = AsyncMock(return_value={
        "text": '{"section_answers":[],"transfer_checks":[]}', "model": "gpt-6-luna",
        "tokens_in": 100_000, "tokens_out": 500, "tokens_cached": 0, "tokens_cache_write": 0,
        "tokens_thought": 50, "response_model": "gpt-6-luna", "response_status": "completed",
        "service_tier": "default", "interaction_id": "response-1", "usage_complete": True,
    })
    monkeypatch.setattr(openai_client, "count_input_tokens", count)
    monkeypatch.setattr(openai_client, "call_interaction", generate)
    options = compare.Options(campaign=tmp_path / "campaign", papers=("theory",),
                              models=("gpt-6-luna",), qa_reserve_usd=Decimal("0.1"))
    return options, compare.BudgetJournal(options, tmp_path / "global"), count, generate


def execute(options, journal):
    with journal.locked():
        anyio.run(compare.campaign, options, journal)


def paid(options):
    return options.model_copy(update={"mode": "run", "run_paid_approved_usd_1": True})


def test_exact_reservation_prices_and_ceiling():
    assert compare.reserve_cost_usd("gpt-5.6-luna", 100_000, 16_000) == 0.0442
    assert compare.reserve_cost_usd("gpt-6-luna", 100_000, 16_000) == 0.0205
    assert compare.reserve_cost_usd("gpt-6-luna", 272_001, 16_000) == 0.08000025
    assert compare.reserve_cost_usd("gpt-6-luna", 1, 1) == 0.00000063
    with pytest.raises(compare.ComparisonError):
        compare.reserve_cost_usd("unregistered", 100, 100)
    request = compare.RequestSpec(prompt="same input", model="gpt-5.6-luna", max_output_tokens=16000,
        strict_schema=True, response_schema={"type": "object", "properties": {"answer": {"type": "string"}}})
    candidate = request.model_copy(update={"model": "gpt-6-luna"})
    assert request.fingerprint() != candidate.fingerprint()
    assert request.audit_hashes()["model_independent_input_sha256"] == candidate.audit_hashes()["model_independent_input_sha256"]
    assert request.audit_hashes()["app_schema_sha256"] != request.audit_hashes()["wire_schema_sha256"]


def test_actual_stage_dry_run_and_single_paid_call(campaign_env):
    options, journal, count, generate = campaign_env
    execute(options, journal)
    assert count.await_count == 1
    generate.assert_not_awaited()
    plan = compare.read_json(options.campaign / "dry-run.json")
    assert plan["generation_api_calls"] == 0
    assert plan["requests"][0]["reserved_usd"] == "0.0205"
    execute(paid(options), journal)
    assert generate.await_count == 1
    sent = generate.call_args
    counted = count.call_args
    assert sent.args[0] == counted.args[0]
    assert sent.kwargs["single_attempt"] is True
    assert sent.kwargs["service_tier"] == "default"
    assert sent.kwargs["max_output_tokens"] == 16_000
    assert sent.kwargs["strict_schema"] is True
    for key, value in counted.kwargs.items():
        assert sent.kwargs[key] == value
    text = "\n".join(p.read_text() for p in options.campaign.glob("*.json"))
    assert "JVBER" not in text
    execute(paid(options), journal)
    assert generate.await_count == 1
    assert journal.spent() == Decimal("0.3671368")


@pytest.mark.parametrize("field,value", [("tokens_in", None), ("response_model", "unknown"), ("service_tier", "flex"), ("tokens_cached", -1)])
def test_unknown_usage_retains_reservation_and_blocks_resume(campaign_env, field, value):
    options, journal, count, generate = campaign_env
    execute(options, journal)
    generate.return_value[field] = value
    with pytest.raises(compare.ComparisonError, match="Usage is unknown"):
        execute(paid(options), journal)
    entry = next(iter(journal.states().values()))
    assert entry.state == "unsettled"
    assert entry.amount_usd == Decimal("0.0205")
    record = compare.read_json(Path(entry.record))
    assert record["cost_usd"] is None
    assert compare.read_json(next(options.campaign.glob("*.validation.json")))["product_valid"] is False
    with pytest.raises(compare.ComparisonError, match="Unsettled"):
        execute(paid(options), journal)
    assert generate.await_count == 1


def test_api_exception_is_immutable_unsettled_evidence(campaign_env):
    options, journal, count, generate = campaign_env
    execute(options, journal)
    generate.side_effect = ConnectionError("sensitive raw failure")
    with pytest.raises(compare.ComparisonError):
        execute(paid(options), journal)
    record = compare.read_json(next(options.campaign.glob("*.result.json")))
    assert record["error_type"] == "ConnectionError"
    assert record["response"]["response_status"] == "exception"
    assert "sensitive" not in json.dumps(record)
    assert next(iter(journal.states().values())).state == "unsettled"


def test_malformed_product_output_preserved_without_retry(campaign_env):
    options, journal, count, generate = campaign_env
    execute(options, journal)
    generate.return_value["text"] = '{"section_answers":[],"section_answers":[],"transfer_checks":[]}'
    execute(paid(options), journal)
    assert generate.await_count == 1
    validation = compare.read_json(next(options.campaign.glob("*.validation.json")))
    assert validation["product_valid"] is False
    assert "_parse_error" in validation["product_result"]["text"]
    assert next(iter(journal.states().values())).state == "settled"


def test_post_provider_handler_failure_preserves_validation(campaign_env, monkeypatch):
    options, journal, count, generate = campaign_env
    invoke = compare.invoke_product
    async def fail_after_response(context, gate):
        await invoke(context, gate)
        raise compare.ComparisonError("private handler error")
    monkeypatch.setattr(compare, "invoke_product", fail_after_response)
    execute(options, journal)
    with pytest.raises(compare.ComparisonError, match="private handler error"):
        execute(paid(options), journal)
    assert compare.read_json(next(options.campaign.glob("*.validation.json"))) == {"product_valid": False, "product_result": None, "error_type": "ComparisonError"}
    assert next(iter(journal.states().values())).state == "settled" and generate.await_count == 1


def test_budget_hash_and_configuration_fail_closed(campaign_env):
    options, journal, count, generate = campaign_env
    execute(options, journal)
    altered = paid(options).model_copy(update={"max_output_tokens": 24_000})
    with pytest.raises(compare.ComparisonError, match="configuration"):
        execute(altered, journal)
    count.return_value = 1_000_000
    with pytest.raises(compare.ComparisonError, match="allowance"):
        execute(paid(options), journal)
    generate.assert_not_awaited()
    paper = compare.selected_papers(options)[0]
    paper.pdf_path.write_bytes(b"%PDF-1.7\nchanged")
    with pytest.raises(compare.ComparisonError, match="PDF hash"):
        execute(paid(options), journal)


def test_global_journals_exactly_once_and_lock(campaign_env, tmp_path):
    options, journal, count, generate = campaign_env
    with journal.locked():
        journal.reserve("first", Decimal("0.3"))
        journal.record(compare.JournalEntry(run_id="first", state="settled", amount_usd=Decimal("0.2"), at=compare.now()))
        with pytest.raises(compare.ComparisonError, match="lock"):
            with compare.BudgetJournal(options, journal.root).locked():
                pytest.fail("Second executor acquired lock")
    other = options.model_copy(update={"campaign": tmp_path / "other"})
    second = compare.BudgetJournal(other, journal.root)
    with second.locked():
        assert second.spent() == Decimal("0.5568868")
        with pytest.raises(compare.ComparisonError, match="cannot cover"):
            second.reserve("second", Decimal("0.4"))
        second.reserve("second", Decimal("0.1"))
    with pytest.raises(compare.ComparisonError, match="Unsettled"):
        journal.spent()
    with pytest.raises(compare.ComparisonError, match="replayed"):
        journal.reserve("first", Decimal("0.1"))


def test_report_and_blind_review_never_call_api(campaign_env):
    options, journal, count, generate = campaign_env
    execute(options, journal)
    execute(paid(options), journal)
    calls = count.await_count, generate.await_count
    compare.offline_export(options.model_copy(update={"mode": "review-pack"}))
    anonymous = next((options.campaign / "review-pack").glob("*.json")).read_text()
    assert "gpt-6-luna" not in anonymous
    assert (options.campaign / "review-key.private.json").stat().st_mode & 0o777 == 0o600
    compare.offline_export(options.model_copy(update={"mode": "report"}))
    report = next((options.campaign / "reports").rglob("usage.csv")).read_text()
    assert "product_valid" in report and "True" in report
    assert calls == (count.await_count, generate.await_count)


def test_stream_is_capped_and_uses_only_supported_kwargs(campaign_env, monkeypatch):
    options, journal, count, generate = campaign_env
    from services.llm import openai_client
    spec = compare.RequestSpec(prompt="chat", model="gpt-6-luna", max_output_tokens=16000)
    plan = {"key": "chat", "template_sha256": spec.template(), "request_sha256": spec.fingerprint(), "reserved_usd": "0.0205"}
    context = (options, compare.selected_papers(options)[0], "gpt-6-luna", "chat", {}, None, None)
    gate = compare.LiveGate(plan, context, journal)
    calls = []
    async def stream(prompt, **kwargs):
        calls.append(kwargs)
        yield {"type": "token", "text": "answer"}
        yield {"type": "done", **generate.return_value}
    monkeypatch.setattr(openai_client, "stream_interaction", stream)
    async def consume():
        events = []
        async for event in gate.stream_capture("chat", model="gpt-6-luna"):
            if event["type"] == "done":
                assert next(iter(journal.states().values())).state == "settled"
                assert list(options.campaign.glob("*.result.json"))
            events.append(event)
        return events
    with journal.locked():
        anyio.run(consume)
    assert len(calls) == 1
    assert calls[0]["max_output_tokens"] == 16000
    assert calls[0]["single_attempt"] is True
    assert "response_schema" not in calls[0] and "strict_schema" not in calls[0]
    with journal.locked(), pytest.raises(compare.ComparisonError, match="retry blocked"):
        anyio.run(consume)
    assert len(calls) == 1


def test_cli_defaults_and_rejects_unknown_inputs(tmp_path):
    options = compare.parse_args(["--campaign", str(tmp_path)])
    assert options.mode == "dry-run"
    assert options.papers == compare.PAPERS
    assert options.budget_total_usd == 1
    with pytest.raises(ValueError):
        compare.parse_args(["--campaign", str(tmp_path), "--budget-total-usd", "2"])


@pytest.mark.parametrize("scope,expected_calls", [("core-chain", 3), ("role-smoke", 2)])
def test_actual_qa_product_paths_and_response_chain(campaign_env, monkeypatch, tmp_path, scope, expected_calls):
    options, journal, count, generate = campaign_env
    options = options.model_copy(update={"scope": scope})
    journal.options = options
    directory = tmp_path / "source"
    directory.mkdir()
    image_path = directory / "figure.png"
    image_path.write_bytes(b"mock raster")
    qa = compare.QAInput(directory=directory,
        paper={"id": 1, "folder_name": "paper", "title": "Paper", "domain": "ai_ml", "agent_used": "neural"},
        figures=[{"id": 1, "figure_num": "Figure 1", "quality": "good", "caption": "Original caption",
                  "file_path": str(image_path)}], tables=[])
    monkeypatch.setattr(compare, "load_qa", lambda options, paper: qa)
    from api import analysis_routes, figure_service
    from services.llm import openai_client
    for module in (analysis_routes, figure_service):
        monkeypatch.setattr(module, "load_or_build_document_context", lambda directory: {"phase_inputs": {"chat": "paper text", "figure_detail": "paper text"}})
    sent = []
    async def generate_stage(prompt, **kwargs):
        sent.append((prompt, kwargs))
        return {**generate.return_value, "interaction_id": f"response-{len(sent)}"}
    async def stream(prompt, *, lane, model, system_instruction, thinking_level, store, max_output_tokens, single_attempt, service_tier):
        sent.append((prompt, {"model": model, "max_output_tokens": max_output_tokens, "single_attempt": single_attempt}))
        yield {"type": "token", "text": "answer"}
        yield {"type": "done", **generate.return_value}
    monkeypatch.setattr(openai_client, "call_interaction", generate_stage)
    monkeypatch.setattr(openai_client, "stream_interaction", stream)
    execute(options, journal)
    assert not sent and count.await_count == expected_calls
    execute(paid(options), journal)
    assert len(sent) == expected_calls
    assert all(kwargs["max_output_tokens"] == 16000 and kwargs["single_attempt"] for _, kwargs in sent)
    if scope == "core-chain":
        assert [kwargs["previous_interaction_id"] for _, kwargs in sent] == [None, "response-1", "response-2"]
        assert isinstance(sent[0][0], list)
        assert isinstance(sent[1][0], str)
        assert [call.kwargs["thinking_level"] for call in count.call_args_list[-3:]] == ["low", "medium", "high"]
    else:
        assert sent[0][0][0]["type"] == "image"
    execute(paid(options), journal)
    assert len(sent) == expected_calls
