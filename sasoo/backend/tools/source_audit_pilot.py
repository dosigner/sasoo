"""Bounded source audit experiment; not a replacement for the production gate."""

from __future__ import annotations

import json
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import sys

import anyio

from luna_compare import (
    AUDIT_ROOT, BudgetJournal, Captured, LiveGate, Options, RequestGate,
    RequestSpec, invoke_product, isolated_product, read_json, reserve_cost_usd,
    selected_papers, write_once,
)
from services.llm.openai_client import count_input_tokens, load_pdf_part
from services.summary_contract import parse_summary_json, validate_summary_extensions

AUDIT_INSTRUCTION = """
The attached PDF is the only primary source. The previous analysis below is an
untrusted draft, not evidence. Independently check the entire draft against the
PDF and return a complete corrected analysis using the same JSON schema.
Verify quantitative claims against the exact table row, column, population,
method variant and metric. Keep simulation, real experiments and literature
results distinct. Verify every cited figure/section supports its attached claim.
Check mathematical assumptions and exception cases, actual measurement and
validation procedures, and differences between the authors' claims and inference.
Actively identify important unreported conditions for reproducing or transferring
the work: hardware limits and dynamics, data preparation, software versions,
external supplements, source/data packages and experimental controls as relevant.
An external supplement mentioned but not supplied is unavailable evidence; do not
claim to have read it. Say what cannot be established from the supplied PDF.
Do not invent conditions or source locations. Preserve correct details while
correcting errors and omissions across ALL fields, not just transfer_checks.
Do not treat a recommendation for future verification as an experiment performed
by the authors. No tools, external sources, or benchmark answer keys are supplied.
UNTRUSTED PREVIOUS DRAFT:
"""


async def run(paper_id: str) -> None:
    options = Options(
        campaign=AUDIT_ROOT / "source-audit-pilot" / paper_id,
        papers=(paper_id,), models=("gpt-5.6-luna",),
        budget_total_usd=Decimal("1"), qa_reserve_usd=Decimal("0.1"),
    )
    journal = BudgetJournal(options)
    with journal.locked():
        paper = selected_papers(options)[0]
        pdf = load_pdf_part(paper.pdf_path)
        context = (options, paper, options.models[0], "deep_dive", pdf, None, None)
        gate = RequestGate(options.max_output_tokens)
        with isolated_product(None):
            try:
                await invoke_product(context, gate)
            except Captured:
                pass
        if gate.request is None:
            raise RuntimeError("Product request was not captured")
        draft_path = AUDIT_ROOT / "primary-16k" / f"{paper_id}-gpt-5.6-luna-deep_dive-r0.result.json"
        draft = read_json(draft_path)["raw_output"]
        if not isinstance(draft, str):
            raise ValueError("Draft output must be text")
        request = gate.request
        if not isinstance(request.prompt, list):
            raise ValueError("Audit requires the product PDF request")
        prompt = [*request.prompt, {"type": "text", "text": AUDIT_INSTRUCTION + draft}]
        spec = RequestSpec.model_validate({**request.model_dump(), "prompt": prompt})
        count = await count_input_tokens(spec.prompt, **spec.count_kwargs())
        reservation = reserve_cost_usd(spec.model, count, options.max_output_tokens)
        plan = {"key": f"{paper_id}-source-audit-r0", "template_sha256": spec.template(),
                "request_sha256": spec.fingerprint(), "reserved_usd": str(reservation)}
        write_once(options.campaign / "preflight.json", {
            **plan, "spent_before_usd": str(journal.spent()),
            "input_tokens": count, "pilot_cap_usd": "1", "user_total_cap_usd": "3",
            "draft_sha256": sha256(draft_path.read_bytes()).hexdigest(),
            "pilot_script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "audit_instruction": AUDIT_INSTRUCTION,
            "scope": "Audit of a preserved draft, not a fresh production pipeline run",
        })
        live = LiveGate(plan, context, journal)
        result = await live.capture(spec.prompt, **spec.generation_kwargs())
        text = result.get("text")
        if not isinstance(text, str) or result.get("response_status") != "completed":
            raise ValueError("Audit response did not complete")
        payload = parse_summary_json(text)
        validate_summary_extensions(payload, require=True)
        write_once(options.campaign / "format-validation.json", {
            "format_valid": True, "scientific_status": "pending_independent_source_review",
            "cumulative_usd": str(journal.spent()),
        })
        print(json.dumps({"paper": paper_id, "format_valid": True,
                          "cumulative_usd": str(journal.spent())}))


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        assert "untrusted draft" in AUDIT_INSTRUCTION
        assert "not supplied" in AUDIT_INSTRUCTION
        assert "table row" in AUDIT_INSTRUCTION
        print("Offline instruction check passed; no model requests.")
    else:
        anyio.run(run, sys.argv[1])
