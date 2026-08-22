"""S3 — 캡션 폴백 후보의 VLM 격자 복원 성공률을 단건으로 측정한다.

`_repair_with_vlm`은 예외를 삼켜 실패가 빈 grid로 둔갑한다(로그는 넣었지만 원문 응답까지
남기지는 않는다). 여기서는 같은 입력을 직접 만들어 호출하고 **예외와 원문 응답을 그대로
노출**한다. 그러지 않으면 H2b(프롬프트 조건부) / H2c(전체 페이지 raster) / H2d(밴드가
표를 안 덮음)를 구분할 수 없다.

실행:
    cd sasoo/backend && .venv/bin/python -m tools.extraction_audit.vlm_probe 2013_IEEETIP
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api.analysis_helpers import _clean_llm_json  # noqa: E402
from services.llm.interactions_client import call_interaction  # noqa: E402
from services.models import MODEL_FLASH_HQ  # noqa: E402
from services.table_candidates import build_table_candidates  # noqa: E402
from services.table_resolver import _has_meaningful_grid, _normalize_grid  # noqa: E402
from tools.extraction_audit.measure import (  # noqa: E402
    LIBRARY,
    load_production_key,
    make_scratch_dir,
    prepare_manifest,
)

OUT = Path(__file__).resolve().parent / "_out" / "vlm_probe"


async def probe_candidate(candidate: dict, manifest: dict, paper_dir: Path, *, mode: str) -> dict:
    """mode='page'는 현재 코드와 같은 입력(전체 페이지 raster), 'crop'은 bbox 크롭을 준다."""
    page = next((p for p in manifest["pages"] if p["page_number"] == candidate["page_number"]), None)
    if page is None:
        return {"mode": mode, "error": "page_not_found"}

    if mode == "page":
        image_bytes = (paper_dir / page["raster_path"]).resolve().read_bytes()
        prompt = {
            "task": "Repair a scientific table grid only when headers are merged, borderless, or multiline. Preserve rows and columns.",
            "bbox": candidate.get("bbox"),
            "existing_grid": candidate.get("text_grid"),
            "response_format": {"rows": [["cell"]], "confidence": "0.0-1.0"},
        }
    else:
        image_bytes = _crop_bytes(paper_dir, candidate)
        prompt = {
            "task": "Extract the table in this image as a grid. The image is already cropped to the table region.",
            "existing_grid": candidate.get("text_grid"),
            "response_format": {"rows": [["cell"]], "confidence": "0.0-1.0"},
        }

    try:
        result = await call_interaction(
            [
                {"type": "image", "data": base64.b64encode(image_bytes).decode("ascii"), "mime_type": "image/png"},
                {"type": "text", "text": json.dumps(prompt, ensure_ascii=False)},
            ],
            lane="pipeline",
            model=MODEL_FLASH_HQ,
            # 3.7 Flash는 minimal을 거부한다(400). low가 이 모델의 최저치다.
            thinking_level="low",
            store=False,
        )
    except Exception as exc:  # 진단에서는 예외를 반드시 노출한다
        return {"mode": mode, "error": f"{type(exc).__name__}: {exc}"}

    raw = result["text"]
    try:
        payload = json.loads(_clean_llm_json(raw))
    except Exception as exc:
        return {"mode": mode, "error": f"parse: {type(exc).__name__}: {exc}", "raw": raw[:400]}
    grid = _normalize_grid(payload.get("rows"))
    return {
        "mode": mode,
        "rows": len(grid),
        "cols": max((len(r) for r in grid), default=0),
        "meaningful": _has_meaningful_grid(grid),
        "confidence": payload.get("confidence"),
        "raw": raw[:300],
    }


def _crop_bytes(paper_dir: Path, candidate: dict) -> bytes:
    pdf_path = next((paper_dir / "..").resolve().glob("*.pdf"), None)
    raise RuntimeError("crop 모드는 pdf 경로가 필요하다 — main()에서 주입한다")


async def main_async(needle: str) -> None:
    if not await load_production_key():
        raise SystemExit("GEMINI_API_KEY를 읽지 못했다")
    OUT.mkdir(parents=True, exist_ok=True)

    for paper_dir in sorted(LIBRARY.iterdir()):
        if not (paper_dir / ".odl_manifest.json").exists() or needle.lower() not in paper_dir.name.lower():
            continue
        pdf_path = next(paper_dir.glob("*.pdf"))
        manifest = prepare_manifest(paper_dir, pdf_path)
        scratch = make_scratch_dir(paper_dir, manifest, pdf_path)
        candidates = [
            candidate
            for candidate in build_table_candidates(manifest, pdf_path=pdf_path, paper_dir=scratch)
            if candidate["source_kind"] == "caption_fallback_crop"
        ]
        print(f"\n=== {paper_dir.name}  캡션 폴백 후보 {len(candidates)}개")

        document = fitz.open(str(pdf_path))
        for candidate in candidates:
            page = document[candidate["page_number"] - 1]
            page_height = float(page.rect.height)
            x0, y_bottom, x1, y_top = candidate["bbox"]
            rect = fitz.Rect(x0, page_height - y_top, x1, page_height - y_bottom)
            crop_path = OUT / f"{paper_dir.name[:18]}_{candidate['id'].replace(':', '_')}.png"
            page.get_pixmap(dpi=150, clip=rect).save(str(crop_path))

            page_result = await probe_candidate(candidate, manifest, scratch, mode="page")
            crop_result = await _probe_with_crop(candidate, crop_path)
            print(f"  {candidate['id']}  p{candidate['page_number']}  cap={candidate['best_caption_id']}")
            print(f"    page 모드(현재 코드): {page_result}")
            print(f"    crop 모드          : {crop_result}")
            print(f"    크롭: {crop_path}")
        document.close()


async def _probe_with_crop(candidate: dict, crop_path: Path) -> dict:
    prompt = {
        "task": "Extract the table in this image as a grid. The image is already cropped to the table region.",
        "response_format": {"rows": [["cell"]], "confidence": "0.0-1.0"},
    }
    try:
        result = await call_interaction(
            [
                {
                    "type": "image",
                    "data": base64.b64encode(crop_path.read_bytes()).decode("ascii"),
                    "mime_type": "image/png",
                },
                {"type": "text", "text": json.dumps(prompt, ensure_ascii=False)},
            ],
            lane="pipeline",
            model=MODEL_FLASH_HQ,
            # 3.7 Flash는 minimal을 거부한다(400). low가 이 모델의 최저치다.
            thinking_level="low",
            store=False,
        )
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    try:
        payload = json.loads(_clean_llm_json(result["text"]))
    except Exception as exc:
        return {"error": f"parse: {type(exc).__name__}: {exc}", "raw": result["text"][:300]}
    grid = _normalize_grid(payload.get("rows"))
    return {
        "rows": len(grid),
        "cols": max((len(r) for r in grid), default=0),
        "meaningful": _has_meaningful_grid(grid),
        "confidence": payload.get("confidence"),
    }


if __name__ == "__main__":
    asyncio.run(main_async(sys.argv[1] if len(sys.argv) > 1 else ""))
