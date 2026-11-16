"""Record what the shipped Python provider adapters put on the wire.

No network: both SDKs' httpx transports are replaced by a handler that serves
canned responses. Output is the fixture read by tests/provider_wire.rs.

Usage: backend/.venv/bin/python -I tests/provider_wire_oracle.py <backend_dir> <out_json>
"""
import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

os.environ["GEMINI_API_KEY"] = "fixture-gemini-key"
os.environ["OPENAI_API_KEY"] = "fixture-openai-key"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
time.sleep = lambda _s: None  # SDK-internal backoff; the recorded attempt count is what matters

import httpx  # noqa: E402

SECRET_HEADERS = {"authorization", "x-goog-api-key"}
KEPT_HEADERS = {"content-type", "x-goog-upload-protocol", "x-goog-upload-command",
                "x-goog-upload-offset", "x-goog-upload-header-content-type",
                "x-goog-upload-header-content-length", "x-goog-upload-file-name"}

seen: list[dict] = []
queue: list[dict] = []


def _record(request) -> dict:
    body = request.read()
    headers = {}
    for k, v in request.headers.items():
        k = k.lower()
        if k in SECRET_HEADERS:
            headers[k] = "<redacted>"
        elif k in KEPT_HEADERS:
            headers[k] = v
    entry = {"method": request.method, "url": str(request.url), "headers": headers}
    try:
        entry["body_json"] = json.loads(body) if body else None
    except (ValueError, UnicodeDecodeError):
        entry["body_base64"] = base64.b64encode(body).decode()
    seen.append(entry)
    if not queue:
        raise AssertionError(f"unexpected request {request.method} {request.url}")
    return queue.pop(0)


def _handler(self, request):
    r = _record(request)
    return httpx.Response(r["status"], content=r["body"].encode(), headers=r.get("headers", {"content-type": "application/json"}), request=request)


httpx.HTTPTransport.handle_request = _handler
try:
    import httpx2

    def _handler2(self, request):
        r = _record(request)
        return httpx2.Response(r["status"], content=r["body"].encode(), headers=r.get("headers", {"content-type": "application/json"}), request=request)

    httpx2.HTTPTransport.handle_request = _handler2
except ImportError:
    pass


def openai_body(**over) -> str:
    body = {
        "id": "resp_fixture", "object": "response", "created_at": 1, "status": "completed",
        "model": "gpt-fixture-2026", "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        "output": [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "{\"a\":1}", "annotations": []}]}],
        "usage": {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150,
                  "input_tokens_details": {"cached_tokens": 20},
                  "output_tokens_details": {"reasoning_tokens": 7}},
    }
    for k, v in over.items():
        if v is None:
            body.pop(k, None)
        else:
            body[k] = v
    return json.dumps(body, ensure_ascii=False)


def gemini_body(**over) -> str:
    body = {
        "id": "int_fixture", "status": "completed", "model": "gemini-fixture",
        "steps": [{"type": "model_output", "content": [{"type": "text", "text": "{\"a\":1}"}]}],
        "usage": {"total_input_tokens": 100, "total_output_tokens": 40, "total_thought_tokens": 9},
    }
    for k, v in over.items():
        if v is None:
            body.pop(k, None)
        else:
            body[k] = v
    return json.dumps(body, ensure_ascii=False)


SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}}
NESTED = {"type": "object", "properties": {
    "title": {"type": "string"},
    "items": {"type": "array", "items": {"type": "object", "properties": {"k": {"type": "string"}, "v": {"type": "number"}}}},
}}
ok = lambda body: [{"status": 200, "body": body}]  # noqa: E731

CASES = [
    # OpenAI Responses API
    {"name": "openai_text_schema", "spec": {"provider": "OpenAi", "model": "gpt-fixture", "parts": [{"text": "hello"}], "instructions": "sys", "schema": SCHEMA, "effort": "low", "store": False}, "responses": ok(openai_body())},
    {"name": "openai_strict_chain", "spec": {"provider": "OpenAi", "model": "gpt-fixture", "parts": [{"text": "이어서 분석해"}], "schema": NESTED, "strict_schema": True, "effort": "high", "store": True, "previous_id": "resp_prev", "max_output_tokens": 16000, "service_tier": "flex"}, "responses": ok(openai_body(service_tier="flex"))},
    {"name": "openai_pdf_parts_default_instructions", "spec": {"provider": "OpenAi", "model": "gpt-fixture", "parts": [{"pdf_inline": "tiny.pdf"}, {"text": "논문을 읽어"}], "store": True}, "responses": ok(openai_body())},
    {"name": "openai_incomplete", "spec": {"provider": "OpenAi", "model": "gpt-fixture", "parts": [{"text": "x"}], "store": False}, "responses": ok(openai_body(status="incomplete", incomplete_details={"reason": "max_output_tokens"}))},
    {"name": "openai_failed_status", "spec": {"provider": "OpenAi", "model": "gpt-fixture", "parts": [{"text": "x"}], "store": False}, "responses": ok(openai_body(status="failed", output=[]))},
    {"name": "openai_usage_missing", "spec": {"provider": "OpenAi", "model": "gpt-fixture", "parts": [{"text": "x"}], "store": False}, "responses": ok(openai_body(usage=None))},
    {"name": "openai_cache_write", "spec": {"provider": "OpenAi", "model": "gpt-fixture", "parts": [{"text": "x"}], "store": False}, "responses": ok(openai_body(usage={"input_tokens": 100, "output_tokens": 0, "total_tokens": 100, "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 64}, "output_tokens_details": {"reasoning_tokens": 0}}))},
    {"name": "openai_multi_message_text", "spec": {"provider": "OpenAi", "model": "gpt-fixture", "parts": [{"text": "x"}], "store": False}, "responses": ok(openai_body(output=[
        {"type": "reasoning", "id": "rs_1", "summary": []},
        {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": "앞", "annotations": []}, {"type": "output_text", "text": "뒤", "annotations": []}]},
        {"type": "message", "id": "msg_2", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": "끝", "annotations": []}]}]))},
    {"name": "openai_http_400", "spec": {"provider": "OpenAi", "model": "gpt-fixture", "parts": [{"text": "x"}], "store": False}, "responses": [{"status": 400, "body": json.dumps({"error": {"message": "bad", "type": "invalid_request_error"}})}]},
    {"name": "openai_http_429_then_ok", "spec": {"provider": "OpenAi", "model": "gpt-fixture", "parts": [{"text": "x"}], "store": False}, "responses": [{"status": 429, "body": json.dumps({"error": {"message": "slow down"}})}] + ok(openai_body())},
    {"name": "openai_http_429_always", "spec": {"provider": "OpenAi", "model": "gpt-fixture", "parts": [{"text": "x"}], "store": False}, "responses": [{"status": 429, "body": json.dumps({"error": {"message": "slow down"}})}] * 12},
    # Gemini Interactions API
    {"name": "gemini_text_schema", "spec": {"provider": "Gemini", "model": "gemini-fixture", "parts": [{"text": "hello"}], "instructions": "sys", "schema": SCHEMA, "effort": "low", "store": False}, "responses": ok(gemini_body())},
    {"name": "gemini_document_chain", "spec": {"provider": "Gemini", "model": "gemini-fixture", "parts": [{"pdf_uri": "https://generativelanguage.googleapis.com/v1beta/files/abc"}, {"text": "논문을 읽어"}], "store": True, "previous_id": "int_prev", "max_output_tokens": 24000, "effort": "medium"}, "responses": ok(gemini_body())},
    {"name": "gemini_reported_zero", "spec": {"provider": "Gemini", "model": "gemini-fixture", "parts": [{"text": "x"}], "store": False}, "responses": ok(gemini_body(usage={"total_input_tokens": 0, "total_output_tokens": 0, "total_thought_tokens": 0}))},
    {"name": "gemini_thought_missing", "spec": {"provider": "Gemini", "model": "gemini-fixture", "parts": [{"text": "x"}], "store": False}, "responses": ok(gemini_body(usage={"total_input_tokens": 10, "total_output_tokens": 4}))},
    {"name": "gemini_usage_missing", "spec": {"provider": "Gemini", "model": "gemini-fixture", "parts": [{"text": "x"}], "store": False}, "responses": ok(gemini_body(usage=None))},
    {"name": "gemini_incomplete", "spec": {"provider": "Gemini", "model": "gemini-fixture", "parts": [{"text": "x"}], "store": False}, "responses": ok(gemini_body(status="incomplete"))},
    {"name": "gemini_thought_and_multi_text", "spec": {"provider": "Gemini", "model": "gemini-fixture", "parts": [{"text": "x"}], "store": False}, "responses": ok(gemini_body(steps=[
        {"type": "model_output", "content": [{"type": "text", "text": "버려질 앞부분"}]},
        {"type": "thought", "signature": "c2ln", "summary": [{"type": "text", "text": "생각"}]},
        {"type": "model_output", "content": [{"type": "text", "text": "첫"}, {"type": "text", "text": "둘"}]},
        {"type": "model_output", "content": [{"type": "text", "text": "셋"}]}]))},
    {"name": "gemini_http_400_string_code", "spec": {"provider": "Gemini", "model": "gemini-fixture", "parts": [{"text": "x"}], "store": False}, "responses": [{"status": 400, "body": json.dumps({"error": {"code": "invalid_request", "message": "bad"}})}]},
    {"name": "gemini_http_503_then_ok", "spec": {"provider": "Gemini", "model": "gemini-fixture", "parts": [{"text": "x"}], "store": False}, "responses": [{"status": 503, "body": json.dumps({"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}})}] + ok(gemini_body())},
    {"name": "gemini_http_503_always", "spec": {"provider": "Gemini", "model": "gemini-fixture", "parts": [{"text": "x"}], "store": False}, "responses": [{"status": 503, "body": json.dumps({"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}})}] * 40},
]


def python_kwargs(spec: dict, fixture_dir: Path):
    prompt: object
    parts = []
    for p in spec["parts"]:
        if "text" in p:
            parts.append({"type": "text", "text": p["text"]})
        elif "pdf_inline" in p:
            from services.llm.openai_client import load_pdf_part
            parts.append(load_pdf_part(fixture_dir / p["pdf_inline"]))
        elif "pdf_uri" in p:
            parts.append({"type": "document", "uri": p["pdf_uri"], "mime_type": "application/pdf"})
    # Rust rule: a single text part is sent as a plain string, like the Python callers do.
    prompt = parts[0]["text"] if len(parts) == 1 and "text" in spec["parts"][0] else parts
    kw = {"lane": "pipeline", "model": spec["model"], "store": spec.get("store", True)}
    for src, dst in [("instructions", "system_instruction"), ("schema", "response_schema"),
                     ("effort", "thinking_level"), ("previous_id", "previous_interaction_id"),
                     ("max_output_tokens", "max_output_tokens")]:
        if spec.get(src) is not None:
            kw[dst] = spec[src]
    if spec["provider"] == "OpenAi":
        if spec.get("strict_schema"):
            kw["strict_schema"] = True
        if spec.get("service_tier"):
            kw["service_tier"] = spec["service_tier"]
    return prompt, kw


async def run_case(case: dict, fixture_dir: Path) -> dict:
    from services.llm import gemini_client, openai_client
    seen.clear()
    queue[:] = [dict(r) for r in case["responses"]]
    prompt, kw = python_kwargs(case["spec"], fixture_dir)
    module = openai_client if case["spec"]["provider"] == "OpenAi" else gemini_client
    out = dict(case)
    try:
        out["result"] = await module.call_interaction(prompt, **kw)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    out["requests"] = list(seen)
    out["unused_responses"] = len(queue)
    return out


async def run_upload(fixture_dir: Path) -> dict:
    """Gemini Files resumable upload of a Korean-named PDF (no DB write)."""
    from services.llm import gemini_client
    seen.clear()
    upload_url = "https://generativelanguage.googleapis.com/upload/v1beta/files?upload_id=fixture&upload_protocol=resumable"
    queue[:] = [
        {"status": 200, "body": "", "headers": {"x-goog-upload-url": upload_url, "x-goog-upload-status": "active"}},
        {"status": 200, "body": json.dumps({"file": {"name": "files/abc", "uri": "https://generativelanguage.googleapis.com/v1beta/files/abc", "mimeType": "application/pdf", "state": "ACTIVE"}}),
         "headers": {"content-type": "application/json", "x-goog-upload-status": "final"}},
    ]
    path = fixture_dir / "논문 사본.pdf"
    client = gemini_client._get_client()
    try:
        with open(path, "rb") as handle:
            uploaded = client.files.upload(file=handle, config={"mime_type": "application/pdf", "display_name": path.name})
        result = {"uri": uploaded.uri}
    except Exception as exc:  # noqa: BLE001
        result = {"error": f"{type(exc).__name__}: {exc}"}
    return {"name": "gemini_upload_korean_name", "file": path.name, "result": result, "requests": list(seen), "unused_responses": len(queue)}


async def main() -> None:
    backend, out_path = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    sys.path.insert(0, str(backend))
    from services.llm import gemini_client, openai_client
    openai_client._RETRY_DELAYS = [0, 0]
    gemini_client._RETRY_DELAYS = [0, 0]
    fixture_dir = out_path.parent
    pdf = b"%PDF-1.4\n% sasoo synthetic fixture\n%%EOF\n"
    (fixture_dir / "tiny.pdf").write_bytes(pdf)
    (fixture_dir / "논문 사본.pdf").write_bytes(pdf)
    cases = [await run_case(c, fixture_dir) for c in CASES]
    upload = await run_upload(fixture_dir)
    import google.genai
    import openai
    doc = {"generator": "tests/provider_wire_oracle.py", "sdk": {"openai": openai.__version__, "google-genai": google.genai.__version__},
           "cases": cases, "upload": upload}
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


asyncio.run(main())
