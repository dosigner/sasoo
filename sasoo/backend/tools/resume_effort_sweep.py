"""Resume only the unissued requests of the frozen 2026-10-04 effort sweep.

Run this from an isolated copy of the frozen backend, never from the promoted
product checkout. The original prompt_compare runner remains replay guarded.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from decimal import Decimal
import json
from pathlib import Path
import sys
import time
import unicodedata
from unittest.mock import patch

import anyio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import luna_compare as c
from tools import prompt_compare as p


PREFLIGHT_COUNTS = 16
MAX_NEW_GENERATION_USD = Decimal("0.25")
MAX_TOTAL_GENERATION_USD = Decimal("1")


class ConservativeJournal(c.BudgetJournal):
    """Charge unsettled reservations against the cap without changing them."""

    def spent(self) -> Decimal:
        states = self.states()
        if any(entry.state == "reserved" for entry in states.values()):
            raise c.ComparisonError("An interrupted reservation blocks paid calls")
        return c.historical_cost(c.EVIDENCE) + sum(
            (entry.amount_usd for entry in states.values()), Decimal(0)
        )


def marker(directory: Path, phase: int, kind: str) -> Path:
    name = f"resume-{kind}.json" if phase == 1 else f"resume-{kind}-{phase}.json"
    return directory / name


def audit(directory: Path, journal: ConservativeJournal, phase: int) -> tuple[list[dict], dict, Decimal, int]:
    p.verify_freeze(directory)
    paid = c.read_json(directory / "paid-start.json")
    saved = c.read_json(directory / "offline-plan.json")
    counted = c.read_json(directory / "counted-plan.json")
    if (paid["approved_generation_usd"] != str(MAX_NEW_GENERATION_USD)
            or paid["approved_count_requests"] != 32
            or paid["plan_sha256"] != p.file_hash(directory / "offline-plan.json")):
        raise c.ComparisonError("Original approval or frozen plan differs")
    if len(saved["requests"]) != 16 or len(counted["requests"]) != 16:
        raise c.ComparisonError("Expected exactly 16 frozen requests")
    if [row["key"] for row in saved["requests"]] != [row["key"] for row in counted["requests"]]:
        raise c.ComparisonError("Counted plan order differs from frozen order")

    states = journal.states()
    keys = [row["key"] for row in counted["requests"]]
    existing = [states.get(c.digest({"campaign": str(directory), "key": key})) for key in keys]
    issued = next((index for index, row in enumerate(existing) if row is None), len(existing))
    if (existing[:4] == [None] * 4 or issued < 4 or issued >= 16
            or [row.state if row else None for row in existing[:4]]
            != ["settled", "settled", "settled", "unsettled"]
            or any(row is None or row.state not in ("settled", "unsettled") for row in existing[4:issued])
            or any(row is not None for row in existing[issued:])):
        raise c.ComparisonError("Issued state differs from the recovery boundary")
    if phase == 1 and issued != 4:
        raise c.ComparisonError("First resume starts after the original four requests")
    if phase > 1 and (not marker(directory, phase - 1, "start").exists()
                      or c.read_json(directory / f"{keys[issued-1]}.validation.json")["product_valid"] is not False):
        raise c.ComparisonError("Prior resume did not stop on a recorded failure")
    count_done = PREFLIGHT_COUNTS + issued
    for ordinal in range(1, count_done + 1):
        issued_file = directory / "counts" / f"{ordinal:02}.issued.json"
        result = directory / "counts" / f"{ordinal:02}.result.json"
        expected_key = keys[ordinal - 1] if ordinal <= PREFLIGHT_COUNTS else keys[ordinal - PREFLIGHT_COUNTS - 1]
        if (not issued_file.exists() or not result.exists()
                or c.read_json(issued_file)["key"] != expected_key
                or c.read_json(result)["key"] != expected_key
                or c.read_json(result)["ordinal"] != ordinal
                or c.read_json(result)["state"] != "completed"):
            raise c.ComparisonError("A prior token count is incomplete")
    if any((directory / "counts" / f"{ordinal:02}.{suffix}.json").exists()
           for ordinal in range(count_done + 1, 33) for suffix in ("issued", "result")):
        raise c.ComparisonError("Unexpected resumed token count exists")
    if any((directory / f"{key}.{suffix}.json").exists() for key in keys[issued:]
           for suffix in ("request", "result", "provider", "provider-failure", "validation")):
        raise c.ComparisonError("A supposedly unissued request has an artifact")
    if marker(directory, phase, "start").exists():
        raise c.ComparisonError("Resume already started; do not replay it")

    prior = Decimal(str(paid["generation_spent_before_usd"]))
    original_states = set(c.digest({"campaign": str(directory), "key": key}) for key in keys)
    other = c.historical_cost(c.EVIDENCE) + sum(
        (row.amount_usd for run_id, row in states.items() if run_id not in original_states), Decimal(0)
    )
    if other != prior:
        raise c.ComparisonError("Another paid call changed the original cumulative baseline")
    approved_reserves = []
    for old, row in zip(saved["requests"], counted["requests"], strict=True):
        if any(row[field] != old[field] for field in old):
            raise c.ComparisonError("Preflight request differs from frozen request")
        reserve = Decimal(str(c.reserve_cost_usd(row["model"], row["input_tokens"], 16_000)))
        if reserve != Decimal(str(row["reserved_usd"])):
            raise c.ComparisonError("Frozen reservation differs from current price calculator")
        approved_reserves.append(reserve)
    if sum(approved_reserves, Decimal(0)) != Decimal(str(counted["reserved_usd"])):
        raise c.ComparisonError("Frozen cohort reservation sum differs")

    spent = journal.spent()
    remaining = sum(approved_reserves[issued:], Decimal(0))
    if spent + remaining > MAX_TOTAL_GENERATION_USD or spent + remaining > prior + MAX_NEW_GENERATION_USD:
        raise c.ComparisonError("Conservative full-cohort liability exceeds approved cap")
    return counted["requests"][issued:], paid, spent, issued


async def check(directory: Path, phase: int) -> dict:
    options = p.options_for(directory)
    journal = ConservativeJournal(options)
    pending, paid, spent, issued = audit(directory, journal, phase)
    if await p.capture_all(directory) != c.read_json(directory / "offline-plan.json"):
        raise c.ComparisonError("Frozen product request capture differs")
    return {"phase": phase, "issued_generation": issued,
            "pending_generation": len(pending), "pending_counts": 32 - (PREFLIGHT_COUNTS + issued),
            "conservative_spent_usd": str(spent),
            "remaining_reservation_usd": str(sum((Decimal(str(r["reserved_usd"])) for r in pending), Decimal(0))),
            "approved_generation_usd": paid["approved_generation_usd"]}


async def resume(directory: Path, phase: int) -> None:
    from openai.resources.responses.responses import Responses
    from services import analysis_execution as execution
    from services.llm import openai_client as adapter

    options = p.options_for(directory)
    journal = ConservativeJournal(options)
    client = adapter._get_client()
    if str(client.base_url).rstrip("/") != "https://api.openai.com/v1":
        raise c.ComparisonError("Expected the standard OpenAI endpoint")
    client = client.with_options(max_retries=0, timeout=600.0)
    original_count, original_create = adapter.count_input_tokens, Responses.create
    conditions = p.conditions_for(directory)
    papers = {paper.id: paper for paper in p.papers_for(options)}
    active_key: str | None = None
    count_index = 0

    async def logged_count(prompt, **kwargs):
        nonlocal count_index
        count_index += 1
        if count_index > 32:
            raise c.ComparisonError("Approved token count scope exhausted")
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
                "request_id": getattr(exc, "request_id", None),
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

    with journal.locked():
        summary = await check(directory, phase)
        pending, paid, spent, issued = audit(directory, journal, phase)
        count_index = PREFLIGHT_COUNTS + issued
        c.write_once(marker(directory, phase, "start"), {
            "at": c.now(), "original_paid_start_sha256": p.file_hash(directory / "paid-start.json"),
            "frozen_plan_sha256": p.file_hash(directory / "offline-plan.json"),
            "phase": phase, "issued_before": issued, "generation_remaining": len(pending),
            "count_remaining": 32 - count_index,
            "conservative_spent_before_usd": str(spent),
            "unsettled_policy": "retain_state_and_charge_reservation_for_budget",
            "runtime_source_hashes": c.source_hashes(), "summary": summary,
        })
        options = p.ExperimentOptions(**{**options.model_dump(),
            "budget_total_usd": min(MAX_TOTAL_GENERATION_USD,
                                     Decimal(str(paid["generation_spent_before_usd"])) + MAX_NEW_GENERATION_USD)})
        journal.options = options
        with ExitStack() as stack:
            stack.enter_context(patch.object(adapter, "_get_client", return_value=client))
            stack.enter_context(patch.object(adapter, "count_input_tokens", logged_count))
            stack.enter_context(patch.object(Responses, "create", logged_create))
            for plan in pending:
                active_key = plan["key"]
                paper = papers[plan["paper_id"]]
                instruction, effort = conditions[plan["condition_id"]]
                run_options = p.ExperimentOptions(**{**options.model_dump(), "effort": effort})
                context = (run_options, paper, "gpt-6-luna", "deep_dive",
                           adapter.load_pdf_part(paper.pdf_path), None, None)
                gate = c.LiveGate(plan, context, journal)
                started, started_at = time.monotonic(), c.now()
                result, error_type = None, None
                try:
                    result = await p.invoke_condition(context, gate, instruction)
                except BaseException as exc:
                    error_type = type(exc).__name__
                valid = (gate.raw is not None and gate.raw.get("response_status") == "completed"
                         and not gate.raw.get("incomplete") and isinstance(result, dict)
                         and not execution._is_error_result(result.get("text", "")))
                c.write_once(directory / f"{active_key}.validation.json", {
                    "condition_id": plan["condition_id"], "repeat": 1,
                    "product_valid": bool(valid), "product_result": result,
                    "error_type": error_type, "start": started_at, "end": c.now(),
                    "total_processing_seconds": time.monotonic() - started,
                    "scientific_status": "not_reviewed",
                })
                if not valid or gate.raw.get("response_model") != "gpt-6-luna":
                    raise c.ComparisonError(f"{active_key} did not complete as planned; remaining calls stopped")
    c.write_once(marker(directory, phase, "end"), {"at": c.now(), "completed_new": len(pending),
                                                  "total_count_requests": count_index})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--mode", choices=("check", "resume"), default="check")
    parser.add_argument("--phase", type=int, default=1)
    args = parser.parse_args()
    # The original run IDs used the filesystem's decomposed Korean path.
    directory = Path(unicodedata.normalize("NFD", str(args.campaign.resolve())))
    if args.phase < 1:
        parser.error("phase must be positive")
    if args.mode == "check":
        print(json.dumps(anyio.run(check, directory, args.phase), ensure_ascii=False))
    else:
        anyio.run(resume, directory, args.phase)


if __name__ == "__main__":
    main()
