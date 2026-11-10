"""Exercise the real product path with synthetic provider responses, offline."""

from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anyio
from openai import OpenAI
from openai.resources.responses.responses import Responses
import pytest

from tools import luna_compare as c
from tools import prompt_compare as p


@pytest.mark.parametrize("paper_count,sweep", [(6, False), (8, False), (4, True)])
def test_prompt_cohort_offline_and_bounded_execution(tmp_path, monkeypatch, paper_count, sweep):
    from services import analysis_execution as execution
    from services.llm import openai_client as adapter

    campaign = tmp_path / "cohort"
    (campaign / "prompts").mkdir(parents=True)
    baseline = execution._DEEP_DIVE_INSTRUCTION
    (campaign / "prompts/baseline.txt").write_text(baseline)
    (campaign / "prompts/v1.txt").write_text("Test completion criteria.\n\n" + baseline)
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF-1.7\nsynthetic offline test")
    names = [*c.PAPERS, "transfer_one", "transfer_two"][:paper_count]
    papers = [c.Paper(id=name, pdf_path=pdf, pdf_sha256=p.file_hash(pdf)) for name in names]
    if paper_count == 6:
        monkeypatch.setattr(c, "selected_papers", lambda options: papers)
    else:
        c.write_once(campaign / "papers.json", {"papers": [p.model_dump(mode="json") for p in papers]})
    efforts = ["low", "medium", "high", "xhigh"]
    if sweep:
        c.write_once(campaign / "efforts.json", {"efforts": efforts})
    generation_count = paper_count * (4 if sweep else 2)
    count_limit = generation_count * 2
    count = AsyncMock(return_value=1000)
    monkeypatch.setattr(adapter, "count_input_tokens", count)
    plan = anyio.run(p.capture_all, campaign)
    assert count.await_count == 0
    expected_conditions = ([e for i in range(paper_count) for e in efforts[i:] + efforts[:i]]
                           if sweep else list("ABBA" * (paper_count // 2)))
    assert [r["condition_id"] for r in plan["requests"]] == expected_conditions
    if sweep:
        assert len({r["prompt_sha256"] for r in plan["requests"]}) == 1
        assert all(row["only_effort_differs"] for row in plan["comparisons"])
    assert len({r["request_sha256"] for r in plan["requests"][:2]}) == 2
    assert execution._DEEP_DIVE_INSTRUCTION == baseline
    c.write_once(campaign / "offline-plan.json", plan)
    c.write_once(campaign / "frozen-files.json", {})

    client = OpenAI(api_key="offline-test-placeholder")
    monkeypatch.setattr(adapter, "_get_client", lambda: client)
    original_journal = c.BudgetJournal
    monkeypatch.setattr(c, "BudgetJournal", lambda options: original_journal(options, tmp_path / "budget"))
    monkeypatch.setattr(c, "historical_cost", lambda root: Decimal("0.61883258"))
    calls = []

    def fake_create(resource, **kwargs):
        calls.append(kwargs)
        text = '{"section_answers":[],"transfer_checks":[]}'
        if len(calls) == 2:
            text = '{"section_answers":[],"section_answers":[],"transfer_checks":[]}'
        return SimpleNamespace(output_text=text, model="gpt-6-luna", status="completed",
            incomplete_details=None, service_tier="default", id=f"offline-{len(calls)}",
            usage=SimpleNamespace(input_tokens=1000, output_tokens=100,
                input_tokens_details=SimpleNamespace(cached_tokens=0, cache_write_tokens=1000),
                output_tokens_details=SimpleNamespace(reasoning_tokens=20)),
            model_dump=lambda **kw: {"synthetic_test_only": True, "output_text": text})

    monkeypatch.setattr(Responses, "create", fake_create)
    with pytest.raises(c.ComparisonError, match="approval"):
        anyio.run(p.run, campaign, Decimal("0"), count_limit)
    with pytest.raises(c.ComparisonError, match="count requests"):
        anyio.run(p.run, campaign, Decimal("0.25"), count_limit - 1)
    assert not calls and count.await_count == 0
    anyio.run(p.run, campaign, Decimal("0.25"), count_limit)
    assert len(calls) == generation_count and count.await_count == count_limit
    assert all(x["model"] == "gpt-6-luna" and x["max_output_tokens"] == 16000 for x in calls)
    if sweep:
        assert [x["reasoning"]["effort"] for x in calls] == expected_conditions
    assert not any("previous_response_id" in x or "tools" in x for x in calls)
    assert len(list(campaign.glob("*.provider.json"))) == generation_count
    validations = [c.read_json(campaign / f"{x['key']}.validation.json") for x in plan["requests"]]
    assert [x["product_valid"] for x in validations] == [True, False] + [True] * (generation_count - 2)
    assert all(c.read_json(x)["cost_usd"] is None for x in (campaign / "counts").glob("*.result.json"))
    journal = original_journal(p.options_for(campaign), tmp_path / "budget")
    assert len(journal.states()) == generation_count
    assert all(x.state == "settled" for x in journal.states().values())
    with pytest.raises(FileExistsError):
        anyio.run(p.run, campaign, Decimal("0.25"), count_limit)
    assert len(calls) == generation_count and count.await_count == count_limit
    p.review_pack(campaign)
    pack = "".join(x.read_text() for x in (campaign / "review-pack").glob("*.json"))
    assert "condition_id" not in pack and "gpt-6-luna" not in pack and "seconds" not in pack
    assert (campaign / "review-key.private.json").stat().st_mode & 0o777 == 0o600
    assert len(json.loads((campaign / "review-key.private.json").read_text())) == generation_count

    failed = tmp_path / "failed-cohort"
    names = ["prompts/baseline.txt", "prompts/v1.txt", "offline-plan.json", "frozen-files.json"]
    if (campaign / "papers.json").exists():
        names.append("papers.json")
    if sweep:
        names.append("efforts.json")
    for name in names:
        destination = failed / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((campaign / name).read_bytes())

    def timeout(resource, **kwargs):
        raise TimeoutError("private exception text must not be logged")

    monkeypatch.setattr(Responses, "create", timeout)
    with pytest.raises(c.ComparisonError, match="Unsettled"):
        anyio.run(p.run, failed, Decimal("0.25"), count_limit)
    failure = c.read_json(next(failed.glob("*.provider-failure.json")))
    assert failure["error_type"] == "TimeoutError"
    record = c.read_json(next(failed.glob("*.result.json")))
    assert record["cost_usd"] is None and record["cost_status"] == "unsettled"
    assert "private exception" not in json.dumps(record)
    assert len(list(failed.glob("*.result.json"))) == 1
    assert count.await_count == count_limit + generation_count + 1


def test_custom_sources_reject_changed_pdf_duplicate_ids_and_path_ids(tmp_path):
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF-1.7 offline")
    row = {"id": "transfer_one", "pdf_path": str(pdf), "pdf_sha256": p.file_hash(pdf)}
    manifest = tmp_path / "papers.json"
    options = p.options_for(tmp_path)
    manifest.write_text(json.dumps({"papers": [row, row]}))
    with pytest.raises(c.ComparisonError, match="duplicate"):
        p.papers_for(options)
    manifest.write_text(json.dumps({"papers": [{**row, "id": "../escape"}]}))
    with pytest.raises(c.ComparisonError, match="identifier"):
        p.papers_for(options)
    manifest.write_text(json.dumps({"papers": [row]}))
    pdf.write_bytes(b"changed PDF")
    with pytest.raises(c.ComparisonError, match="hash"):
        p.papers_for(options)


@pytest.mark.parametrize("efforts", [["medium", "medium"], ["high"], ["low", "unknown"], ["high", None]])
def test_sweep_rejects_ambiguous_conditions(tmp_path, efforts):
    (tmp_path / "efforts.json").write_text(json.dumps({"efforts": efforts}))
    with pytest.raises(c.ComparisonError, match="supported sweep"):
        p.conditions_for(tmp_path)
