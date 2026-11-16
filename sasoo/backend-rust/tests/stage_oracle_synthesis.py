"""Run the shipped Python synthesis stage (through `_run_visualizations`, with the
visualization items stubbed) on canned provider responses, and record the wire
requests and the analysis_results rows. Also records the pure helpers
(`normalize_text`, `_numeric_tokens`, `_validate_synthesis`) on synthetic inputs.

No network and no DB writes. Scaffolding copied from tests/stage_oracle.py.

Usage: backend/.venv/bin/python -I tests/stage_oracle_synthesis.py <backend_dir> <out_json>
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

os.environ["GEMINI_API_KEY"] = "fixture-gemini-key"
os.environ["OPENAI_API_KEY"] = "fixture-openai-key"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
time.sleep = lambda _s: None

import httpx  # noqa: E402

KEPT = {"content-type"}
SECRET = {"authorization", "x-goog-api-key"}
seen: list[dict] = []
queue: list[dict] = []


def _record(request) -> dict:
    body = request.read()
    headers = {k.lower(): ("<redacted>" if k.lower() in SECRET else v)
               for k, v in request.headers.items() if k.lower() in KEPT | SECRET}
    seen.append({"method": request.method, "url": str(request.url), "headers": headers,
                 "body_json": json.loads(body) if body else None})
    if not queue:
        raise AssertionError("unexpected provider request")
    return queue.pop(0)


def _handler(self, request):
    r = _record(request)
    return httpx.Response(r["status"], content=r["body"].encode(), headers={"content-type": "application/json"}, request=request)


httpx.HTTPTransport.handle_request = _handler
try:
    import httpx2

    def _handler2(self, request):
        r = _record(request)
        return httpx2.Response(r["status"], content=r["body"].encode(), headers={"content-type": "application/json"}, request=request)

    httpx2.HTTPTransport.handle_request = _handler2
except ImportError:
    pass


def openai_body(text, *, status="completed", usage=True):
    body = {"id": "resp_stage", "object": "response", "created_at": 1, "status": status, "model": "gpt-6-luna",
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
            "output": [{"type": "message", "id": "m", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}]}
    if usage:
        body["usage"] = {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200,
                         "input_tokens_details": {"cached_tokens": 100, "cache_write_tokens": 0},
                         "output_tokens_details": {"reasoning_tokens": 50}}
    return json.dumps(body, ensure_ascii=False)


def gemini_body(text, *, status="completed", usage=True):
    body = {"id": "int_stage", "status": status, "model": "gemini",
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}]}
    if usage:
        body["usage"] = {"total_input_tokens": 1000, "total_output_tokens": 150, "total_thought_tokens": 50}
    return json.dumps(body, ensure_ascii=False)


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Synthetic inputs
# ---------------------------------------------------------------------------

BODY = ("We operate at 1550 nm and reach 97.5% coupling. The BER is 2 × 10−3 before coding and 1E-9 after. "
        "A shift of −5.2 dB appears. Power is 3,000 mW over 12 channels.")
SCREENING = dumps({"domain": "optics", "relevance_score": 0.9, "summary": "요약", "paper_type": "article"})
CITATION = dumps({"total_references": 42, "summary": "인용 요약"})
VISUAL = dumps({"figure_count": 3, "key_findings_from_visuals": ["Fig. 1: 수렴"]})
RECIPE = dumps({"title": "레시피", "parameters": [
    {"name": "wavelength", "value": "1550"}, {"name": "Laser Power", "value": "10"}, {"name": ""},
    "loose", {"name": "beam waist"}, {"name": 7}]})
DEEP = dumps({"problem_definition": "문제", "method_summary": "방법"})
FIGURES = [["Fig. 1", "Setup of the 🚀 optical bench. " + "x" * 250], ["Figure 2", None], ["3", "결과 그림"], ["", "no number"]]

METRIC_OK = {"label": "파장", "value": "1,550", "unit": "nm", "evidence": "We operate at 1550 nm"}
METRICS = [
    METRIC_OK,
    {"label": "결합", "value": "97.5", "unit": "%", "evidence": "reach 97.5% coupling"},
    {"label": "빈 단위", "value": "12", "unit": "  ", "evidence": "12 channels"},
    {"label": "값 불일치", "value": "42", "unit": "-", "evidence": "about 40 units"},
    {"label": "본문 없음", "value": "7.77", "unit": "dB", "evidence": "7.77 dB gain"},
    {"label": "지수", "value": "2×10^-3", "unit": "-", "evidence": "BER is 2 × 10−3"},
    "not a dict",
]
SYNTH = {
    "problem_sentence": " 난류 보정 문제 🚀 ✅ ",
    "method_sentence": "변형 거울 → 보정 ⭐",
    "key_metrics": METRICS,
    "equations": [
        {"latex": "a=b", "meaning": "뜻 😀", "symbols": [{"symbol": "a", "meaning": "x"}, "bad",
                                                    {"symbol": "b", "meaning": "y"}, {"symbol": "c", "meaning": "z"},
                                                    {"symbol": "d", "meaning": "w"}, {"symbol": "e", "meaning": "v"}],
         "paper_number": "1"},
        "skip me",
        {"latex": "c=d", "meaning": "둘", "paper_number": ""},
        {"latex": "e", "meaning": "m", "symbols": [], "paper_number": "3"},
        {"latex": "f", "meaning": "m", "symbols": "ab", "paper_number": "4"},
        {"latex": "g", "meaning": "m", "symbols": [], "paper_number": "5"},
        {"latex": "h", "meaning": "m", "symbols": [], "paper_number": "6"},
    ],
    "result_figures": [
        {"figure_num": "Fig. 1", "interpretation": "해석 1"},
        {"figure_num": "fig 2", "interpretation": "해석 2"},
        {"figure_num": "Figure 3", "interpretation": "해석 3"},
        {"figure_num": "9", "interpretation": "없음"},
        {"figure_num": "FIG.1", "interpretation": "중복"},
        {"figure_num": "Fig.2", "interpretation": "상한 초과"},
        "x",
    ],
    "key_parameters": [{"name": "Wave Length"}, {"name": "laserpower"}, {"name": "power"}, {"name": "7"},
                       {"name": "beam waist"}, {"name": "WAVELENGTH"}, {"name": "beam\twaist"}, 3],
    "equation_count": 7,
    "dropped": 99,
}


def synth(**over):
    base = json.loads(json.dumps(SYNTH))
    base.update(over)
    return dumps(base)


NUMERIC_STRINGS = [
    "1,550", "1550", "1,5500", "12,34", "97.5%", "50 %", "-5.2", "−5.2", "‒3", "1e-9", "1E-9", "1e5.3",
    "2 × 10^-3", "2x10-3", "2X10^3", "6.02·10^23", "3*10^2", "4 ⋅ 10 ^ 2", "2×1000", "×1000", "10⁻³", "10-3",
    "10 +5", "10-3.5", "fig.5", "version 10.5.3", "4.5. 다음 문장", ".5", "1,550.25 nm", "0.0", "-0", "0e5",
    "3,000,000", "3,000,00", "1e", "1e-", "10^", "１２３", "１０⁻⁹", "ﬁt 12", "x²", "10²", "a-\n  b 5",
    "5­0", "co-\r\n operate 7", "é 8", "1e400", "1E-400", "  lead and trail  ", "ß ẞ ς", "‘q’ “d”",
    "", "1.2.3", "007", "-007.500", "1,234,567.890e2", "−1,000", "a1b2", "3.14159, 2.71828",
]


def canon(d):
    t = d.as_tuple()
    digits = "".join(map(str, t.digits)).lstrip("0")
    exp = t.exponent
    if not digits:
        return [False, "0", 0]
    while digits.endswith("0"):
        digits = digits[:-1]
        exp += 1
    return [bool(t.sign), digits, exp]


VALIDATE_CASES = [
    {"name": "full", "data": json.loads(synth()), "doc": BODY, "figures": ["Fig. 1", "Figure 2", "3"],
     "params": ["wavelength", "Laser Power", "beam waist"]},
    {"name": "no_body", "data": json.loads(synth()), "doc": "", "figures": [], "params": []},
    {"name": "body_without_numbers", "data": json.loads(synth()), "doc": "no digits here", "figures": ["1"], "params": ["7"]},
    {"name": "string_and_dict_lists", "data": {"key_metrics": "ab", "result_figures": {"a": 1, "b": 2},
                                               "key_parameters": None, "equations": 0}, "doc": BODY, "figures": [], "params": []},
    {"name": "missing_lists", "data": {"problem_sentence": "x"}, "doc": BODY, "figures": [], "params": []},
    {"name": "metric_number_values", "data": {"key_metrics": [
        {"label": "a", "value": 1550, "unit": "nm", "evidence": "at 1550 nm"},
        {"label": "b", "value": "", "unit": "nm", "evidence": "no number"},
        {"label": "c", "value": "10-3", "unit": "-", "evidence": "range 10-3"},
        {"label": "d", "value": "1550", "unit": 0, "evidence": "1550"},
        {"label": "e", "value": "1.55e3", "unit": "nm", "evidence": "1550 nm"},
        {"label": "f", "value": "3000", "unit": "mW", "evidence": "3,000 mW"},
        {"label": "g", "value": "12", "unit": "ch", "evidence": "12 and 99"},
    ]}, "doc": BODY, "figures": [], "params": []},
    {"name": "type_error_metrics", "data": {"key_metrics": 5}, "doc": BODY, "figures": [], "params": []},
    {"name": "type_error_symbols", "data": {"equations": [{"latex": "a", "symbols": True}]}, "doc": "", "figures": [], "params": []},
    {"name": "type_error_float", "data": {"result_figures": 2.5}, "doc": "", "figures": [], "params": []},
]


# ---------------------------------------------------------------------------
# Stage cases
# ---------------------------------------------------------------------------

def stage_cases():
    out = []
    for provider, body in (("gemini", gemini_body), ("openai", openai_body)):
        source = ({"pdf_uri": "https://generativelanguage.googleapis.com/v1beta/files/abc", "pdf_sha256": "ab" * 32}
                  if provider == "gemini" else {"openai_pdf": "tiny.pdf"})
        base = {"provider": provider, "visualization_input": "Results summary: 1550 nm, BER 1e-9.", "source": source,
                "figures": FIGURES, "body_text": BODY, "system_instruction": "", "previous_id": None,
                "screening": SCREENING, "citation_text": CITATION, "visual_text": VISUAL, "recipe_text": RECIPE,
                "deep_text": DEEP}
        out += [
            {**base, "name": f"synth_{provider}_restart", "responses": [body(synth())]},
            {**base, "name": f"synth_{provider}_continue", "previous_id": "prev_deep", "system_instruction": "페르소나",
             "responses": [body("```json\n" + synth() + "\n```")]},
            {**base, "name": f"synth_{provider}_fallback", "source": {}, "responses": [body(synth())]},
            {**base, "name": f"synth_{provider}_no_figures_no_recipe", "figures": [], "recipe_text": "not json",
             "visual_text": '{"_raw": "x", "_parse_error": "y"}', "responses": [body(synth())]},
            {**base, "name": f"synth_{provider}_no_body", "body_text": "", "responses": [body(synth())]},
            {**base, "name": f"synth_{provider}_invalid_twice", "responses": [body("not json"), body("still {bad")]},
            {**base, "name": f"synth_{provider}_list_twice", "responses": [body("[1, 2]"), body("[1, 2]")]},
            {**base, "name": f"synth_{provider}_incomplete", "responses": [body(synth(), status="incomplete")]},
            {**base, "name": f"synth_{provider}_usage_missing", "responses": [body(synth(), usage=False)]},
            {**base, "name": f"synth_{provider}_type_error", "responses": [body(synth(key_metrics=5))]},
            {**base, "name": f"synth_{provider}_recipe_type_error", "recipe_text": '{"parameters": 7}', "responses": []},
            {**base, "name": f"synth_{provider}_http_400",
             "responses": [{"status": 400, "body": json.dumps({"error": {"code": 400, "message": "bad"}})}]},
        ]
    out.append({**out[0], "name": "synth_openai_doc_text", "provider": "openai", "source": {"doc_text": "본문 전문 " * 10},
                "responses": [openai_body(synth())]})
    return out


def install_recorders(ae, rows):
    async def fake_insert(paper_id, phase, result_text, model_used, tokens_in, tokens_out, cost_usd, input_text,
                          interaction_id=None, *, provider=None, model=None, effort=None):
        rows.append({"phase": phase, "result": result_text, "model_used": model_used, "tokens_in": tokens_in,
                     "tokens_out": tokens_out, "cost_usd": cost_usd,
                     "input_hash": ae.compute_input_hash(input_text, provider=provider, model=model, effort=effort),
                     "interaction_id": interaction_id, "config_hash": ae._config_hash(provider, model, effort)})
        return len(rows)

    async def no_cache(*_a, **_k):
        return None

    ae._insert_analysis_result = fake_insert
    ae._get_cached_phase_result = no_cache


async def run_stage_case(ae, models, case, fixture_dir) -> dict:
    from services.llm.openai_client import load_pdf_part
    from services.model_registry import resolve
    rows: list[dict] = []
    install_recorders(ae, rows)

    async def fake_fetch_all(_sql, _params):
        return [{"figure_num": n, "caption": c} for n, c in case["figures"]]

    async def no_items(*_a, **_k):
        return []

    ae.fetch_all = fake_fetch_all
    ae._run_visualization_items = no_items
    seen.clear()
    queue[:] = [r if isinstance(r, dict) else {"status": 200, "body": r} for r in case["responses"]]
    src = case["source"]
    previous = [t for t in (case["screening"], case["citation_text"], case["visual_text"], case["recipe_text"], case["deep_text"])
                if t and not ae._is_error_result(t)]
    kwargs = {"provider": case["provider"], "body_text": case["body_text"], "system_instruction": case["system_instruction"],
              "previous_interaction_id": case["previous_id"]}
    if "pdf_uri" in src:
        kwargs.update(pdf_uri=src["pdf_uri"], pdf_sha256=src["pdf_sha256"])
    if "openai_pdf" in src:
        kwargs["openai_pdf_part"] = load_pdf_part(fixture_dir / src["openai_pdf"])
    if "doc_text" in src:
        kwargs["doc_text"] = src["doc_text"]
    error = None
    try:
        await ae._run_visualizations(1, case["visualization_input"], "fixture", previous, case["recipe_text"],
                                     case["deep_text"], models.AnalysisStatus(paper_id=1), **kwargs)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    choice = resolve("synthesis", case["provider"])
    return {**case, "choice": {"model": choice.model, "effort": choice.effort},
            "requests": list(seen), "unused_responses": len(queue), "rows": rows, "error": error}


async def main():
    backend, out_path = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    sys.path.insert(0, str(backend))
    from models import schemas as models
    from services import analysis_execution as ae
    from services import evidence_verifier as ev
    from services.llm import gemini_client, openai_client
    gemini_client._RETRY_DELAYS = [0, 0]
    openai_client._RETRY_DELAYS = [0, 0]

    numeric = []
    for text in NUMERIC_STRINGS:
        norm = ev.normalize_text(text)
        numeric.append({"text": text, "normalized": norm,
                        "tokens": [canon(n) + [lit] for n, lit in ev._numeric_tokens(norm)]})
    validate = []
    for case in VALIDATE_CASES:
        try:
            out, dropped = ae._validate_synthesis(json.loads(json.dumps(case["data"])), case["doc"], case["figures"], case["params"])
            validate.append({**case, "out": dumps(out), "dropped": dropped, "error": None})
        except TypeError as exc:
            validate.append({**case, "out": None, "dropped": None, "error": str(exc)})
    helpers = {"norm_figure_num": {v: ae._norm_figure_num(v) for v in ["Fig. 3", "Figure 3", " 3 ", "FIG.3", "fig3", "figure.3", "Fig.Fig. 3", "Ｆｉｇ. 3"]},
               "strip_emoji": {v: ae._strip_emoji(v) for v in [" a 🚀 b ", "→ ∑ ✅", "1️⃣ 키캡", "⬛ 사각", "　x　"]},
               "recipe_param_names": {v: ae._recipe_param_names(v) for v in [RECIPE, "", "[1]", '{"parameters": "ab"}', '```json\n{"parameters": [{"name": 1.5}]}\n```']}}

    fixture_dir = out_path.parent.parent / "provider"
    stages = [await run_stage_case(ae, models, c, fixture_dir) for c in stage_cases()]
    out_path.write_text(json.dumps({"generator": "tests/stage_oracle_synthesis.py", "numeric": numeric, "validate": validate,
                                    "helpers": helpers, "synthesis": stages},
                                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


asyncio.run(main())
