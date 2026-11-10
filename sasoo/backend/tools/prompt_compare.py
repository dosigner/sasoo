"""Frozen prompt comparison using luna_compare's product path and budget gate."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Literal
import random
import re
import socket
import sys
import time
from unittest.mock import patch

import anyio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import luna_compare as c


def file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class ExperimentOptions(c.Options):
    # This expands only isolated experiments, not the production model registry.
    effort: Literal["low", "medium", "high", "xhigh"] = "high"


def options_for(directory: Path, effort: str = "high") -> ExperimentOptions:
    return ExperimentOptions(campaign=directory.resolve(), models=("gpt-6-luna",),
                             repeat=1, effort=effort)


def conditions_for(directory: Path) -> dict[str, tuple[str, str]]:
    """Return condition -> (instruction, effort) for one isolated comparison."""
    sweep = directory / "efforts.json"
    if not sweep.exists():
        return {key: ((directory / "prompts" / name).read_text(), "high")
                for key, name in (("A", "baseline.txt"), ("B", "v1.txt"))}
    values = c.read_json(sweep)["efforts"]
    if (not isinstance(values, list) or len(values) < 2
            or any(not isinstance(v, str) or v not in {"low", "medium", "high", "xhigh"} for v in values)
            or len(set(values)) != len(values)):
        raise c.ComparisonError("Expected unique supported sweep efforts")
    prompt = (directory / "prompts/v1.txt").read_text()
    return {effort: (prompt, effort) for effort in values}


def papers_for(options: c.Options) -> list[c.Paper]:
    """Use a frozen local manifest, or the original six-paper cohort."""
    manifest = options.campaign / "papers.json"
    if not manifest.exists():
        return c.selected_papers(options)
    papers = [c.Paper.model_validate(row) for row in c.read_json(manifest)["papers"]]
    if not papers or len({p.id for p in papers}) != len(papers):
        raise c.ComparisonError("Empty or duplicate paper selection")
    for paper in papers:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", paper.id):
            raise c.ComparisonError("Unsafe paper identifier")
        if not paper.pdf_path.is_absolute() or file_hash(paper.pdf_path) != paper.pdf_sha256:
            raise c.ComparisonError("PDF path or hash mismatch")
    return papers


async def invoke_condition(context, gate, instruction: str):
    from services import analysis_execution as execution

    # ponytail: process-wide patch; keep this executor serial.
    with c.isolated_product(None), patch.object(execution, "_DEEP_DIVE_INSTRUCTION", instruction):
        return await c.invoke_product(context, gate)


def normalized(spec: c.RequestSpec, instruction: str) -> dict:
    data = spec.model_dump(mode="json")
    parts = data["prompt"]
    if not isinstance(parts, list) or len(parts) != 2:
        raise c.ComparisonError("Expected the product PDF and one instruction part")
    if parts[0]["type"] != "document" or parts[1]["type"] != "text":
        raise c.ComparisonError("Unexpected product input path")
    if not parts[1]["text"].startswith(instruction + "\n\n"):
        raise c.ComparisonError("Frozen instruction was not used")
    parts[1]["text"] = "<CONDITION_PROMPT>" + parts[1]["text"][len(instruction):]
    return data


async def capture_all(directory: Path) -> dict:
    from services import analysis_execution as execution
    from services.llm import openai_client as adapter

    options = options_for(directory)
    papers = papers_for(options)
    conditions = conditions_for(directory)
    effort_sweep = (directory / "efforts.json").exists()
    baseline = (directory / "prompts/baseline.txt").read_text()
    if execution._DEEP_DIVE_INSTRUCTION != baseline:
        raise c.ComparisonError("Production baseline changed")
    requests, comparisons = [], []
    blocked_calls = []

    def blocked(*args, **kwargs):
        blocked_calls.append("network_or_api")
        raise c.ComparisonError("Offline capture attempted an API or network call")

    with ExitStack() as stack:
        for name in ("_get_client", "count_input_tokens", "call_interaction", "stream_interaction"):
            stack.enter_context(patch.object(adapter, name, blocked))
        stack.enter_context(patch.object(socket.socket, "connect", blocked))
        stack.enter_context(patch.object(socket.socket, "connect_ex", blocked))
        for index, paper in enumerate(papers):
            pdf = adapter.load_pdf_part(paper.pdf_path)
            pair = {}
            keys = list(conditions)
            offset = index % len(keys)
            for condition in keys[offset:] + keys[:offset]:
                instruction, effort = conditions[condition]
                context = (options_for(directory, effort), paper, "gpt-6-luna", "deep_dive", pdf, None, None)
                gate = c.RequestGate(16_000)
                try:
                    await invoke_condition(context, gate, instruction)
                except c.Captured:
                    pass
                spec = gate.request
                if spec is None:
                    raise c.ComparisonError("Product request was not captured")
                pair[condition] = spec
                if execution._DEEP_DIVE_INSTRUCTION != baseline:
                    raise c.ComparisonError("Prompt escaped its condition scope")
                safe = spec.model_dump(mode="json")
                safe["prompt"][0].pop("data")
                safe["prompt"][0]["file_reference"] = str(paper.pdf_path)
                key = f"{paper.id}-{condition}-gpt-6-luna-deep_dive-r1"
                requests.append({
                    "key": key, "paper_id": paper.id, "condition_id": condition, "repeat": 1,
                    "model": spec.model, "stage": "deep_dive", "effort": effort,
                    "pdf_sha256": paper.pdf_sha256,
                    "prompt_sha256": sha256(instruction.encode()).hexdigest(),
                    "request_sha256": spec.fingerprint(), "template_sha256": spec.template(),
                    **spec.audit_hashes(), "request": safe,
                })
            normalized_app, wire = [], []
            for key, spec in pair.items():
                app = normalized(spec, conditions[key][0])
                kwargs = spec.count_kwargs()
                if effort_sweep:
                    app["thinking_level"] = kwargs["thinking_level"] = "high"
                normalized_app.append(app)
                wire.append(adapter._build_request(app["prompt"], **kwargs))
                if (spec.model != "gpt-6-luna" or spec.thinking_level != conditions[key][1]
                        or spec.previous_interaction_id is not None or not spec.strict_schema
                        or not spec.single_attempt or spec.max_output_tokens != 16_000
                        or spec.service_tier != "default"):
                    raise c.ComparisonError("Comparison settings drifted")
            if any(value != normalized_app[0] for value in normalized_app[1:]):
                raise c.ComparisonError("Application request differs outside the comparison variable")
            if any(value != wire[0] for value in wire[1:]):
                raise c.ComparisonError("Wire request differs outside the comparison variable")
            comparisons.append({"paper_id": paper.id,
                                "only_instruction_differs": not effort_sweep,
                                "only_effort_differs": effort_sweep,
                                "normalized_wire_sha256": c.digest(wire[0])})
    if blocked_calls or len({r["key"] for r in requests}) != len(conditions) * len(papers):
        raise c.ComparisonError("Offline isolation or request identity failed")
    hashes = c.source_hashes()
    for name in ("tools/prompt_compare.py", "services/llm/gemini_client.py", "services/summary_contract.py"):
        hashes[name] = file_hash(c.BACKEND / name)
    manifest = directory / "papers.json"
    sweep = directory / "efforts.json"
    return {"requests": requests, "comparisons": comparisons, "source_hashes": hashes,
            "paper_manifest_sha256": file_hash(manifest) if manifest.exists() else None,
            "effort_manifest_sha256": file_hash(sweep) if sweep.exists() else None,
            "sdk_version": c.version("openai"), "generation_api_calls": 0, "count_api_calls": 0,
            "network_attempts": len(blocked_calls)}


def verify_freeze(directory: Path) -> None:
    for name, expected in c.read_json(directory / "frozen-files.json").items():
        path = c.REPO / name
        if file_hash(path) != expected:
            raise c.ComparisonError(f"Frozen file changed: {name}")


def review_pack(directory: Path) -> None:
    verify_freeze(directory)
    plans = c.read_json(directory / "offline-plan.json")["requests"]
    random.Random(20261001).shuffle(plans)
    destination = directory / "review-pack"
    destination.mkdir(exist_ok=False)
    mapping = {}
    for index, plan in enumerate(plans, 1):
        label = f"response-{index:03}"
        path = directory / f"{plan['key']}.result.json"
        result = c.read_json(path) if path.exists() else None
        c.write_once(destination / f"{label}.json", {
            "paper_id": plan["paper_id"], "raw_output": result["raw_output"] if result else None,
            "review_state": "pending" if result else "not_generated",
        })
        mapping[label] = {"key": plan["key"], "condition_id": plan["condition_id"]}
    with open(directory / "review-key.private.json", "x", encoding="utf-8",
              opener=lambda path, flags: os.open(path, flags, 0o600)) as handle:
        json.dump(mapping, handle, ensure_ascii=False, indent=2)


async def run(directory: Path, approved_generation_usd: Decimal, approved_count_requests: int) -> None:
    """Called only after explicit approval for this frozen cohort and count scope."""
    from openai.resources.responses.responses import Responses
    from services import analysis_execution as execution
    from services.llm import openai_client as adapter

    if not approved_generation_usd.is_finite() or not 0 < approved_generation_usd <= 1:
        raise c.ComparisonError("This cohort needs a new bounded generation approval")
    verify_freeze(directory)
    saved = c.read_json(directory / "offline-plan.json")
    # Each generation has a preflight count and an immediate count before issue.
    expected_counts = 2 * len(saved["requests"])
    if not expected_counts or approved_count_requests != expected_counts:
        raise c.ComparisonError(f"This cohort needs approval for {expected_counts} count requests")
    if await capture_all(directory) != saved:
        raise c.ComparisonError("Captured product requests changed after freezing")
    options = options_for(directory)
    journal = c.BudgetJournal(options)
    client = adapter._get_client()
    if str(client.base_url).rstrip("/") != "https://api.openai.com/v1":
        raise c.ComparisonError("Frozen pricing requires the standard OpenAI endpoint")
    client = client.with_options(max_retries=0, timeout=600.0)
    original_count, original_create = adapter.count_input_tokens, Responses.create
    conditions = conditions_for(directory)
    papers = {p.id: p for p in papers_for(options)}
    count_index = 0
    active_key = None

    async def logged_count(prompt, **kwargs):
        nonlocal count_index
        count_index += 1
        if count_index > approved_count_requests:
            raise c.ComparisonError("Approved count request scope exhausted")
        record = {"key": active_key, "ordinal": count_index, "start": c.now(),
                  "input_tokens": None, "cost_usd": None, "cost_status": "unknown_tariff",
                  "state": "issued", "seconds": None}
        c.write_once(directory / "counts" / f"{count_index:02}.issued.json", record)
        started = time.monotonic()
        try:
            record["input_tokens"] = await original_count(prompt, **kwargs)
            record["state"] = "completed"
            return record["input_tokens"]
        except BaseException as exc:
            record.update(state="failed", error_type=type(exc).__name__)
            raise
        finally:
            record.update(end=c.now(), seconds=time.monotonic() - started)
            c.write_once(directory / "counts" / f"{count_index:02}.result.json", record)

    def logged_create(resource, *args, **kwargs):
        started, started_at = time.monotonic(), c.now()
        try:
            response = original_create(resource, *args, **kwargs)
        except BaseException as exc:
            c.write_once(directory / f"{active_key}.provider-failure.json", {
                "error_type": type(exc).__name__, "status_code": getattr(exc, "status_code", None),
                "stage": "sdk_create", "response_received": False,
            })
            raise
        finally:
            c.write_once(directory / f"{active_key}.provider-timing.json", {
                "start": started_at, "end": c.now(),
                "generation_seconds": time.monotonic() - started,
            })
        c.write_once(directory / f"{active_key}.provider.json", response.model_dump(mode="json"))
        return response

    with journal.locked(), patch.object(adapter, "_get_client", return_value=client), \
            patch.object(adapter, "count_input_tokens", logged_count), \
            patch.object(Responses, "create", logged_create):
        start_spent = journal.spent()
        # A new invocation cannot replay an interrupted or completed cohort.
        c.write_once(directory / "paid-start.json", {
            "at": c.now(), "approved_generation_usd": str(approved_generation_usd),
            "approved_count_requests": approved_count_requests,
            "generation_spent_before_usd": str(start_spent),
            "count_cost_usd": None, "count_cost_status": "unknown_tariff",
            "plan_sha256": file_hash(directory / "offline-plan.json"),
        })
        ceiling = min(Decimal("1"), start_spent + approved_generation_usd)
        options = ExperimentOptions(**{**options.model_dump(), "budget_total_usd": ceiling})
        journal.options = options
        plans = []
        for plan in saved["requests"]:
            active_key = plan["key"]
            spec_data = dict(plan["request"])
            spec_data["prompt"] = [adapter.load_pdf_part(papers[plan["paper_id"]].pdf_path),
                                   spec_data["prompt"][1]]
            spec = c.RequestSpec.model_validate(spec_data)
            count = await logged_count(spec.prompt, **spec.count_kwargs())
            reserve = c.reserve_cost_usd(spec.model, count, spec.max_output_tokens)
            plans.append({**plan, "input_tokens": count, "reserved_usd": str(reserve)})
        required = sum((Decimal(p["reserved_usd"]) for p in plans), Decimal(0))
        c.write_once(directory / "counted-plan.json", {"requests": plans, "reserved_usd": str(required)})
        if start_spent + required > ceiling:
            raise c.ComparisonError("Entire cohort exceeds the approved generation budget")
        for plan in plans:
            active_key = plan["key"]
            paper = papers[plan["paper_id"]]
            started = time.monotonic()
            started_at = c.now()
            pdf = adapter.load_pdf_part(paper.pdf_path)
            instruction, effort = conditions[plan["condition_id"]]
            run_options = ExperimentOptions(**{**options.model_dump(), "effort": effort})
            context = (run_options, paper, "gpt-6-luna", "deep_dive", pdf, None, None)
            gate = c.LiveGate(plan, context, journal)
            result, error_type = None, None
            try:
                result = await invoke_condition(context, gate, instruction)
            except Exception as exc:
                error_type = type(exc).__name__
                # Unknown liability blocks all later calls through the shared journal.
                journal.spent()
            finally:
                valid = (gate.raw is not None and gate.raw.get("response_status") == "completed"
                         and not gate.raw.get("incomplete") and isinstance(result, dict)
                         and not execution._is_error_result(result.get("text", "")))
                c.write_once(directory / f"{active_key}.validation.json", {
                    "condition_id": plan["condition_id"], "repeat": 1,
                    "product_valid": bool(valid), "product_result": result, "error_type": error_type,
                    "start": started_at, "end": c.now(), "total_processing_seconds": time.monotonic() - started,
                    "scientific_status": "not_reviewed",
                })
            if gate.raw and gate.raw.get("response_model") != "gpt-6-luna":
                raise c.ComparisonError("Returned model differs; preserve evidence and stop")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--mode", choices=("prepare", "check", "run", "review-pack"), default="check")
    parser.add_argument("--approve-new-generation-usd", type=Decimal)
    parser.add_argument("--approve-count-requests", type=int, default=0)
    args = parser.parse_args()
    directory = args.campaign.resolve()
    if args.mode == "review-pack":
        review_pack(directory)
    elif args.mode == "run":
        if args.approve_new_generation_usd is None:
            parser.error("run requires explicit approval for this cohort")
        anyio.run(run, directory, args.approve_new_generation_usd, args.approve_count_requests)
    else:
        captured = anyio.run(capture_all, directory)
        if args.mode == "prepare":
            c.write_once(directory / "offline-plan.json", captured)
        else:
            if (directory / "frozen-files.json").exists():
                verify_freeze(directory)
            if captured != c.read_json(directory / "offline-plan.json"):
                raise c.ComparisonError("Offline plan no longer matches")
        print(json.dumps({"status": "passed", "mode": args.mode, "requests": len(captured["requests"]),
                          "generation_api_calls": 0, "count_api_calls": 0}))


if __name__ == "__main__":
    main()
