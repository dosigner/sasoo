# /// script
# requires-python = ">=3.12"
# dependencies = ["anyio", "pydantic>=2"]
# ///
# Run with the installed app environment: .venv/bin/python tools/luna_compare.py --help
# noqa: SIZE_OK -- The approved plan requires one self-contained audit CLI.
"""Immutable PDF comparison through product stages, with a shared budget journal."""

from __future__ import annotations

import argparse
from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import csv
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import random
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from typing import Final, Literal, assert_never
from unittest.mock import AsyncMock, patch

import anyio
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

BACKEND: Final = Path(__file__).resolve().parents[1]
REPO: Final = BACKEND.parents[1]
EVIDENCE: Final = REPO / "docs/validation/assets/v1.0.1-summary-reading"
AUDIT_ROOT: Final = REPO / "docs/validation/assets/gpt-6-luna"
PAPERS: Final = ("theory", "robotics2", "review", "bio1", "bio2", "robotics1")
MODELS: Final = ("gpt-5.6-luna", "gpt-6-luna")
JSON_OBJECT: Final = TypeAdapter(dict[str, JsonValue])
sys.path.insert(0, str(BACKEND))


class ComparisonError(RuntimeError):
    pass


class Captured(BaseException):
    """Stop product execution before generation, including product retry handlers."""


class Options(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["dry-run", "run", "review-pack", "report"] = "dry-run"
    scope: Literal["deep-dive", "core-chain", "role-smoke"] = "deep-dive"
    campaign: Path
    papers: tuple[str, ...] = PAPERS
    models: tuple[str, ...] = MODELS
    input_mode: Literal["pdf"] = "pdf"
    effort: Literal["high"] = "high"
    explanation_level: str = "undergrad"
    max_output_tokens: int = Field(default=16_000, gt=0, le=32_000)
    budget_total_usd: Decimal = Field(default=Decimal("1"), gt=0, le=1)
    qa_reserve_usd: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    price_multiplier: Decimal = Field(default=Decimal("1"), ge=1)
    run_paid_approved_usd_1: bool = False
    qa_source_db: Path | None = None
    qa_paper_id: int | None = None
    qa_paper_dir: Path | None = None
    repeat: int = Field(default=0, ge=0)


class Paper(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    id: str
    pdf_path: Path
    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class JournalEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    run_id: str
    state: Literal["reserved", "settled", "unsettled"]
    amount_usd: Decimal = Field(ge=0, allow_inf_nan=False)
    at: str
    record: str | None = None


def digest(value: JsonValue) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read_json(path: Path) -> dict[str, JsonValue]:
    return JSON_OBJECT.validate_json(path.read_text(encoding="utf-8"))


def write_once(path: Path, data: JsonValue) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())


def append_line(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def reserve_cost_usd(model: str, input_tokens: int, output_cap: int) -> float:
    from services.pricing import PRICING, calc_cost

    if model not in PRICING or model not in MODELS:
        raise ComparisonError("Model has no approved comparison price")
    calc_cost(model, input_tokens, output_cap, cache_write_tokens=input_tokens)
    rates = PRICING[model]
    long_context = input_tokens > 272_000
    raw = (Decimal(input_tokens) * Decimal(str(rates["cache_write"])) * (2 if long_context else 1)
           + Decimal(output_cap) * Decimal(str(rates["output"])) * (Decimal("1.5") if long_context else 1)) / 1_000_000
    return float(raw.quantize(Decimal("0.00000001"), rounding=ROUND_CEILING))


def historical_cost(root: Path) -> Decimal:
    """Read each historical execution once; aggregate files are cross-checks only."""
    records = [p for p in (root / "models").rglob("*.json")
               if re.fullmatch(r"(?:bio[12]|robotics[12]|theory|review)-(?:baseline|current)\.json", p.name)]
    costs = [Decimal(str(read_json(p)["cost_usd"])) for p in records]
    if not costs or any(not c.is_finite() or c < 0 for c in costs):
        raise ComparisonError("Historical usage is absent or malformed")
    total = sum(costs, Decimal(0))
    aggregate = read_json(root / "models/all-usage.json")
    recorded = Decimal(str(aggregate["total"]["cost"]))
    if abs(total - recorded) > Decimal("0.000000001"):
        raise ComparisonError("Historical execution costs disagree with aggregate")
    if total < Decimal("0.3568868") - Decimal("0.000000001"):
        raise ComparisonError("Historical budget floor was lost")
    return max(total, Decimal("0.3568868"))


class BudgetJournal:
    """Mutable journal controller; append-only records own the durable state."""

    def __init__(self, options: Options, root: Path = AUDIT_ROOT) -> None:
        self.options = options
        self.root = root
        self.path = options.campaign / "ledger.jsonl"

    @contextmanager
    def locked(self) -> Iterator[None]:
        import fcntl

        self.root.mkdir(parents=True, exist_ok=True)
        self.options.campaign.mkdir(parents=True, exist_ok=True)
        with (self.root / ".budget.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ComparisonError("Another comparison executor owns the global budget lock") from exc
            registry = self.root / "campaigns.jsonl"
            registered = set(registry.read_text().splitlines()) if registry.exists() else set()
            campaign = str(self.options.campaign.resolve())
            if campaign not in registered:
                self.path.touch(exist_ok=True)
                append_line(registry, campaign)
            yield

    def states(self) -> dict[str, JournalEntry]:
        states: dict[str, JournalEntry] = {}
        registry = self.root / "campaigns.jsonl"
        paths = set(registry.read_text().splitlines()) if registry.exists() else set()
        paths.update(str(p.parent.resolve()) for p in self.root.rglob("ledger.jsonl"))
        for campaign in sorted(paths):
            path = Path(campaign) / "ledger.jsonl"
            if not path.exists():
                raise ComparisonError("Registered campaign ledger is missing")
            for line in path.read_text().splitlines():
                entry = JournalEntry.model_validate_json(line)
                previous = states.get(entry.run_id)
                if previous is None and entry.state != "reserved":
                    raise ComparisonError("Ledger settlement lacks its reservation")
                if previous is not None and (previous.state != "reserved" or entry.state == "reserved"):
                    raise ComparisonError("Duplicate or invalid ledger transition")
                states[entry.run_id] = entry
        return states

    def spent(self) -> Decimal:
        states = self.states()
        if any(e.state != "settled" for e in states.values()):
            raise ComparisonError("Unsettled or interrupted request blocks all paid calls")
        return historical_cost(EVIDENCE) + sum((e.amount_usd for e in states.values()), Decimal(0))

    def reserve(self, run_id: str, amount: Decimal) -> None:
        if run_id in self.states():
            raise ComparisonError("Previously issued request cannot be replayed")
        if self.spent() + amount + self.options.qa_reserve_usd > self.options.budget_total_usd:
            raise ComparisonError("Remaining cumulative budget cannot cover reservation and QA")
        self.record(JournalEntry(run_id=run_id, state="reserved", amount_usd=amount, at=now()))

    def record(self, entry: JournalEntry) -> None:
        append_line(self.path, entry.model_dump_json())


def source_hashes() -> dict[str, str]:
    paths = ["tools/luna_compare.py", "services/analysis_execution.py", "services/pricing.py",
             "services/model_registry.py", "services/models.py", "services/summary_contract.py",
             "services/llm/openai_client.py", "api/analysis_context.py", "api/analysis_routes.py",
             "api/figure_service.py", "services/document_context.py"]
    paths.extend(str(p.relative_to(BACKEND)) for p in sorted((BACKEND / "agents").glob("*.md")))
    return {name: sha256((BACKEND / name).read_bytes()).hexdigest() for name in paths}


class RequestSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    prompt: str | list[dict[str, JsonValue]]
    model: str
    system_instruction: str | None = None
    thinking_level: str | None = None
    previous_interaction_id: str | None = None
    response_schema: dict[str, JsonValue] | None = None
    strict_schema: bool = False
    lane: Literal["pipeline", "chat"] = "pipeline"
    store: bool = False
    max_output_tokens: int
    single_attempt: bool = True
    service_tier: Literal["default"] = "default"

    def count_kwargs(self) -> dict[str, JsonValue]:
        return self.model_dump(include={"model", "system_instruction", "thinking_level",
                                        "previous_interaction_id", "response_schema", "strict_schema"})

    def generation_kwargs(self) -> dict[str, JsonValue]:
        return self.model_dump(exclude={"prompt"})

    def fingerprint(self) -> str:
        return digest(self.model_dump(mode="json"))

    def audit_hashes(self) -> dict[str, str]:
        from services.llm.openai_client import _build_request
        wire = _build_request(self.prompt, **self.count_kwargs())
        return {
            "count_request_sha256": digest(wire),
            "input_sha256": digest(wire["input"]),
            "model_independent_input_sha256": digest({k: v for k, v in wire.items() if k != "model"}),
            "app_schema_sha256": digest(self.response_schema),
            "wire_schema_sha256": digest(wire.get("text")),
            "wire_system_sha256": digest(wire["instructions"]),
        }

    def template(self) -> str:
        data = self.model_dump(mode="json")
        if isinstance(self.prompt, list):
            data["prompt"] = "\n".join(str(part["text"]) for part in self.prompt if part.get("type") == "text")
        data["previous_interaction_id"] = None
        return digest(data)


class RequestGate:
    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.request: RequestSpec | None = None

    async def capture(self, prompt, **kwargs) -> None:
        self.request = RequestSpec.model_validate({"prompt": prompt, **kwargs,
            "max_output_tokens": self.cap, "single_attempt": True, "service_tier": "default"})
        raise Captured

    async def stream_capture(self, prompt, **kwargs) -> AsyncIterator[dict[str, JsonValue]]:
        await self.capture(prompt, **kwargs)
        yield {"type": "unreachable"}


class QAInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    paper: dict[str, JsonValue]
    figures: list[dict[str, JsonValue]]
    tables: list[dict[str, JsonValue]]
    directory: Path


def load_qa(options: Options, paper: Paper) -> QAInput:
    if options.qa_source_db is None or options.qa_paper_id is None or options.qa_paper_dir is None:
        raise ComparisonError("QA scopes require --qa-source-db, --qa-paper-id and --qa-paper-dir")
    with sqlite3.connect(f"file:{options.qa_source_db.resolve()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM papers WHERE id = ?", (options.qa_paper_id,)).fetchone()
        if row is None:
            raise ComparisonError("QA paper is absent")
        figures = [dict(r) for r in db.execute("SELECT * FROM figures WHERE paper_id = ? AND COALESCE(extraction_status, 'resolved') != 'rejected' ORDER BY id", (options.qa_paper_id,))]
        tables = [dict(r) for r in db.execute("SELECT * FROM tables WHERE paper_id = ? AND COALESCE(extraction_status, 'resolved') != 'rejected' ORDER BY id", (options.qa_paper_id,))]
    directory = options.qa_paper_dir.resolve()
    pdfs = list(directory.glob("*.pdf"))
    if not any(sha256(p.read_bytes()).hexdigest() == paper.pdf_sha256 for p in pdfs):
        raise ComparisonError("QA paper PDF differs from the comparison manifest")
    if not figures:
        raise ComparisonError("QA requires a genuine resolved figure")
    for figure in figures:
        path = Path(str(figure.get("file_path") or ""))
        path = path if path.is_absolute() else directory / path
        if not path.is_file():
            raise ComparisonError("QA figure file is unavailable; automatic extraction is prohibited")
        figure["file_path"] = str(path)
        figure["detailed_explanation"] = None
    return QAInput(paper=dict(row), figures=figures, tables=tables, directory=directory)


@contextmanager
def isolated_product(qa: QAInput | None) -> Iterator[None]:
    """Keep product SQL/cache writes and parser sidecars in a disposable scope."""
    from services import analysis_execution as execution
    from services import odl_parser

    with ExitStack() as stack, tempfile.TemporaryDirectory(prefix="sasoo-luna-") as temporary:
        stack.enter_context(patch.dict(os.environ, {"SASOO_APP_DATA_ROOT": temporary}))
        stack.enter_context(patch.object(execution, "_get_cached_phase_result", AsyncMock(return_value=None)))
        stack.enter_context(patch.object(execution, "_insert_analysis_result", AsyncMock(return_value=1)))
        stack.enter_context(patch.object(execution, "_ensure_recipe_evidence", AsyncMock()))
        stack.enter_context(patch.object(odl_parser, "_resolve_stage_engine", return_value="odl"))
        stack.enter_context(patch.object(odl_parser, "_run_convert_gemini", side_effect=ComparisonError("Automatic model parsing prohibited")))
        if qa is not None:
            from api import analysis_routes, figure_service
            from models import database

            directory = Path(temporary) / "paper"
            shutil.copytree(qa.directory, directory)
            stack.enter_context(patch.object(database, "DB_PATH", Path(temporary) / "sasoo.db"))
            for module in (execution, analysis_routes, figure_service):
                stack.enter_context(patch.object(module, "get_paper_dir", return_value=directory))
            stack.enter_context(patch.object(execution, "_get_visual_contract", AsyncMock(return_value=(
                {"visual_state": "ready", "visual_ready": True, "visual_error": None,
                 "artifacts_ready": True, "artifacts_error": None}, len(qa.figures), len(qa.tables)))))
            async def rows(sql, params):
                return qa.tables if "FROM tables" in sql else qa.figures
            async def row(sql, params):
                return qa.figures[0] if "FROM figures" in sql else qa.paper
            for module in (execution, figure_service):
                stack.enter_context(patch.object(module, "fetch_all", rows))
            for module in (analysis_routes, figure_service):
                stack.enter_context(patch.object(module, "fetch_one", row))
                stack.enter_context(patch.object(module, "active_provider", AsyncMock(return_value="openai")))
                stack.enter_context(patch.object(module, "get_latest_completed_phase_rows", AsyncMock(return_value={})))
            stack.enter_context(patch.object(figure_service, "execute_update", AsyncMock()))
            stack.enter_context(patch.object(figure_service, "ensure_text_artifacts_async", AsyncMock()))
            stack.enter_context(patch.object(figure_service, "ensure_paper_artifacts", AsyncMock(side_effect=ComparisonError("Automatic extraction prohibited"))))
            stack.enter_context(patch.object(analysis_routes, "_CHAT_MAX_ATTEMPTS", 1))
        yield


async def invoke_product(context, gate) -> JsonValue:
    from api.analysis_context import build_chain_system_instruction
    from services import analysis_execution as execution
    from services.agents import MdAgent, parse_agent_md
    from services.model_registry import ModelChoice, resolve
    from models.schemas import AnalysisStatus

    options, paper, model, stage, pdf, previous, qa = context
    agent_name = "cell" if paper.id.startswith("bio") else "photon" if paper.id == "theory" else "neural"
    agent = MdAgent(parse_agent_md((BACKEND / "agents" / f"{agent_name}.md").read_text()))
    system = build_chain_system_instruction(
        persona_prompt="" if stage == "deep_dive" else execution._build_persona_prompt(agent, stage),
        research_context="", focus=None, level_key=options.explanation_level)
    choice = lambda role, provider: ModelChoice(model, options.effort if role == "deep_dive" else resolve(role, "openai").effort)
    status = AnalysisStatus(paper_id=1, overall_status="running", phases=[])
    common = {"system_instruction": system, "provider": "openai", "openai_pdf_part": pdf,
              "previous_interaction_id": previous, "single_attempt": True,
              "max_output_tokens": options.max_output_tokens}
    with ExitStack() as stack:
        stack.enter_context(patch.object(execution, "_stage_choice", choice))
        stack.enter_context(patch.object(execution, "call_interaction", gate.capture))
        match stage:
            case "deep_dive":
                return await execution._run_deep_dive(1, "", [], status, **common)
            case "visual":
                return await execution._run_visual(1, "", "paper", status, **common)
            case "recipe":
                return await execution._run_recipe(1, "", status, **common)
            case "figure_explain":
                from api import figure_service
                stack.enter_context(patch.object(figure_service, "call_interaction", gate.capture))
                stack.enter_context(patch.object(figure_service, "resolve_model", choice))
                return (await figure_service.explain_figure_handler(int(qa.paper["id"]), int(qa.figures[0]["id"]))).model_dump()
            case "chat":
                from api import analysis_routes
                from starlette.requests import Request
                async def receive():
                    return {"type": "http.request", "body": b'{"message":"Explain the paper method and its limits.","history":[]}'}
                request = Request({"type": "http", "method": "POST", "path": "/chat", "headers": []}, receive)
                stack.enter_context(patch.object(analysis_routes, "stream_interaction", gate.stream_capture))
                stack.enter_context(patch.object(analysis_routes, "resolve_model", choice))
                response = await analysis_routes._chat_with_agent_impl(int(qa.paper["id"]), request)
                chunks = [chunk async for chunk in response.body_iterator]
                return {"sse": "".join(c.decode() if isinstance(c, bytes) else c for c in chunks)}
            case unknown:
                assert_never(unknown)


class LiveGate(RequestGate):
    """The sole paid boundary. Raw provider metadata is persisted before app parsing."""

    def __init__(self, plan, context, journal: BudgetJournal) -> None:
        super().__init__(context[0].max_output_tokens)
        self.plan = plan
        self.context = context
        self.journal = journal
        self.calls = 0
        self.raw: dict[str, JsonValue] | None = None
        self.error_type: str | None = None
        self.run_id = digest({"campaign": str(context[0].campaign.resolve()), "key": plan["key"]})

    async def prepare(self, prompt, kwargs) -> tuple[RequestSpec, Decimal, float]:
        from services.llm.openai_client import count_input_tokens
        self.calls += 1
        if self.calls != 1:
            raise ComparisonError("Product retry blocked before transmission")
        spec = RequestSpec.model_validate({"prompt": prompt, **kwargs, "max_output_tokens": self.cap,
                                          "single_attempt": True, "service_tier": "default"})
        if spec.template() != self.plan["template_sha256"]:
            raise ComparisonError("Product request differs from dry-run template")
        if spec.previous_interaction_id is None and spec.fingerprint() != self.plan["request_sha256"]:
            raise ComparisonError("Request differs from counted dry-run")
        count = await count_input_tokens(spec.prompt, **spec.count_kwargs())
        reserve = Decimal(str(reserve_cost_usd(spec.model, count, self.cap))) * self.context[0].price_multiplier
        if reserve > Decimal(str(self.plan["reserved_usd"])):
            raise ComparisonError("Actual counted request exceeds preflight allowance")
        self.request = spec
        write_once(self.context[0].campaign / f"{self.plan['key']}.request.json", {
            "request_sha256": spec.fingerprint(), **spec.audit_hashes(),
            "input_tokens": count, "reserved_usd": str(reserve), "previous_interaction_id": spec.previous_interaction_id})
        self.journal.reserve(self.run_id, reserve)
        self.started_at = now()
        return spec, reserve, time.monotonic()

    def finish(self, result, reservation: Decimal, started: float) -> None:
        from services.pricing import PRICING, calc_result_cost
        options, paper, model, stage, pdf, previous, qa = self.context
        raw = JSON_OBJECT.validate_python(result)
        self.raw = raw
        response_model = raw.get("response_model")
        known_usage = (type(raw.get("tokens_in")) is int and type(raw.get("tokens_out")) is int
                       and raw.get("usage_complete", True) is not False
                       and isinstance(response_model, str) and response_model in PRICING
                       and raw.get("service_tier") == "default")
        amount = reservation
        cost_status = "unsettled"
        if known_usage:
            try:
                amount = Decimal(str(calc_result_cost({**raw, "model": response_model}))) * options.price_multiplier
                cost_status = "upper_bound" if raw.get("tokens_cached") is None or raw.get("tokens_cache_write") is None else "reported_usage"
            except ValueError:
                known_usage = False
                self.error_type = "InvalidUsage"
        record = {"run_id": self.run_id, "paper_id": paper.id, "model": model, "stage": stage,
            "scope": options.scope, "repeat": options.repeat, "pdf_sha256": paper.pdf_sha256,
            "request_sha256": self.request.fingerprint(), **self.request.audit_hashes(),
            "system_sha256": digest(self.request.system_instruction), "effort": self.request.thinking_level,
            "max_output_tokens": self.cap, "sdk_version": version("openai"), "code_hashes": source_hashes(),
            "start": self.started_at, "end": now(), "seconds": time.monotonic() - started,
            "cost_usd": str(amount) if known_usage else None, "cost_status": cost_status,
            "reserved_usd": str(reservation), "raw_output": raw.get("text", ""), "response": raw,
            "error_type": self.error_type, "reservation_exceeded": amount > reservation}
        path = options.campaign / f"{self.plan['key']}.result.json"
        write_once(path, record)
        self.journal.record(JournalEntry(run_id=self.run_id, state="settled" if known_usage and amount <= reservation else "unsettled",
            amount_usd=amount, at=now(), record=str(path.resolve())))
        if not known_usage or amount > reservation:
            raise ComparisonError("Usage is unknown or exceeds its reservation; paid execution stopped")

    async def capture(self, prompt, **kwargs):
        from services.llm.openai_client import call_interaction
        spec, reservation, started = await self.prepare(prompt, kwargs)
        try:
            result = await call_interaction(spec.prompt, **spec.generation_kwargs())
        except BaseException as exc:  # noqa: BROAD_EXCEPT_OK -- Persist liability then re-raise at paid boundary.
            self.error_type = type(exc).__name__
            self.finish({"text": "", "response_status": "exception", "usage_complete": False}, reservation, started)
            raise
        self.finish(result, reservation, started)
        return result

    async def stream_capture(self, prompt, **kwargs):
        from services.llm.openai_client import stream_interaction
        spec, reservation, started = await self.prepare(prompt, kwargs)
        chunks = []
        terminal = None
        finalized = False
        try:
            kwargs = spec.generation_kwargs()
            kwargs.pop("response_schema")
            kwargs.pop("strict_schema")
            kwargs.pop("previous_interaction_id")
            async for event in stream_interaction(spec.prompt, **kwargs):
                if event["type"] == "token":
                    chunks.append(event["text"])
                if event["type"] == "done":
                    if finalized:
                        raise ComparisonError("Stream produced multiple terminal events")
                    terminal = event
                    try:
                        self.finish({**terminal, "text": "".join(chunks)}, reservation, started)
                    finally:
                        finalized = True
                yield event
        except BaseException as exc:  # noqa: BROAD_EXCEPT_OK -- Preserve failed stream liability.
            if not finalized:
                self.error_type = type(exc).__name__
                self.finish({"text": "".join(chunks), "response_status": "exception", "usage_complete": False}, reservation, started)
            raise
        if not finalized:
            self.finish({"text": "".join(chunks), "response_status": "missing_completion"}, reservation, started)


def selected_papers(options: Options) -> list[Paper]:
    manifest = read_json(EVIDENCE / "papers/manifest.json")
    papers = {p.id: p for p in TypeAdapter(list[Paper]).validate_python(manifest["papers"])}
    if not options.papers or len(set(options.papers)) != len(options.papers) or set(options.papers) - set(papers):
        raise ComparisonError("Unknown or duplicate papers")
    if not options.models or len(set(options.models)) != len(options.models) or set(options.models) - set(MODELS):
        raise ComparisonError("Unknown or duplicate models")
    selected = [papers[key] for key in options.papers]
    for paper in selected:
        if sha256(paper.pdf_path.read_bytes()).hexdigest() != paper.pdf_sha256:
            raise ComparisonError("PDF hash mismatch")
    if options.scope != "deep-dive" and len(selected) != 1:
        raise ComparisonError("QA scopes require exactly one paper")
    return selected


def configuration(options: Options) -> dict[str, JsonValue]:
    return {"options": options.model_dump(mode="json", exclude={"mode", "run_paid_approved_usd_1"}),
            "code_hashes": source_hashes(), "sdk_version": version("openai")}


async def campaign(options: Options, journal: BudgetJournal) -> None:
    from services.llm.openai_client import count_input_tokens, load_pdf_part

    papers = selected_papers(options)
    config = configuration(options)
    path = options.campaign / "dry-run.json"
    stages = {"deep-dive": ("deep_dive",), "core-chain": ("visual", "recipe", "deep_dive"),
              "role-smoke": ("figure_explain", "chat")}[options.scope]
    live = options.mode == "run"
    saved = read_json(path) if path.exists() else None
    if saved is not None and saved["configuration"] != config:
        raise ComparisonError("Resume configuration, PDF sources or code hashes changed")
    if live and (not options.run_paid_approved_usd_1 or saved is None):
        raise ComparisonError("Run requires explicit paid flag and matching dry-run")
    if live and options.scope == "deep-dive" and options.qa_reserve_usd <= 0:
        raise ComparisonError("Primary generation requires an explicit bounded QA reserve")
    if saved is not None and not live:
        print(json.dumps({"status": "existing_dry_run", "path": str(path)}))
        return
    if live:
        states = journal.states()
        remaining = sum((Decimal(str(r["reserved_usd"])) for r in saved["requests"]
            if digest({"campaign": str(options.campaign.resolve()), "key": r["key"]}) not in states), Decimal(0))
        if journal.spent() + remaining + options.qa_reserve_usd > options.budget_total_usd:
            raise ComparisonError("Entire remaining cohort and QA exceed cumulative budget")
    plans = []
    for index, paper in enumerate(papers):
        pdf = load_pdf_part(paper.pdf_path)
        qa = load_qa(options, paper) if options.scope != "deep-dive" else None
        ordered_models = options.models if (index + options.repeat) % 2 == 0 else tuple(reversed(options.models))
        for model in ordered_models:
            previous = None
            cumulative_inputs = 0
            with isolated_product(qa):
                for stage_index, stage in enumerate(stages):
                    key = f"{paper.id}-{model}-{stage}-r{options.repeat}"
                    context = (options, paper, model, stage, pdf, previous, qa)
                    if live:
                        plan = next(r for r in saved["requests"] if r["key"] == key)
                        run_id = digest({"campaign": str(options.campaign.resolve()), "key": key})
                        existing = journal.states().get(run_id)
                        if existing is not None:
                            if existing.state != "settled":
                                raise ComparisonError("Issued request is not settled")
                            record = read_json(Path(existing.record))
                            if options.scope != "deep-dive":
                                validation_path = options.campaign / f"{key}.validation.json"
                                if not validation_path.exists() or read_json(validation_path)["product_valid"] is not True:
                                    raise ComparisonError("QA dependency was not validated; cannot resume dependents")
                            previous = record["response"].get("interaction_id")
                            continue
                        gate = LiveGate(plan, context, journal)
                        try:
                            result = await invoke_product(context, gate)
                        except BaseException as exc:  # noqa: BROAD_EXCEPT_OK -- Preserve product failure evidence, then re-raise.
                            if gate.raw is not None:
                                write_once(options.campaign / f"{key}.validation.json", {
                                    "product_valid": False, "product_result": None, "error_type": type(exc).__name__})
                            raise
                        valid = gate.raw is not None and not gate.raw.get("incomplete") and gate.raw.get("response_status") == "completed"
                        if isinstance(result, dict) and "text" in result:
                            from services.analysis_execution import _is_error_result
                            valid = valid and not _is_error_result(result["text"])
                        write_once(options.campaign / f"{key}.validation.json", {"product_valid": valid, "product_result": result})
                        if not valid and options.scope != "deep-dive":
                            raise ComparisonError("Product output is incomplete or malformed")
                        previous = gate.raw.get("interaction_id")
                        if options.scope == "core-chain" and stage_index < len(stages) - 1 and not previous:
                            raise ComparisonError("Core-chain response ID is absent")
                    else:
                        gate = RequestGate(options.max_output_tokens)
                        try:
                            await invoke_product(context, gate)
                        except Captured:
                            if gate.request is None:
                                raise ComparisonError("Capture interrupted before request validation") from None
                        if gate.request is None:
                            raise ComparisonError("Product did not issue its required model request")
                        request = gate.request
                        count = await count_input_tokens(request.prompt, **request.count_kwargs())
                        cumulative_inputs += count
                        bound = count if options.scope != "core-chain" else cumulative_inputs + stage_index * options.max_output_tokens
                        reserve = Decimal(str(reserve_cost_usd(model, bound, options.max_output_tokens))) * options.price_multiplier
                        plans.append({"key": key, "paper_id": paper.id, "model": model, "stage": stage,
                            "pdf_sha256": paper.pdf_sha256, "request_sha256": request.fingerprint(),
                            "template_sha256": request.template(), **request.audit_hashes(),
                            "input_tokens": count, "input_upper_bound": bound, "reserved_usd": str(reserve),
                            "dynamic_followup": options.scope == "core-chain" and stage_index > 0})
    if not live:
        total = sum((Decimal(p["reserved_usd"]) for p in plans), Decimal(0))
        write_once(path, {"configuration": config, "requests": plans, "reserved_usd": str(total),
            "historical_usd": str(historical_cost(EVIDENCE)), "qa_reserved_usd": str(options.qa_reserve_usd),
            "count_api_calls": len(plans), "generation_api_calls": 0,
            "dynamic_count_policy": "Core-chain follow-ups are counted exactly after response IDs exist; preflight sums independently counted stage inputs plus preceding output caps."})
        print(json.dumps({"status": "dry_run_counted", "reserved_usd": str(total), "qa_reserved_usd": str(options.qa_reserve_usd)}))


def offline_export(options: Options) -> None:
    records = [read_json(p) for p in sorted(options.campaign.glob("*.result.json"))]
    if options.mode == "review-pack":
        random.SystemRandom().shuffle(records)
        destination = options.campaign / "review-pack"
        destination.mkdir(exist_ok=False)
        mapping = {}
        for index, record in enumerate(records):
            label = f"response-{index + 1:03}"
            mapping[label] = {"run_id": record["run_id"], "model": record["model"], "repeat": record["repeat"]}
            write_once(destination / f"{label}.json", {"paper_id": record["paper_id"], "raw_output": record["raw_output"]})
        private = options.campaign / "review-key.private.json"
        with open(private, "x", encoding="utf-8", opener=lambda p, flags: os.open(p, flags, 0o600)) as handle:
            json.dump(mapping, handle, ensure_ascii=False, indent=2)
        return
    fields = ["paper_id", "model", "repeat", "stage", "scope", "product_valid", "error_type", "cost_status", "cost_usd", "seconds",
              "tokens_in", "tokens_out", "tokens_cached", "tokens_cache_write", "tokens_thought", "response_model", "response_status", "incomplete_reason", "service_tier"]
    destination = options.campaign / "reports" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination.mkdir(parents=True)
    with (destination / "usage.csv").open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fields)
        writer.writeheader()
        for record in records:
            merged = {**record, **record["response"]}
            validation = options.campaign / f"{record['paper_id']}-{record['model']}-{record['stage']}-r{record['repeat']}.validation.json"
            checked = read_json(validation) if validation.exists() else {}
            merged["product_valid"] = checked.get("product_valid", "unverified")
            merged["error_type"] = checked.get("error_type") or merged.get("error_type")
            writer.writerow({key: merged.get(key) for key in fields})
    lines = ["# Comparison execution records", "", "Scientific accuracy is not inferred from schema success.", "", "| Paper | Model | Repeat | Stage | Cost status | USD | Seconds |", "|---|---|---:|---|---|---:|---:|"]
    lines.extend(f"| {r['paper_id']} | {r['model']} | {r['repeat']} | {r['stage']} | {r['cost_status']} | {r['cost_usd']} | {r['seconds']:.3f} |" for r in records)
    (destination / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> Options:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dry-run", "run", "review-pack", "report"), default="dry-run")
    parser.add_argument("--scope", choices=("deep-dive", "core-chain", "role-smoke"), default="deep-dive")
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--papers", default=",".join(PAPERS))
    parser.add_argument("--models", default=",".join(MODELS))
    parser.add_argument("--input-mode", default="pdf")
    parser.add_argument("--effort", default="high")
    parser.add_argument("--explanation-level", default="undergrad")
    parser.add_argument("--max-output-tokens", type=int, default=16_000)
    parser.add_argument("--budget-total-usd", type=Decimal, default=Decimal("1"))
    parser.add_argument("--qa-reserve-usd", type=Decimal, default=Decimal("0"))
    parser.add_argument("--price-multiplier", type=Decimal, default=Decimal("1"))
    parser.add_argument("--run-paid-approved-usd-1", action="store_true")
    parser.add_argument("--qa-source-db", type=Path)
    parser.add_argument("--qa-paper-id", type=int)
    parser.add_argument("--qa-paper-dir", type=Path)
    parser.add_argument("--repeat", type=int, default=0)
    data = vars(parser.parse_args(argv))
    data["papers"] = tuple(data["papers"].split(","))
    data["models"] = tuple(data["models"].split(","))
    data["campaign"] = data["campaign"].resolve()
    return Options.model_validate(data)


def main() -> None:
    options = parse_args()
    if options.mode in ("review-pack", "report"):
        offline_export(options)
        return
    journal = BudgetJournal(options)
    with journal.locked():
        anyio.run(campaign, options, journal)


if __name__ == "__main__":
    main()
