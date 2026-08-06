"""Evidence Anchoring 회귀 지표 하네스 (단일 lane).

검증기는 완전 결정론이라 LLM을 부르지 않는다 — 이미 저장된 recipe 결과와 PDF만 읽는다.
그래서 lane이 하나다(tools/extraction_audit는 VLM 비결정성 때문에 2-lane이다).

실행:
    cd sasoo/backend
    .venv/bin/python -m tools.evidence_audit.measure
    .venv/bin/python -m tools.evidence_audit.measure --limit 5 --json _out/metrics.json

측정 지표:
    quote_offer_rate     인용을 준 파라미터 / 전체 파라미터   (프롬프트 준수도)
    verified_rate        VERIFIED / 인용을 준 파라미터        (핵심 KPI)
    parameter_verified_rate  VERIFIED / 전체 파라미터         (사용자 체감)
    exact/normalized/partial/not_found_rate                   (정규화 규칙 효과)
    value_present_rate   값 가드 통과 / 인용이 확인된 파라미터
    page_confirm_rate    page_status=match / 인용이 확인된 파라미터  (LLM 페이지 신뢰도)
    bbox_rate            bbox 있는 앵커 / 인용이 확인된 파라미터     (하이라이트 커버리지)
    forged_false_verify  숫자 1자리 변조 인용이 VERIFIED가 된 건수  (0이어야 한다)
    elapsed_ms           논문당 검증 소요                            (동기 실행 유지 판단)

퍼센트만 쓰지 않고 항상 n/N을 함께 낸다. 분모는 세 축으로 분리해 보고한다
(설계 스펙 §회귀 지표 — "분모를 parser engine·match method·source_tag별로 분리 보고"):
    - parser engine(ODL/Gemini)   → by_engine            엔진 비대칭 재발 감시
    - match method(exact/normalized/partial/none) → exact_rate/normalized_rate/
      partial_rate/not_found_rate가 이미 이 분해다. QuoteMatch.match_method는
      "exact"→verified_exact, "normalized"→verified_normalized, "partial"→partial_match,
      None→{no_quote,not_found,no_text_layer,invalid_page,ambiguous,stale_source,
      verifier_error} 로 quote_status 버킷과 1:1 대응하므로 별도 by_match_method
      테이블은 같은 숫자를 중복 출력할 뿐이라 만들지 않는다.
    - source_tag(explicit/inferred/computed 등) → by_source_tag. inferred 파라미터는
      구조적으로 VERIFIED 불가(값 가드가 "inferred"면 value_status="inferred"로 항상
      막힌다)이므로 explicit과 뭉치면 verified_rate가 오염된다 — 반드시 따로 본다.

by_engine·by_source_tag 둘 다 parameter_verified_rate 외에 value_present_rate·
page_confirm_rate·bbox_rate까지 n/N과 함께 JSON에 낸다(콘솔 출력은 parameter_verified_rate만
찍는다 — JSON이 기록용, 콘솔은 한눈에 보는 요약용). forged_false_verify는 축 분해하지
않는다 — "0이어야 하는 불변식"이라 축별로 쪼개도 판정 기준이 달라지지 않고(어느 축에서든
하나라도 나오면 전체가 실패), 실패 시 원인 추적은 축 집계가 아니라 papers[] 안의 논문별
원본 레코드(folder_name·engine·source_tag를 이미 담고 있다)를 직접 봐야 하기 때문이다.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from models.database import DB_PATH, get_paper_dir  # noqa: E402
from services.evidence_verifier import (  # noqa: E402
    EVIDENCE_NORMALIZER_VERSION,
    EVIDENCE_VERIFIER_VERSION,
    iter_recipe_parameters,
    verify_recipe_parameters,
)

OUT_DIR = Path(__file__).resolve().parent / "_out"
_DIGIT = re.compile(r"\d")


def _find_pdf(paper_dir: Path) -> Optional[Path]:
    """api.analysis_routes._find_paper_pdf와 같은 규칙(라우트 import는 FastAPI를 끌고 온다)."""
    try:
        pdfs = sorted(paper_dir.glob("*.pdf"))
    except OSError:
        return None
    return pdfs[0] if pdfs else None


def _manifest_engine(paper_dir: Path) -> str:
    manifest = paper_dir / ".odl_manifest.json"
    if not manifest.exists():
        return "unknown"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    return str(payload.get("engine") or "unknown")


def latest_recipe_rows(db_path, limit: Optional[int] = None) -> list[dict[str, Any]]:
    """논문별 최신 recipe 행을 읽는다(읽기 전용 연결 — 앱 DB를 건드리지 않는다)."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT p.id AS paper_id, p.folder_name AS folder_name,
                   ar.id AS result_id, ar.result AS result
            FROM papers p
            JOIN analysis_results ar ON ar.id = (
                SELECT id FROM analysis_results
                WHERE paper_id = p.id AND phase = 'recipe'
                ORDER BY created_at DESC, id DESC LIMIT 1
            )
            ORDER BY p.id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    collected: list[dict[str, Any]] = []
    for row in rows:
        try:
            recipe = json.loads(row["result"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(recipe, dict) or "_parse_error" in recipe or recipe.get("skipped"):
            continue
        paper_dir = get_paper_dir(row["folder_name"])
        collected.append(
            {
                "paper_id": row["paper_id"],
                "folder_name": row["folder_name"],
                "result_id": row["result_id"],
                "recipe": recipe,
                "paper_dir": paper_dir,
                "engine": _manifest_engine(paper_dir),
            }
        )
        if limit is not None and len(collected) >= limit:
            break
    return collected


def _forge(quote: str) -> Optional[str]:
    """인용의 마지막 숫자 한 자리를 바꾼 위조본. 숫자가 없으면 None."""
    matches = list(_DIGIT.finditer(quote))
    if not matches:
        return None
    at = matches[-1].start()
    original = quote[at]
    replacement = "9" if original != "9" else "1"
    return quote[:at] + replacement + quote[at + 1 :]


def measure_paper(row: dict[str, Any]) -> dict[str, Any]:
    pdf_path = _find_pdf(row["paper_dir"])
    started = time.perf_counter()
    drafts = verify_recipe_parameters(row["recipe"], pdf_path)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    parameters = iter_recipe_parameters(row["recipe"])
    offered = sum(1 for _, param in parameters if str(param.get("evidence_quote") or "").strip())
    by_display = Counter(draft.display_status for draft in drafts)
    by_quote = Counter(draft.quote_status for draft in drafts)
    located = [d for d in drafts if d.quote_status in {"verified_exact", "verified_normalized"}]

    # source_tag별 분모 분리 — inferred 파라미터는 구조적으로 VERIFIED 불가하므로
    # explicit과 뭉치면 verified_rate가 오염된다(설계 스펙 §회귀 지표). value_present/
    # page_confirmed/bbox도 같은 이유로 함께 쪼갠다 — located(=exact+normalized) 모수
    # 자체가 source_tag마다 다르므로 전체 합산 비율만 보면 어느 축이 끌어내렸는지 안 보인다.
    by_source_tag: dict[str, Counter] = defaultdict(Counter)
    for draft in drafts:
        tag = draft.source_tag or "unspecified"
        counter = by_source_tag[tag]
        counter["parameters"] += 1
        if str(draft.claimed_quote or "").strip():
            counter["offered"] += 1
        if draft.display_status == "VERIFIED":
            counter["verified"] += 1
        if draft.quote_status in {"verified_exact", "verified_normalized"}:
            counter["located"] += 1
            if draft.value_status == "value_in_quote":
                counter["value_present"] += 1
            if draft.page_status == "match":
                counter["page_confirmed"] += 1
            if draft.bbox_json:
                counter["bbox"] += 1

    # 위조 인용 게이트: 확인된 인용의 숫자를 한 자리 바꿔 다시 검증한다.
    forged_params = []
    for draft in located:
        forged = _forge(draft.claimed_quote or "")
        if forged is None:
            continue
        forged_params.append(
            {
                "name": draft.target_label,
                "value": "0",
                "source_tag": "explicit",
                "evidence_quote": forged,
                "evidence_page": draft.matched_page,
            }
        )
    forged_drafts = (
        verify_recipe_parameters({"parameters": forged_params}, pdf_path) if forged_params else []
    )

    return {
        "paper_id": row["paper_id"],
        "folder_name": row["folder_name"],
        "engine": row["engine"],
        "pdf": str(pdf_path) if pdf_path else None,
        "parameters": len(drafts),
        "offered": offered,
        "by_display_status": dict(by_display),
        "by_quote_status": dict(by_quote),
        "by_source_tag": {tag: dict(counter) for tag, counter in by_source_tag.items()},
        "verified": by_display.get("VERIFIED", 0),
        "exact": by_quote.get("verified_exact", 0),
        "normalized": by_quote.get("verified_normalized", 0),
        "partial": by_quote.get("partial_match", 0),
        "not_found": by_quote.get("not_found", 0),
        "value_present": sum(1 for d in located if d.value_status == "value_in_quote"),
        "page_confirmed": sum(1 for d in located if d.page_status == "match"),
        "bbox": sum(1 for d in located if d.bbox_json),
        "forged_attempts": len(forged_params),
        "forged_false_verify": sum(1 for d in forged_drafts if d.display_status == "VERIFIED"),
        "elapsed_ms": round(elapsed_ms, 1),
    }


def _ratio(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "n/a (0/0)"
    return f"{numerator / denominator:.3f} ({numerator}/{denominator})"


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    totals: Counter = Counter()
    for result in results:
        for key in (
            "parameters", "offered", "verified", "exact", "normalized", "partial",
            "not_found", "value_present", "page_confirmed", "bbox",
            "forged_attempts", "forged_false_verify",
        ):
            totals[key] += result[key]

    located = totals["exact"] + totals["normalized"]
    by_engine: dict[str, Counter] = defaultdict(Counter)
    for result in results:
        counter = by_engine[result["engine"]]
        counter["parameters"] += result["parameters"]
        counter["verified"] += result["verified"]
        counter["offered"] += result["offered"]
        counter["located"] += result["exact"] + result["normalized"]
        counter["value_present"] += result["value_present"]
        counter["page_confirmed"] += result["page_confirmed"]
        counter["bbox"] += result["bbox"]

    by_source_tag: dict[str, Counter] = defaultdict(Counter)
    for result in results:
        for tag, tag_counter in result["by_source_tag"].items():
            counter = by_source_tag[tag]
            for key in (
                "parameters", "offered", "verified", "located",
                "value_present", "page_confirmed", "bbox",
            ):
                counter[key] += tag_counter.get(key, 0)

    return {
        "verifier_version": EVIDENCE_VERIFIER_VERSION,
        "normalizer_version": EVIDENCE_NORMALIZER_VERSION,
        "papers": len(results),
        "quote_offer_rate": _ratio(totals["offered"], totals["parameters"]),
        "verified_rate": _ratio(totals["verified"], totals["offered"]),
        "parameter_verified_rate": _ratio(totals["verified"], totals["parameters"]),
        "exact_rate": _ratio(totals["exact"], totals["parameters"]),
        "normalized_rate": _ratio(totals["normalized"], totals["parameters"]),
        "partial_rate": _ratio(totals["partial"], totals["parameters"]),
        "not_found_rate": _ratio(totals["not_found"], totals["parameters"]),
        "value_present_rate": _ratio(totals["value_present"], located),
        "page_confirm_rate": _ratio(totals["page_confirmed"], located),
        "bbox_rate": _ratio(totals["bbox"], located),
        "forged_false_verify": f"{totals['forged_false_verify']}/{totals['forged_attempts']}",
        "elapsed_ms_max": max((r["elapsed_ms"] for r in results), default=0.0),
        "by_engine": {
            engine: {
                "parameters": counter["parameters"],
                "offered": counter["offered"],
                "verified": counter["verified"],
                "located": counter["located"],
                "value_present": counter["value_present"],
                "page_confirmed": counter["page_confirmed"],
                "bbox": counter["bbox"],
                "parameter_verified_rate": _ratio(counter["verified"], counter["parameters"]),
                "value_present_rate": _ratio(counter["value_present"], counter["located"]),
                "page_confirm_rate": _ratio(counter["page_confirmed"], counter["located"]),
                "bbox_rate": _ratio(counter["bbox"], counter["located"]),
            }
            for engine, counter in sorted(by_engine.items())
        },
        "by_source_tag": {
            tag: {
                "parameters": counter["parameters"],
                "offered": counter["offered"],
                "verified": counter["verified"],
                "located": counter["located"],
                "value_present": counter["value_present"],
                "page_confirmed": counter["page_confirmed"],
                "bbox": counter["bbox"],
                "parameter_verified_rate": _ratio(counter["verified"], counter["parameters"]),
                "value_present_rate": _ratio(counter["value_present"], counter["located"]),
                "page_confirm_rate": _ratio(counter["page_confirmed"], counter["located"]),
                "bbox_rate": _ratio(counter["bbox"], counter["located"]),
            }
            for tag, counter in sorted(by_source_tag.items())
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evidence Anchoring 회귀 지표 측정")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", default=None, help="지표 JSON 저장 경로")
    args = parser.parse_args(argv)

    rows = latest_recipe_rows(args.db, limit=args.limit)
    if not rows:
        print("recipe 결과가 없습니다. 분석을 먼저 실행하세요.")
        return 1

    results = [measure_paper(row) for row in rows]
    summary = aggregate(results)

    print(f"papers={summary['papers']}  verifier={summary['verifier_version']}/{summary['normalizer_version']}")
    for key in (
        "quote_offer_rate", "verified_rate", "parameter_verified_rate",
        "exact_rate", "normalized_rate", "partial_rate", "not_found_rate",
        "value_present_rate", "page_confirm_rate", "bbox_rate", "forged_false_verify",
    ):
        print(f"  {key:<24} {summary[key]}")
    print(f"  {'elapsed_ms_max':<24} {summary['elapsed_ms_max']}")
    for engine, stats in summary["by_engine"].items():
        print(f"  engine[{engine}] {stats['parameter_verified_rate']}")
    for tag, stats in summary["by_source_tag"].items():
        print(f"  source_tag[{tag}] {stats['parameter_verified_rate']}")

    out_path = Path(args.json) if args.json else OUT_DIR / f"metrics-{int(time.time())}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"summary": summary, "papers": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
