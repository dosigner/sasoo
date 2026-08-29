"""OpenAI 페이지 비전 파싱 실측 스파이크 (`pdf_visual_engine` provider 중립화 사전 검증).

`gemini_parser`의 렌더·프롬프트·스키마를 그대로 재사용해 같은 페이지를 Gemini와 OpenAI로
각각 파싱하고 비교한다. Gemini 출력은 정답이 아니라 프로덕션 기준선(추출 정확도 12/12 lane이
통과한 경로)이므로 참조로만 쓴다. 판정 대상은 세 가지다.

1. 스키마 준수 — OpenAI가 markdown + elements(box_2d 4원소)를 규약대로 채우는가.
2. box_2d 공간 정합 — 0-1000 범위와 좌표 순서, 면적이 유효한가. Gemini 박스와 IoU가 얼마인가.
   하류의 그림·표 후보 추출과 크롭이 전부 이 좌표에 의존하므로 여기가 진짜 관문이다.
3. 비용·지연 — `media_resolution`이 OpenAI에서 무시되므로(`openai_client.py:114`) 이미지
   입력 토큰이 Gemini 대비 얼마나 늘어나는가.

실행:
    cd sasoo/backend
    .venv/bin/python -m tools.openai_vision_spike --selftest        # API 호출 없음
    OPENAI_API_KEY=... GEMINI_API_KEY=... \\
        .venv/bin/python -m tools.openai_vision_spike --pdf <경로> --pages 1,2,3
    # 키를 환경변수로 넘기지 않으려면 설정 DB에서 복호화해 쓴다(읽기 전용으로만 연다):
    .venv/bin/python -m tools.openai_vision_spike --pdf <경로> --db <경로>/library/sasoo.db
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from services.gemini_parser import (
    RENDER_DPI,
    _PAGE_PROMPT,
    _PAGE_RESPONSE_SCHEMA,
    _PARSER_SYSTEM_INSTRUCTION,
    _parse_json,
    _render_page_png,
)
from services.llm.interactions_client import call_interaction
from services.model_registry import resolve
from services.pricing import calc_cost

# 하류 파이프라인이 좌표를 실제로 쓰는 요소만 비교 대상으로 둔다.
_VISUAL_TYPES = ("image", "table")


async def _parse_page(png_b64: str, provider: str) -> dict[str, Any]:
    """페이지 1장을 지정 공급사로 파싱한다.

    effort를 `gemini_parser._THINKING_LEVEL`(기본 "minimal") 대신 레지스트리에서 가져오는 것이
    핵심이다. OpenAI는 minimal을 BadRequestError로 거부한다(플랜 Task 0 실측). 프로덕션
    코드를 고치기 전에 이 우회가 실제로 통하는지부터 확인하는 것이 이 스파이크의 목적이다.
    """
    choice = resolve("visual", provider)
    started = time.monotonic()
    result = await call_interaction(
        [
            {"type": "image", "data": png_b64, "mime_type": "image/png"},
            {"type": "text", "text": _PAGE_PROMPT},
        ],
        lane="pipeline",
        model=choice.model,
        system_instruction=_PARSER_SYSTEM_INSTRUCTION,
        thinking_level=choice.effort,
        store=False,
        response_schema=_PAGE_RESPONSE_SCHEMA,
    )
    elapsed = time.monotonic() - started

    data = _parse_json(result.get("text", ""))
    elements = data.get("elements") or []
    tokens_in = int(result.get("tokens_in", 0) or 0)
    tokens_out = int(result.get("tokens_out", 0) or 0)
    used_model = result.get("model", choice.model)

    bad_boxes = [e.get("box_2d") for e in elements if not _box_ok(e.get("box_2d"))]
    counts: dict[str, int] = {}
    for e in elements:
        counts[str(e.get("type"))] = counts.get(str(e.get("type")), 0) + 1

    return {
        "model": used_model,
        "effort": choice.effort,
        "elapsed_s": round(elapsed, 2),
        "markdown_chars": len(data.get("markdown") or ""),
        "element_counts": counts,
        "bad_box_count": len(bad_boxes),
        "bad_box_samples": bad_boxes[:3],
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_thought": int(result.get("tokens_thought", 0) or 0),
        "cost_usd": calc_cost(used_model, tokens_in, tokens_out),
        "elements": elements,
    }


def _box_ok(box: Any) -> bool:
    """box_2d가 [ymin, xmin, ymax, xmax] 0-1000 규약을 지키고 면적이 양수인가."""
    if not isinstance(box, list) or len(box) != 4:
        return False
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box):
        return False
    ymin, xmin, ymax, xmax = box
    if not all(0 <= float(v) <= 1000 for v in box):
        return False
    return ymax > ymin and xmax > xmin


def _iou(a: list[float], b: list[float]) -> float:
    ay0, ax0, ay1, ax1 = a
    by0, bx0, by1, bx1 = b
    ih = max(0.0, min(ay1, by1) - max(ay0, by0))
    iw = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    inter = ih * iw
    if inter <= 0:
        return 0.0
    union = (ay1 - ay0) * (ax1 - ax0) + (by1 - by0) * (bx1 - bx0) - inter
    return inter / union if union > 0 else 0.0


def _boxes(elements: list[dict[str, Any]], element_type: str) -> list[list[float]]:
    return [
        [float(v) for v in e["box_2d"]]
        for e in elements
        if e.get("type") == element_type and _box_ok(e.get("box_2d"))
    ]


def _match(ref: list[list[float]], cand: list[list[float]]) -> dict[str, Any]:
    """참조 박스마다 최고 IoU 후보를 그리디로 1:1 짝지어 통계를 낸다.

    그리디는 최적 할당(헝가리안)이 아니지만, 논문 페이지의 그림·표는 서로 겹치지 않아
    실질 차이가 없다. ponytail: 겹치는 박스가 흔해지면 헝가리안으로 올린다.
    """
    remaining = list(cand)
    ious: list[float] = []
    for r in ref:
        best_i, best = -1, 0.0
        for i, c in enumerate(remaining):
            v = _iou(r, c)
            if v > best:
                best_i, best = i, v
        ious.append(best)
        if best_i >= 0:
            remaining.pop(best_i)
    return {
        "ref_count": len(ref),
        "cand_count": len(cand),
        "iou50": sum(1 for v in ious if v >= 0.5),
        "iou75": sum(1 for v in ious if v >= 0.75),
        "mean_iou": round(sum(ious) / len(ious), 3) if ious else None,
        "unmatched_cand": len(remaining),
    }


async def _run(pdf: str, pages: list[int]) -> dict[str, Any]:
    doc = fitz.open(pdf)
    out: dict[str, Any] = {"pdf": pdf, "dpi": RENDER_DPI, "pages": []}
    try:
        for page_no in pages:
            png_b64, width, height = await _render_page_png(doc, page_no - 1, RENDER_DPI)
            rec: dict[str, Any] = {
                "page": page_no,
                "page_pt": [round(width, 1), round(height, 1)],
                "png_kb": round(len(png_b64) * 3 / 4 / 1024, 1),
            }
            for provider in ("gemini", "openai"):
                try:
                    rec[provider] = await _parse_page(png_b64, provider)
                except Exception as exc:  # 한쪽이 죽어도 다른 쪽 기록은 남긴다
                    rec[provider] = {"error": f"{type(exc).__name__}: {exc}"}

            gem, oai = rec["gemini"], rec["openai"]
            if "error" not in gem and "error" not in oai:
                rec["compare"] = {
                    t: _match(_boxes(gem["elements"], t), _boxes(oai["elements"], t))
                    for t in _VISUAL_TYPES
                }
                gem_chars = gem["markdown_chars"] or 1
                rec["markdown_ratio"] = round(oai["markdown_chars"] / gem_chars, 3)
                rec["tokens_in_ratio"] = round(oai["tokens_in"] / max(gem["tokens_in"], 1), 2)
            # elements 원본은 요약 출력에서 뺀다(페이지당 수십 KB).
            for provider in ("gemini", "openai"):
                rec[provider].pop("elements", None)
            out["pages"].append(rec)
    finally:
        doc.close()
    return out


def _load_keys_into_env(db_path: Path) -> list[str]:
    """설정 DB에서 키를 복호화해 이 프로세스 환경에만 심는다. 값은 절대 출력하지 않는다.

    `tools/provider_compare.load_keys`와 같은 경로지만 DB 위치를 인자로 받는다 — worktree의
    `library/sasoo.db`는 빈 파일이라 백엔드 상대 경로 기본값이 맞지 않는다. 사용자의 실제
    DB를 건드리지 않도록 `mode=ro`로만 연다.
    """
    import sqlite3

    from services.crypto import decrypt_value

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = dict(
            conn.execute(
                "SELECT key, value FROM settings WHERE key IN "
                "('openai_api_key', 'gemini_api_key')"
            ).fetchall()
        )
    finally:
        conn.close()

    sources: list[str] = []
    for setting, env_name in (
        ("openai_api_key", "OPENAI_API_KEY"),
        ("gemini_api_key", "GEMINI_API_KEY"),
    ):
        if os.environ.get(env_name):
            sources.append(f"{env_name}=환경변수")
            continue
        stored = rows.get(setting) or ""
        value = decrypt_value(stored) if stored else ""
        if value:
            os.environ[env_name] = value
            sources.append(f"{env_name}=설정DB")
        else:
            sources.append(f"{env_name}=없음")
    return sources


def _selftest() -> None:
    """API 없이 좌표 판정과 매칭 로직만 검증한다."""
    assert _box_ok([10, 20, 30, 40])
    assert not _box_ok([30, 20, 10, 40]), "ymax <= ymin 은 무효"
    assert not _box_ok([10, 20, 10, 40]), "면적 0은 무효"
    assert not _box_ok([-1, 20, 30, 40]), "범위 밖은 무효"
    assert not _box_ok([10, 20, 30]), "4원소가 아니면 무효"
    assert not _box_ok("nope")
    assert not _box_ok([True, 20, 30, 40]), "bool은 좌표가 아니다"

    assert _iou([0, 0, 100, 100], [0, 0, 100, 100]) == 1.0
    assert _iou([0, 0, 100, 100], [200, 200, 300, 300]) == 0.0
    half = _iou([0, 0, 100, 100], [0, 50, 100, 150])
    assert abs(half - 1 / 3) < 1e-9, half

    # 참조 2개 중 1개만 잘 맞고, 후보 1개는 남는다.
    stats = _match(
        [[0, 0, 100, 100], [200, 200, 300, 300]],
        [[0, 0, 100, 100], [900, 900, 1000, 1000]],
    )
    assert stats == {
        "ref_count": 2,
        "cand_count": 2,
        "iou50": 1,
        "iou75": 1,
        "mean_iou": 0.5,
        "unmatched_cand": 1,
    }, stats
    print("selftest ok")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", help="파싱할 PDF 경로")
    ap.add_argument("--pages", default="1,2,3", help="1-기반 페이지 번호 쉼표 구분")
    ap.add_argument("--db", help="키를 복호화해 올 설정 DB 경로(읽기 전용으로 연다)")
    ap.add_argument("--selftest", action="store_true", help="API 호출 없이 로직만 검증")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return
    if not args.pdf:
        ap.error("--pdf 가 필요하다 (또는 --selftest)")

    if args.db:
        print(" ".join(_load_keys_into_env(Path(args.db))), file=sys.stderr)

    pages = [int(p) for p in args.pages.split(",") if p.strip()]
    result = asyncio.run(_run(args.pdf, pages))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
