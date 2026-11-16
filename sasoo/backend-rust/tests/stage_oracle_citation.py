"""Run the shipped Python citation stage (`_run_citation`) with canned provider responses and record
the wire requests and the analysis_results row each stage would store.

No network and no DB writes: both SDK transports are intercepted, and the DB
helpers the stages call are replaced by recorders.

Usage: backend/.venv/bin/python -I tests/stage_oracle_citation.py <backend_dir> <out_json>
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




# Synthetic inputs only (papers are copyrighted). `sections` stands in for the
# document_context output; `_run_citation` receives these strings directly.
NUM_SECTIONS = {
    "introduction": "Free-space optical links suffer from turbulence [1]. Prior surveys cover this topic well [2, 3]. "
                    "Early work used fast tip-tilt mirrors [4]. Background on scintillation is in [10].",
    "methods": "We follow the wavefront sensing approach of [5] with a modal basis [6–8]. "
               "The deformable mirror model follows [5]. Calibration uses the method in [1]. "
               "Noise handling extends [12-14] and [0].",
    "results": "Our Strehl ratio exceeds the baseline of [6] by 20 percent. Compared with [9], latency is halved [5]. "
               "Short [2]. (Table 2) lists the numbers in [11].",
    "full_text": "ignored full text",
    "references": "ignored references",
}
NUM_BODY = "\n\n".join(v for k, v in NUM_SECTIONS.items() if k not in ("full_text", "references"))
NUM_REFS = (
    "[1] A. Smith, B. Jones, and C. Lee, “Turbulence in free-space links,” Opt. Express 12, 1-10 (2004).\n"
    "[2] Kim, J. et al. Adaptive optics review for communication systems. Nature Photonics 5, 100 (2011).\n"
    "[3] Wong A, Lee B. Survey of atmospheric channel models and statistics, IEEE Commun. Surv. 2015.\n"
    "[4] R. Tyson, Principles of Adaptive Optics, 3rd edition, CRC Press, 2010.\n"
    "[5] Dongju Kim and Hana Park, \"Modal wavefront sensing with neural networks\", Optica 7, 2020.\n"
    "[6] Lee, C., Smith, A., Zhou, Q., Deformable mirror control at kilohertz rates. Appl. Opt. 45 (2006)\n"
    "[7] ???\n"
    "[8] Doe J (2019) A study without any journal name at all\n"
    "[9]   Brown K. et al.   Latency budgets    in adaptive optics loops. J. Opt. Soc. Am. A 30, 2013.\n"
    "[10] Introduction to scintillation, lecture notes 1999.\n"
    "[11] Garcia M, Wavefront statistics for strong turbulence regimes. Phys. Rev A 88, 2019\n"
    "[12] Chen L., Noise models. 2001.\n[13] Patel R. & Singh V. 2003. Photon noise limits in sensors.\n"
    "[14] Muller H. Ann. Phys. 2008."
)
NUM_AUTHORS = "Dongju Kim, Alice Wong; Bob Lee & C. Smith"

# Only cited in introduction: background filter leaves nothing -> local_only.
BG_SECTIONS = {
    "introduction": "Optical turbulence is a well known problem [1]. It was studied for decades [2, 3]. Many surveys exist [1].",
    "methods": "We describe a new sensor without prior art references here. It is a fully original design.",
}
BG_BODY = "\n\n".join(BG_SECTIONS.values())
BG_REFS = ("[1] A. Smith, Turbulence basics in optical links, Opt. Express 1, 2001.\n"
           "[2] B. Jones and C. Lee, History of atmospheric optics, Appl. Opt. 2, 1990.\n"
           "[3] Survey of turbulence. Nature 3, 1995.")

# Superscript style (few brackets) with "1." numbering and messy lines.
SUP_SECTIONS = {
    "introduction": "Turbulence degrades coherent links strongly1,2. Adaptive optics corrects this3–5 in practice.",
    "results": "Table1 shows the setup. Channel reciprocity23 is not exploited here. "
               "The exponent version1.2 is unchanged. Our interval4. Prior bound w0 holds and Fig2 too.",
}
SUP_BODY = "\n\n".join(SUP_SECTIONS.values())
SUP_REFS = ("1. Smith A, Jones B. Coherent links under turbulence. Nat. Photon. 4, 2010.\n"
            "2. Lee C. et al., Strong turbulence channel measurements in urban links, Opt. Lett. 2012.\n"
            "  3.   Kim D & Park H. Adaptive optics for coherent receivers. 2015\n"
            "4. “A quoted title only” 2016.\n"
            "5. x\n")

# Author-year style, unnumbered entries split by blank lines, no sections.
AY_BODY = ("Deep optics was introduced recently (Smith et al., 2020). Cosmos models extend it (Agarwal et al., 2021). "
           "Rendering was studied (Wang, 2018). Smith also showed this in 2020 with a lens. Agarwal improved it further. "
           "Muller and others worked on 1999 data.")
AY_REFS = ("Smith, J., Brown, K., 2020. Deep optics for computational imaging systems. Nature 580, 1-5.\n\n"
           "Niket Agarwal, Arslan Ali, et al. (2021). Cosmos world foundation models for robots. arXiv preprint.\n\n"
           "short\n\n"
           "Wang et al. 2018, Neural rendering of complex optical scenes, IEEE Trans. Vis. 3.\n\n"
           "Müller, H. and Schmidt, K. Old data analysis in optics, 1999.")


def cite_ok(**overrides):
    payload = {
        "ref_analyses": [
            {"ref_id": "[5]", "citation_role": "methodological", "evidence_context": "We follow the wavefront sensing approach of [5]",
             "why_cited": "방법의 기반이다."},
            {"ref_id": "ref 6", "citation_role": "comparative", "why_cited": "비교 기준이다."},
            {"ref_id": "#1", "citation_role": "foundational", "evidence_context": "(제목 근거)", "why_cited": "문제 정의."},
            {"ref_id": "[52] Zhiqi Li et al. (2025)", "citation_role": "unclear", "why_cited": "목록에 없음."},
            {"ref_id": "(9)", "citation_role": "contrasting", "why_cited": "지연 비교."},
            {"ref_id": "[5]", "citation_role": "supporting", "why_cited": "중복 항목."},
        ],
        "summary": "방법 문헌에 크게 기댄다.",
        "citation_balance": "heavily_reliant",
        "key_influences": ["[5]", "[6]"],
        "limitations": "상위 7개만 봤다.",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


CITE_OK = cite_ok()
CITE_MIN = json.dumps({"ref_analyses": [{"ref_id": "1", "citation_role": "supporting", "why_cited": "x"}],
                       "summary": "짧은 평가.", "citation_balance": "balanced"}, ensure_ascii=False)
CITE_TRUNC = CITE_OK[:180]


def citation_cases():
    out = []
    inputs = {
        "numbered": (NUM_SECTIONS, NUM_BODY, NUM_REFS, NUM_AUTHORS),
        "superscript": (SUP_SECTIONS, SUP_BODY, SUP_REFS, "A. Smith"),
        "author_year": ({}, AY_BODY, AY_REFS, "Jane Smith and K. Brown"),
    }
    local = [
        ("background_only", (BG_SECTIONS, BG_BODY, BG_REFS, "")),
        ("no_references", (NUM_SECTIONS, NUM_BODY, "", NUM_AUTHORS)),
        ("unparsable_references", ({}, "Body text without any citations at all.", "a\nb\n", "")),
    ]
    for provider, body in (("gemini", gemini_body), ("openai", openai_body)):
        cases = [
            ("numbered_ok", "numbered", [body(CITE_OK)]),
            ("numbered_fenced", "numbered", [body("```json\n" + CITE_OK + "\n```")]),
            ("superscript_ok", "superscript", [body(CITE_MIN)]),
            ("author_year_ok", "author_year", [body(CITE_MIN)]),
            ("invalid_json", "numbered", [body("not json")]),
            ("truncated_json", "numbered", [body(CITE_TRUNC)]),
            ("extra_data", "numbered", [body(CITE_MIN + " trailing")]),
            ("schema_bad_enum", "numbered", [body(cite_ok(citation_balance="lopsided"))]),
            ("schema_missing_summary", "numbered", [body(json.dumps({"ref_analyses": [], "citation_balance": "diverse"}))]),
            ("blank_summary", "numbered", [body(cite_ok(summary="  \n"))]),
            ("not_object", "numbered", [body("[1, 2]")]),
            ("incomplete", "numbered", [body(CITE_OK, status="incomplete")]),
            ("usage_missing", "numbered", [body(CITE_OK, usage=False)]),
        ]
        for name, kind, responses in cases:
            sections, cbody, refs, authors = inputs[kind]
            out.append({"name": f"citation_{provider}_{name}", "provider": provider, "responses": responses,
                        "sections": sections, "citation_body": cbody, "citation_references": refs,
                        "paper_authors": authors})
        for name, (sections, cbody, refs, authors) in local:
            out.append({"name": f"citation_{provider}_{name}", "provider": provider, "responses": [],
                        "sections": sections, "citation_body": cbody, "citation_references": refs,
                        "paper_authors": authors})
    return out


async def run_citation_case(ae, models, case) -> dict:
    from services.model_registry import resolve
    rows: list[dict] = []

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
    seen.clear()
    queue[:] = [{"status": 200, "body": b} for b in case["responses"]]
    status = models.AnalysisStatus(paper_id=1)
    error = None
    try:
        await ae._run_citation(1, case["sections"], case["citation_body"], case["citation_references"],
                               case["paper_authors"], status, provider=case["provider"])
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    choice = resolve("citation", case["provider"])
    return {**case, "choice": {"model": choice.model, "effort": choice.effort},
            "requests": list(seen), "unused_responses": len(queue), "rows": rows, "error": error}


JSON_PROBES = ["", "not json", "{", '{"a"', '{"a":', '{"a": 1', '{"a": 1,', '{"a": 1,}', "[1,", "[1,]", "[1 2]",
               '{"a" 1}', "{1:2}", '"abc', '"a\\x"', '"a\\u12"', '"a\\u12zz"', '"a\nb"', "[1] x", '{"a": [1, {"b": tru}]}',
               "-", "1.", "1e", "1e+", "-x", "NaN x", '\n\n  {"a": nul}', '{"a":1}\n\nx', '["\\', '{"a": "b\\',
               '"\\ud800\\uzzzz"', "\ufeff{}", "  [true, false, null, -0.5e-3, 12]  ", '{"k": "\u20ac"}', "[1, 2]", CITE_TRUNC]

# Extra analyzer-only inputs: (references, body, sections, authors).
ANALYZER_INPUTS = [
    (NUM_REFS, NUM_BODY, NUM_SECTIONS, NUM_AUTHORS),
    (SUP_REFS, SUP_BODY, SUP_SECTIONS, "A. Smith"),
    (AY_REFS, AY_BODY, {}, "Jane Smith and K. Brown"),
    # Body markers [85] inside the reference text: the "1." branch must win on duplicates.
    ("1. Alpha A. et al. First work on lasers. Laser Phys. 2001 see [2] and [2]\n2. Beta B., Gamma G., Second work here today, 2002 [3]\n"
     "3. Delta D. Third work [3] again. 2003\n4. Eps E. Fourth. Proc. SPIE 4, 2004 [1]",
     "Lasers matter [1]. Second [2]. Third [3]. Fourth [4]. More [1, 4]. Range [2-3].", {"methods": "Lasers matter [1]."}, ""),
    ("[1] Only one\n[2] two", "Body [1] [2].", {}, "x"),
    ("[1]   ", "Body.", {}, ""),
    ("Line one is long enough here\nSecond line also long enough\nshort\nFourth reference line, 2020", "Plain body text here without cites. Another sentence follows here!",
     {"intro": "Plain body text"}, "Some One; Two & Three"),
    ("[1] A. B\u00e9la, \u201cUnicode title quoted,\u201d Phys. Rev. Lett. 1, 1999.\n[2] O'Brien, P. and D'Arcy, Q. 2005. Title words go here. Science 2.\n[3] Smith J, Jones K. 2010",
     "Text (O'Brien et al., 2005) and (Smith, 2010). Also (B\u00e9la, 1999). [1]", {"a": "Text", "b": "Also"}, "P. O'Brien, J. Smith"),
]


async def main():
    backend, out_path = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    sys.path.insert(0, str(backend))
    from models import schemas as models
    from services import analysis_execution as ae
    from services.llm import gemini_client, openai_client
    gemini_client._RETRY_DELAYS = [0, 0]
    openai_client._RETRY_DELAYS = [0, 0]
    cases = [await run_citation_case(ae, models, c) for c in citation_cases()]
    json_errors = []
    for text in JSON_PROBES:
        try:
            json.loads(text)
            json_errors.append({"text": text, "error": None})
        except json.JSONDecodeError as exc:
            json_errors.append({"text": text, "error": str(exc)})
    from services.citation_analyzer import analyze_citations
    analyzer = [{"references": r, "body": b, "sections": sec, "authors": a,
                 "expected": analyze_citations(r, b, sec, a).to_dict()} for r, b, sec, a in ANALYZER_INPUTS]
    out_path.write_text(json.dumps({"generator": "tests/stage_oracle_citation.py", "citation": cases,
                                    "json_errors": json_errors, "analyzer": analyzer},
                                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


asyncio.run(main())
