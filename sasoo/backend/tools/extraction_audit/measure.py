"""S1 — 그림·표 추출 정확도 측정 하네스 (2-lane).

플랜 §4-S1의 요건 그대로:

1. **그림과 표를 같은 실행에서 함께 낸다.** 로마 확장과 캡션 게이트는 `_caption_kind`·
   `TABLE_LABEL_PATTERN` 등 그림과 공유하는 코드를 건드린다. 표만 재고 넘어가면 그림
   12편 정확일치가 조용히 깨진다.
2. **두 lane을 나란히 기록한다.**
   - `deterministic` (GEMINI_API_KEY 제거): VLM 비결정성 없이 재현 가능한 진단.
     후보 수, gold 캡션별 후보 재현율, 캡션 소유권, 폴백 후보 생성 여부.
   - `production` (키 있음): 최종 FP/FN, 폴백 성공률, VLM 호출 수.
3. 저장된 매니페스트의 `kind`는 옛 코드 산출물이라 현재 규칙으로 재계산한다.
   `if k: c["kind"] = k`로 쓰면 새 규칙이 None을 낼 때 옛 "figure"가 남아 "덜 인정"하는
   방향의 변경이 측정에 전혀 반영되지 않는다 — 반드시 `or "unknown"`.
4. 개수뿐 아니라 라벨 집합, `caption is None`, `source_kind`, `parse_method`, `confidence`를
   함께 찍는다.

VLM 캐시는 비용이 아니라 **재현성** 때문에 쓴다. 캐시가 없으면 수정 전후의 델타가 내
수정 때문인지 VLM 흔들림 때문인지 구분할 수 없다. `--no-cache`로 끄고 3회 반복하면
노이즈 바닥(라벨 집합이 흔들리는 폭)을 잰다.

실행:
    cd sasoo/backend
    .venv/bin/python -m tools.extraction_audit.measure                 # 두 lane 모두
    .venv/bin/python -m tools.extraction_audit.measure --lane deterministic
    .venv/bin/python -m tools.extraction_audit.measure --no-cache --repeat 3   # 노이즈 바닥
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services import table_resolver  # noqa: E402
from services.document_audit import find_suspect_pages  # noqa: E402
from services.document_manifest import (  # noqa: E402
    _caption_kind,
    recover_missing_caption_blocks,
)
from services.figure_candidates import build_figure_candidates  # noqa: E402
from services.figure_resolver import resolve_figure_candidates  # noqa: E402
from services.odl_parser import _merge_page_scoped_items  # noqa: E402
from services.table_candidates import build_table_candidates  # noqa: E402
from services.table_resolver import resolve_table_candidates  # noqa: E402
from tools.extraction_audit.table_labels import match_table_label, normalize  # noqa: E402

BACKEND = Path(__file__).resolve().parents[2]
LIBRARY = BACKEND / "library"
GOLD_PATH = BACKEND.parents[1] / "docs" / "table_gold.json"
CACHE_DIR = Path(__file__).resolve().parent / "_vlm_cache"
OUT_DIR = Path(__file__).resolve().parent / "_out"

FIGURE_MENTION = re.compile(r"\b(?:Figure|Fig\.?)\s*(\d{1,2})\b", re.I)

# 캐시 키에 섞는다. 프롬프트나 입력 구성을 바꾸면 올려서 캐시를 무효화한다.
VLM_PROMPT_VERSION = "v1"


# ──────────────────────────────────────────────────────────────────────────────
# 준비
# ──────────────────────────────────────────────────────────────────────────────


def load_gold() -> dict[str, dict]:
    return json.loads(GOLD_PATH.read_text(encoding="utf-8"))["papers"]


def iter_papers(filter_substring: str | None = None, *, require_manifest: bool = True) -> list[Path]:
    """정답셋 후보 논문 디렉터리를 고른다.

    `require_manifest=False`(재파싱 모드)에서는 저장된 매니페스트가 필요 없으므로
    `*.pdf`만 있으면 후보로 인정한다.
    """
    papers = sorted(
        directory
        for directory in LIBRARY.iterdir()
        if (not require_manifest or (directory / ".odl_manifest.json").exists()) and any(directory.glob("*.pdf"))
    )
    if filter_substring:
        papers = [p for p in papers if filter_substring.lower() in p.name.lower()]
    return papers


def prepare_manifest(paper_dir: Path, pdf_path: Path) -> dict[str, Any]:
    """저장된 매니페스트를 현재 코드 기준으로 되살린다."""
    manifest = json.loads((paper_dir / ".odl_manifest.json").read_text(encoding="utf-8"))
    for caption in manifest.get("captions", []) or []:
        caption["kind"] = _caption_kind(caption.get("text") or "") or "unknown"
    for page in manifest.get("pages", []) or []:
        for caption in page.get("caption_blocks", []) or []:
            caption["kind"] = _caption_kind(caption.get("text") or "") or "unknown"
    # 저장된 매니페스트는 캡션 복원 이전 산출물이므로 현재 파이프라인과 같게 복원을 태운다.
    manifest.setdefault("captions", []).extend(
        recover_missing_caption_blocks(
            pdf_path=pdf_path,
            pages={page["page_number"]: page for page in manifest.get("pages", [])},
        )
    )
    # 이전 실행 결과는 지운다 — audit이 tables를 읽으므로 남아 있으면 판정이 오염된다.
    for key in ("figures", "tables", "figure_candidates", "table_candidates", "audit"):
        manifest.pop(key, None)
    return manifest


async def _reparse_manifest(pdf_path: Path, scratch: Path, provider: str) -> dict[str, Any]:
    """비전 엔진으로 매니페스트를 새로 만든다(저장된 산출물을 쓰지 않는다).

    프로덕션 경로(_build_resolver_v1_manifest)와 같은 인자로 build_document_manifest를
    부르는 것이 핵심이다 — 여기서 인자가 어긋나면 "제품이 이렇게 뽑는다"가 아니라
    "감사 도구가 이렇게 뽑는다"를 재게 된다.
    """
    from services.document_manifest import build_document_manifest
    from services.gemini_parser import run_convert_gemini
    from services.odl_parser import (
        RESOLVER_PARSER_VERSION,
        RESOLVER_PIPELINE_VERSION,
    )

    figures_dir = scratch / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    root, markdown_text, actual_engine = await run_convert_gemini(
        pdf_path, scratch, figures_dir, provider=provider
    )
    return build_document_manifest(
        pdf_path=pdf_path,
        paper_dir=scratch,
        root=root,
        markdown_text=markdown_text,
        actual_engine=actual_engine,
        requested_mode="fast",
        extraction_pipeline_version=RESOLVER_PIPELINE_VERSION,
        parser_version=RESOLVER_PARSER_VERSION,
        resolver_version="audit",
    )


def make_scratch_dir(paper_dir: Path, manifest: dict[str, Any] | None = None, pdf_path: Path | None = None) -> Path:
    """산출물을 라이브러리에 쓰지 않도록 래스터만 심볼릭 링크한 작업 디렉터리를 만든다.

    저장된 매니페스트에 `raster_path`가 없는 논문이 있다(2013_IEEETIP은 13페이지 전부).
    표의 격자 복원은 페이지 래스터가 있어야 VLM을 호출조차 하므로, 그대로 재면
    "제품이 표를 못 잡는다"가 아니라 "옛 산출물에 래스터가 없다"를 재게 된다
    (인수인계 §6-3: 저장된 매니페스트는 옛 코드 산출물이다).
    현재 코드와 같게 래스터를 만들되, **스크래치에** 만들어 사용자 라이브러리는 건드리지 않는다.
    """
    scratch = Path(tempfile.mkdtemp(prefix="tblaudit_"))
    pages = (manifest or {}).get("pages") or []
    needs_raster = bool(pages) and not any(page.get("raster_path") for page in pages)

    for name in (".page_rasters", ".odl_raw_images"):
        source = paper_dir / name
        if name == ".page_rasters" and needs_raster:
            continue  # 아래에서 스크래치에 직접 만든다
        if source.exists():
            (scratch / name).symlink_to(source.resolve(), target_is_directory=True)

    if needs_raster and pdf_path is not None:
        from services.document_manifest import _ensure_page_rasters

        raster_paths = _ensure_page_rasters(pdf_path, scratch, len(pages))
        for page in pages:
            page["raster_path"] = raster_paths.get(page["page_number"])
    return scratch


# ──────────────────────────────────────────────────────────────────────────────
# VLM 캐시 (재현성용)
# ──────────────────────────────────────────────────────────────────────────────


class VlmCache:
    """`_repair_with_vlm`을 감싸 디스크 캐시를 씌운다.

    계약(인수인계 §6-2)이 금지한 것은 **성능 벤치마크**에서 `call_interaction`을 대체해
    재시도·세마포어를 우회하는 것이다. 여기는 정확도 측정의 결정성 확보이고, 히트율을
    로그로 남겨 캐시가 실제 호출을 가려버렸는지 알 수 있게 한다.
    """

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self.hits = 0
        self.misses = 0
        self.calls = 0
        self.successes = 0
        self.original = table_resolver._repair_with_vlm
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _key(self, candidate: dict[str, Any], pdf_digest: str, provider: str) -> str:
        payload = json.dumps(
            {
                "pdf": pdf_digest,
                "page": candidate.get("page_number"),
                "bbox": [round(float(v), 2) for v in (candidate.get("bbox") or [])],
                "grid": candidate.get("text_grid"),
                "prompt": VLM_PROMPT_VERSION,
                "provider": provider,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def install(self, pdf_digest: str) -> None:
        original = self.original

        async def wrapper(candidate, manifest, paper_dir, *, provider: str = "gemini"):  # noqa: ANN001
            self.calls += 1
            cache_path = CACHE_DIR / f"{self._key(candidate, pdf_digest, provider)}.json"
            if self.enabled and cache_path.exists():
                self.hits += 1
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                result = (cached["rows"], cached["model"], cached["confidence"])
            else:
                self.misses += 1
                result = await original(candidate, manifest, paper_dir, provider=provider)
                if self.enabled:
                    cache_path.write_text(
                        json.dumps(
                            {"rows": result[0], "model": result[1], "confidence": result[2]},
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
            if table_resolver._has_meaningful_grid(result[0]):
                self.successes += 1
            return result

        table_resolver._repair_with_vlm = wrapper

    def restore(self) -> None:
        table_resolver._repair_with_vlm = self.original


# ──────────────────────────────────────────────────────────────────────────────
# 파이프라인 재현 (odl_parser._build_manifest_with_visuals와 같은 순서)
# ──────────────────────────────────────────────────────────────────────────────


async def run_pipeline(manifest: dict[str, Any], *, pdf_path: Path, scratch: Path) -> dict[str, Any]:
    manifest["figure_candidates"] = build_figure_candidates(manifest, pdf_path=pdf_path)
    figure_result = await resolve_figure_candidates(
        manifest, paper_dir=scratch, pdf_path=pdf_path, resolver_version="audit"
    )
    manifest["figures"] = figure_result["figures"]
    low_figure_pages = set(figure_result.get("low_confidence_pages", []))

    manifest["table_candidates"] = build_table_candidates(manifest, pdf_path=pdf_path, paper_dir=scratch)
    first_pass_candidates = [dict(candidate) for candidate in manifest["table_candidates"]]
    table_result = await resolve_table_candidates(manifest, paper_dir=scratch, resolver_version="audit")
    manifest["tables"] = table_result["tables"]
    low_table_pages = set(table_result.get("low_confidence_pages", []))

    audit = find_suspect_pages(
        full_text=manifest.get("full_text", ""),
        pages=manifest.get("pages", []),
        figures=manifest.get("figures", []),
        tables=manifest.get("tables", []),
        figure_candidates=manifest.get("figure_candidates", []),
        table_candidates=manifest.get("table_candidates", []),
    )
    manifest["audit"] = audit
    suspect_pages = {page for page in audit.get("suspect_pages", []) if isinstance(page, int)}
    parser_failed_pages = {page for page in (manifest.get("parser_failed_pages") or []) if isinstance(page, int)}
    if parser_failed_pages:
        suspect_pages |= parser_failed_pages
        audit["suspect_pages"] = sorted(suspect_pages)

    retry_figure_pages = low_figure_pages | suspect_pages
    retry_table_pages = low_table_pages | suspect_pages

    if retry_figure_pages:
        manifest["figure_candidates"] = _merge_page_scoped_items(
            manifest["figure_candidates"],
            build_figure_candidates(manifest, pdf_path=pdf_path, page_numbers=retry_figure_pages, aggressive=True),
            retry_figure_pages,
        )
        retried = await resolve_figure_candidates(
            manifest,
            paper_dir=scratch,
            pdf_path=pdf_path,
            resolver_version="audit",
            page_numbers=retry_figure_pages,
        )
        manifest["figures"] = _merge_page_scoped_items(manifest["figures"], retried["figures"], retry_figure_pages)

    if retry_table_pages:
        manifest["table_candidates"] = _merge_page_scoped_items(
            manifest["table_candidates"],
            build_table_candidates(
                manifest, pdf_path=pdf_path, paper_dir=scratch, page_numbers=retry_table_pages, aggressive=True
            ),
            retry_table_pages,
        )
        retried = await resolve_table_candidates(
            manifest, paper_dir=scratch, resolver_version="audit", page_numbers=retry_table_pages
        )
        manifest["tables"] = _merge_page_scoped_items(manifest["tables"], retried["tables"], retry_table_pages)

    return {
        "figures": manifest["figures"],
        "tables": manifest["tables"],
        "table_candidates": manifest["table_candidates"],
        "first_pass_candidates": first_pass_candidates,
        "audit": audit,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 지표
# ──────────────────────────────────────────────────────────────────────────────


def _extracted_table_numbers(tables: list[dict[str, Any]]) -> Counter:
    """산출된 표 이름에서 번호를 뽑는다. `Table 2 [2]`는 같은 번호가 2개인 것으로 센다."""
    numbers: Counter = Counter()
    for table in tables:
        matched = match_table_label(normalize(str(table.get("table_num") or "")))
        numbers[matched[1] if matched else None] += 1
    return numbers


def table_metrics(tables: list[dict[str, Any]], gold_numbers: list[int]) -> dict[str, Any]:
    gold_set = set(gold_numbers)
    extracted = _extracted_table_numbers(tables)
    false_positive = sum(max(0, count - (1 if number in gold_set else 0)) for number, count in extracted.items())
    false_negative = len(gold_set - set(extracted))
    linked = sum(1 for table in tables if table.get("caption"))
    return {
        "extracted_count": len(tables),
        "extracted_numbers": sorted(n for n in extracted if n is not None),
        "fp": false_positive,
        "fn": false_negative,
        "error": false_positive + false_negative,
        "exact": false_positive == 0 and false_negative == 0,
        "caption_linked": linked,
        "caption_link_rate": (linked / len(tables)) if tables else 1.0,
        "parse_methods": dict(Counter(table.get("parse_method") for table in tables)),
    }


def figure_metrics(figures: list[dict[str, Any]], markdown_text: str) -> dict[str, Any]:
    """그림 정확도는 **부모 그림 번호 집합**으로 잰다.

    `Fig. 11C`는 Fig. 11의 서브피겨이지 별도의 그림이 아니다. 서브피겨 분해
    (`figure_resolver._maybe_detect_subfigures`)는 GEMINI_API_KEY가 있어야 동작하므로,
    라벨을 그대로 세면 키 유무만으로 그림 수가 두 배가 되어 두 lane을 비교할 수 없다.
    인수인계 §5의 기준선(12편 정확일치)은 키 없는 조건에서 잰 값이다.
    """
    truth = {int(n) for n in FIGURE_MENTION.findall(markdown_text) if 1 <= int(n) <= 30}
    parents: set[int] = set()
    for figure in figures:
        # 서브피겨는 `parent_figure_num`으로 식별한다. 라벨 문자열에서 숫자를 뽑으면
        # 서브 접미사가 숫자인 경우("Fig. 12"의 자식이 "Fig. 121")를 부모 121로 오인한다.
        if figure.get("parent_figure_num"):
            continue
        match = re.search(r"(\d+)", str(figure.get("figure_num") or ""))
        if match:
            parents.add(int(match.group(1)))
    return {
        "truth_count": len(truth),
        "extracted_count": len(parents),
        "missing": sorted(truth - parents),
        "extra": sorted(parents - truth),
        "error": len(truth - parents) + len(parents - truth),
        "exact": truth == parents,
        "labels": sorted({figure["figure_num"] for figure in figures}),
    }


def candidate_diagnostics(
    manifest: dict[str, Any], candidates: list[dict[str, Any]], gold: dict[str, Any]
) -> dict[str, Any]:
    """결정적 lane 진단 — gold 캡션이 캡션으로 인정됐는지, 그 캡션에 후보가 붙었는지."""
    captions: dict[str, dict[str, Any]] = {}
    for page in manifest.get("pages", []) or []:
        for block in page.get("caption_blocks", []) or []:
            captions[str(block.get("id"))] = block
    for caption in manifest.get("captions", []) or []:
        captions.setdefault(str(caption.get("id")), caption)

    linked_ids = {candidate.get("best_caption_id") for candidate in candidates}
    pages_with_candidates = {candidate.get("page_number") for candidate in candidates}

    rows = []
    for evidence in gold.get("evidence", []):
        number = evidence["number"]
        recognized_as_table = False
        has_linked_candidate = False
        for caption_id, block in captions.items():
            matched = match_table_label(normalize(str(block.get("text") or "")))
            if not matched or matched[1] != number:
                continue
            if block.get("kind") == "table":
                recognized_as_table = True
            if caption_id in linked_ids:
                has_linked_candidate = True
        rows.append(
            {
                "label": evidence["label"],
                "page": evidence.get("page"),
                "caption_recognized": recognized_as_table,
                "candidate_linked": has_linked_candidate,
                "page_has_candidate": evidence.get("page") in pages_with_candidates,
            }
        )

    total = len(rows) or 1
    return {
        "gold_rows": rows,
        "caption_recognition_rate": sum(1 for r in rows if r["caption_recognized"]) / total,
        "candidate_link_rate": sum(1 for r in rows if r["candidate_linked"]) / total,
        "page_coverage_rate": sum(1 for r in rows if r["page_has_candidate"]) / total,
        "candidate_count": len(candidates),
        "candidate_source_kinds": dict(Counter(c.get("source_kind") for c in candidates)),
        "candidates_without_caption": sum(1 for c in candidates if not c.get("best_caption_id")),
    }


# ──────────────────────────────────────────────────────────────────────────────
# lane 실행
# ──────────────────────────────────────────────────────────────────────────────


async def load_production_key(provider: str = "gemini") -> bool:
    """DB에서 VLM 키를 읽어 환경변수에 넣는다.

    `worker=True`가 필수다. worker=False는 credential store 락을 잡고 사용자 DB에
    마이그레이션 UPDATE를 친다 — 측정 하네스가 사용자 데이터를 건드리면 안 된다.
    `worker=True`는 넘겨받은 settings를 복호화해 환경변수에 넣는 것이 전부다(DB 접근 없음).

    DB는 `init_db()` 대신 **읽기 전용 sqlite 연결**로 연다. init_db는 스키마 마이그레이션을
    수행할 수 있어 측정이 사용자 DB를 바꿀 위험이 있다.
    """
    import sqlite3

    from models.database import DB_PATH
    from services.api_key_runtime import load_api_keys_from_settings
    from services.provider_state import key_env_for

    # 라이브러리 12편은 개발 DB(backend/library) 쪽인데, 개발 DB의 *_api_key는 비어
    # 있고 실제 키는 패키지 앱 DB에만 들어 있다. 키만 그쪽에서 읽는다(읽기 전용).
    candidates = [DB_PATH, Path.home() / "Library" / "Application Support" / "sasoo" / "sasoo.db"]
    env_var = key_env_for(provider)
    for db_path in candidates:
        if not db_path.exists():
            continue
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT key, value FROM settings WHERE key IN ('gemini_api_key', 'openai_api_key')"
            ).fetchall()
        except sqlite3.OperationalError:
            # 스키마가 없는 빈 db(개발 worktree의 껍데기 sasoo.db 등) — 다음 후보로 넘어간다.
            continue
        finally:
            connection.close()
        settings = {key: value for key, value in rows if value}
        if not settings:
            continue
        await load_api_keys_from_settings(settings, worker=True)
        if os.environ.get(env_var):
            print(f"[audit] {provider} 키 출처: {db_path}")
            return True
    return False


async def run_lane(
    lane: str, papers: list[Path], gold: dict, *, use_cache: bool, reparse: str | None = None
) -> dict[str, Any]:
    saved_key = os.environ.get("GEMINI_API_KEY")
    if lane == "deterministic":
        os.environ.pop("GEMINI_API_KEY", None)
    else:
        if not os.environ.get("GEMINI_API_KEY") and not await load_production_key():
            raise SystemExit("GEMINI_API_KEY를 DB에서 읽지 못했다 — production lane을 돌릴 수 없다.")

    results: dict[str, Any] = {}
    cache = VlmCache(enabled=use_cache and lane == "production")
    started = time.time()
    for paper_dir in papers:
        pdf_path = next(paper_dir.glob("*.pdf"))
        markdown_candidates = sorted(paper_dir.glob("*.odl-reference.md")) or sorted(
            p for p in paper_dir.glob("*.md") if not p.name.startswith(".")
        )
        markdown_text = markdown_candidates[0].read_text(encoding="utf-8", errors="ignore") if markdown_candidates else ""
        paper_gold = gold.get(paper_dir.name, {"labels": [], "numbers": [], "evidence": []})

        if reparse:
            # 저장된 매니페스트를 쓰지 않는다 — 스크래치를 먼저 만들고 페이지 비전
            # 파싱부터 다시 돌린다(래스터도 스크래치에 새로 생긴다).
            scratch = Path(tempfile.mkdtemp(prefix="tblaudit_"))
            manifest = await _reparse_manifest(pdf_path, scratch, reparse)
        else:
            manifest = prepare_manifest(paper_dir, pdf_path)
            scratch = make_scratch_dir(paper_dir, manifest, pdf_path)
        cache.install(hashlib.sha1(pdf_path.read_bytes()).hexdigest()[:16])
        try:
            outcome = await run_pipeline(manifest, pdf_path=pdf_path, scratch=scratch)
        finally:
            cache.restore()
            shutil.rmtree(scratch, ignore_errors=True)

        results[paper_dir.name] = {
            "tables": table_metrics(outcome["tables"], paper_gold["numbers"]),
            "figures": figure_metrics(outcome["figures"], markdown_text),
            "diagnostics": candidate_diagnostics(manifest, outcome["table_candidates"], paper_gold),
            "gold_labels": paper_gold["labels"],
            "table_rows": [
                {
                    "table_num": table.get("table_num"),
                    "page": table.get("page_number"),
                    "caption": (table.get("caption") or None) and str(table["caption"])[:80],
                    "parse_method": table.get("parse_method"),
                    "confidence": round(float(table.get("confidence") or 0), 3),
                }
                for table in outcome["tables"]
            ],
        }
    return {
        "lane": lane,
        "elapsed_sec": round(time.time() - started, 1),
        "vlm": {
            "calls": cache.calls,
            "cache_hits": cache.hits,
            "cache_misses": cache.misses,
            "grid_recovered": cache.successes,
        },
        "papers": results,
    }


def print_lane(report: dict[str, Any]) -> None:
    lane = report["lane"]
    print(f"\n{'=' * 118}\n[{lane}] {report['elapsed_sec']}s  VLM {report['vlm']}\n{'=' * 118}")
    print(
        f"{'논문':<46} {'gold':>4} {'표':>3} {'FP':>3} {'FN':>3} {'오차':>4} {'캡션연결':>8}  "
        f"{'그림(원문/추출)':>14}  후보"
    )
    table_error = figure_error = exact_tables = exact_figures = 0
    for name, item in report["papers"].items():
        tables, figures, diagnostics = item["tables"], item["figures"], item["diagnostics"]
        table_error += tables["error"]
        figure_error += figures["error"]
        exact_tables += int(tables["exact"])
        exact_figures += int(figures["exact"])
        print(
            f"{name[:45]:<46} {len(item['gold_labels']):>4} {tables['extracted_count']:>3} "
            f"{tables['fp']:>3} {tables['fn']:>3} {tables['error']:>4} "
            f"{tables['caption_linked']:>3}/{tables['extracted_count']:<4} "
            f"{figures['truth_count']:>6}/{figures['extracted_count']:<7} "
            f"{diagnostics['candidate_count']:>3}개(무캡션 {diagnostics['candidates_without_caption']}) "
            f"{'캡션인정 %.0f%% 후보연결 %.0f%%' % (diagnostics['caption_recognition_rate'] * 100, diagnostics['candidate_link_rate'] * 100) if item['gold_labels'] else ''}"
        )
    count = len(report["papers"])
    print(
        f"\n표: 총오차 {table_error}, 정확일치 {exact_tables}/{count}   |   "
        f"그림: 총오차 {figure_error}, 정확일치 {exact_figures}/{count}"
    )


async def main_async(args: argparse.Namespace) -> None:
    gold = load_gold()
    papers = iter_papers(args.papers, require_manifest=args.reparse is None)
    lanes = ["deterministic", "production"] if args.lane == "both" else [args.lane]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.reparse:
        from services.provider_state import key_env_for

        env_var = key_env_for(args.reparse)
        if not os.environ.get(env_var) and not await load_production_key(args.reparse):
            raise SystemExit(
                f"{env_var}를 DB에서 읽지 못했다 — --reparse {args.reparse}로는 측정을 시작할 수 없다."
            )

    for repeat in range(args.repeat):
        for lane in lanes:
            report = await run_lane(lane, papers, gold, use_cache=not args.no_cache, reparse=args.reparse)
            print_lane(report)
            suffix = f"_{repeat + 1}" if args.repeat > 1 else ""
            out_path = OUT_DIR / f"measure_{lane}{suffix}{args.tag}.json"
            out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"원장: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lane", choices=["deterministic", "production", "both"], default="both")
    parser.add_argument("--repeat", type=int, default=1, help="노이즈 바닥 측정용 반복 횟수")
    parser.add_argument("--no-cache", action="store_true", help="VLM 캐시를 끈다(노이즈 측정)")
    parser.add_argument(
        "--reparse",
        choices=["gemini", "openai"],
        default=None,
        help="저장된 매니페스트 대신 이 공급사의 비전 엔진으로 다시 파싱해 측정한다",
    )
    parser.add_argument("--papers", default=None, help="논문 이름 부분 문자열 필터")
    parser.add_argument("--tag", default="", help="원장 파일명 접미사")
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
