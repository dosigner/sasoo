"""
파서 엔진 비교 파일럿: ODL vs Gemini.

PDF x 엔진마다 wall time, 마크다운 문자수, 트리 요소 타입별 개수, figure 후보 수
(resolver LLM 호출 없음 — 비용 통제), gemini면 토큰/비용을 수집한다. 실패한 셀은
error로 기록하고 계속 진행한다.

사용:
    python scripts/pilot_parser_compare.py --pdfs a.pdf b.pdf --engines odl,gemini --out ./pilot_out

주의: gemini 셀은 실제 API를 호출해 과금된다(GEMINI_API_KEY 필요; 없으면 backend/.env에서
직접 파싱해 로드). odl 셀은 Java 런타임 + opendataloader-pdf가 필요하다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

# backend 루트를 import 경로에 추가(conftest.py와 동일한 방식).
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# gemini 튜닝 프로파일: env 래핑으로 baseline/tuned를 한 스위치로 재현한다.
# gemini_parser 모듈이 import 시점에 이 env를 읽으므로, 반드시 파서 import 전에 세팅한다.
_GEMINI_PROFILES: dict[str, dict[str, str]] = {
    "baseline": {
        "SASOO_GEMINI_PARSER_DPI": "180",
        "SASOO_GEMINI_PARSER_THINKING": "low",
        "SASOO_GEMINI_PARSER_MEDIA_RESOLUTION": "",  # 미지정 = SDK 기본 해상도
        "SASOO_GEMINI_PARSER_ELEMENTS": "full",
    },
    "tuned": {
        "SASOO_GEMINI_PARSER_DPI": "150",
        "SASOO_GEMINI_PARSER_THINKING": "minimal",
        "SASOO_GEMINI_PARSER_MEDIA_RESOLUTION": "low",
        "SASOO_GEMINI_PARSER_ELEMENTS": "slim",
    },
}


def _apply_gemini_profile(profile: str | None) -> None:
    if not profile:
        return
    import os

    settings = _GEMINI_PROFILES.get(profile)
    if settings is None:
        raise SystemExit(f"unknown --gemini-profile: {profile!r} (baseline|tuned)")
    os.environ.update(settings)


def _load_env_gemini_key() -> None:
    """GEMINI_API_KEY가 env에 없으면 backend/.env를 직접 파싱해 로드(새 의존성 금지)."""
    import os

    if os.environ.get("GEMINI_API_KEY"):
        return
    env_path = BACKEND_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if key == "GEMINI_API_KEY" and value.strip():
            os.environ["GEMINI_API_KEY"] = value.strip().strip('"').strip("'")
            break


def _count_element_types(root: dict[str, Any]) -> dict[str, int]:
    """ODL 호환 트리를 재귀 순회해 type별 개수를 센다(kids/list items/rows.cells)."""
    counts: dict[str, int] = {}

    def _walk(elements: Any) -> None:
        if not isinstance(elements, list):
            return
        for element in elements:
            if not isinstance(element, dict):
                continue
            etype = str(element.get("type", "") or "unknown")
            counts[etype] = counts.get(etype, 0) + 1
            _walk(element.get("kids"))
            _walk(element.get("list items"))
            rows = element.get("rows")
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        _walk(row.get("cells"))

    _walk(root.get("kids"))
    return counts


def _run_engine(
    pdf_path: Path, engine: str, work_dir: Path, md_out: Path | None = None
) -> dict[str, Any]:
    """한 (pdf, engine) 셀을 실행해 지표 dict를 반환. 실패 시 {"error": ...}."""
    from services.document_manifest import build_document_manifest
    from services.figure_candidates import build_figure_candidates

    output_dir = work_dir / "out"
    figures_dir = work_dir / "figures"
    output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    usage: dict[str, Any] = {}
    start = time.perf_counter()
    try:
        if engine == "gemini":
            from services.gemini_parser import run_convert_gemini

            root, markdown_text, actual_engine = asyncio.run(
                run_convert_gemini(pdf_path, output_dir, figures_dir, usage_out=usage)
            )
        elif engine == "odl":
            from services.odl_parser import _run_convert

            root, markdown_text, actual_engine = _run_convert(
                pdf_path, output_dir, figures_dir, "java", engine="odl"
            )
        else:
            raise ValueError(f"unknown engine: {engine}")

        if md_out is not None:
            md_out.write_text(markdown_text, encoding="utf-8")

        # figure 후보 수 (resolver LLM 호출 없이 후보 생성까지만).
        manifest = build_document_manifest(
            pdf_path=pdf_path,
            paper_dir=work_dir,
            root=root,
            markdown_text=markdown_text,
            actual_engine=actual_engine,
            requested_mode=engine,
            extraction_pipeline_version="resolver_v1",
            parser_version="pilot",
            resolver_version="pilot",
            generate_page_rasters=False,
        )
        figure_candidates = build_figure_candidates(manifest, pdf_path=pdf_path)

        elapsed = time.perf_counter() - start
        type_counts = _count_element_types(root)
        cell: dict[str, Any] = {
            "engine": actual_engine,
            "wall_time_s": round(elapsed, 3),
            "markdown_chars": len(markdown_text),
            "element_counts": type_counts,
            "image_elements": type_counts.get("image", 0) + type_counts.get("picture", 0),
            "table_elements": type_counts.get("table", 0),
            "caption_elements": type_counts.get("caption", 0),
            "figure_candidates": len(figure_candidates),
            "pages": int(root.get("number of pages") or 0),
        }
        if engine == "gemini":
            cell["tokens_in"] = usage.get("tokens_in", 0)
            cell["tokens_out"] = usage.get("tokens_out", 0)
            cell["cost_usd"] = usage.get("cost_usd", 0.0)
        return cell
    except Exception as exc:  # noqa: BLE001 - 셀 단위 격리
        return {
            "engine": engine,
            "wall_time_s": round(time.perf_counter() - start, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _print_markdown_table(results: list[dict[str, Any]]) -> None:
    header = [
        "pdf", "engine", "time(s)", "md_chars", "img", "table", "caption",
        "fig_cand", "tokens_in", "tokens_out", "cost_usd", "error",
    ]
    print("| " + " | ".join(header) + " |")
    print("| " + " | ".join("---" for _ in header) + " |")
    for row in results:
        cell = row["metrics"]
        line = [
            row["pdf"],
            cell.get("engine", row["engine"]),
            str(cell.get("wall_time_s", "")),
            str(cell.get("markdown_chars", "")),
            str(cell.get("image_elements", "")),
            str(cell.get("table_elements", "")),
            str(cell.get("caption_elements", "")),
            str(cell.get("figure_candidates", "")),
            str(cell.get("tokens_in", "")),
            str(cell.get("tokens_out", "")),
            str(cell.get("cost_usd", "")),
            cell.get("error", ""),
        ]
        print("| " + " | ".join(line) + " |")


def main() -> None:
    parser = argparse.ArgumentParser(description="ODL vs Gemini 파서 엔진 비교")
    parser.add_argument("--pdfs", nargs="+", required=True, help="비교할 PDF 경로들")
    parser.add_argument("--engines", default="odl,gemini", help="쉼표 구분 엔진 목록")
    parser.add_argument("--out", required=True, help="결과 출력 디렉토리")
    parser.add_argument(
        "--save-markdown",
        action="store_true",
        help="엔진별 변환 마크다운을 <out>/<pdf>.<engine>.md로 저장 (정성 비교용)",
    )
    parser.add_argument(
        "--gemini-profile",
        choices=sorted(_GEMINI_PROFILES),
        default=None,
        help="gemini 튜닝 env 프리셋(baseline|tuned). 개별 SASOO_GEMINI_PARSER_* env로 세부 조정 가능.",
    )
    args = parser.parse_args()

    _apply_gemini_profile(args.gemini_profile)
    _load_env_gemini_key()

    engines = [e.strip().lower() for e in args.engines.split(",") if e.strip()]
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for pdf_arg in args.pdfs:
        pdf_path = Path(pdf_arg).resolve()
        for engine in engines:
            if not pdf_path.exists():
                metrics = {"engine": engine, "error": f"PDF not found: {pdf_path}"}
            else:
                md_out = (
                    out_dir / f"{pdf_path.stem}.{engine}.md" if args.save_markdown else None
                )
                with TemporaryDirectory() as tmp:
                    metrics = _run_engine(pdf_path, engine, Path(tmp), md_out=md_out)
            results.append({"pdf": pdf_path.name, "engine": engine, "metrics": metrics})
            status = metrics.get("error") or f"{metrics.get('wall_time_s')}s"
            print(f"[done] {pdf_path.name} x {engine}: {status}", file=sys.stderr)

    results_path = out_dir / "results.json"
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nresults.json -> {results_path}\n", file=sys.stderr)
    _print_markdown_table(results)


if __name__ == "__main__":
    main()
