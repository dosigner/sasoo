"""
Sasoo - 논문 도해 생성 (PaperBanana 패키지 대체)

2단 파이프라인: Planner(Gemini 3.1-pro가 상세 기술서 작성) → Render(ImageProvider).
품질은 렌더 프롬프트가 아니라 Planner 기술서에서 나온다 — 배경 스타일, 색, 선 굵기,
아이콘 스타일, 라벨 텍스트까지 텍스트로 확정한 뒤 렌더러에는 실행만 시킨다.

동시성 규약 (2026-07-11 사고의 재발 방지):
  - 렌더는 asyncio.wait_for(run_pipeline_blocking(...), RENDER_TIMEOUT_S).
    스레드로 빼야 이벤트 루프가 살아 있고, 그래야 타임아웃 타이머도 실제로 발화한다.
    (PaperBanana는 루프 안에서 동기 호출을 해서 /health까지 죽었고, asyncio 타임아웃은
    루프가 막혀 영영 발화하지 못했다.)
  - 프로바이더의 HTTP 클라이언트는 반드시 "스레드 안에서, 동기 API로" 생성·사용한다.
    async 클라이언트를 스레드로 옮기면 원래 루프에 묶여 조용히 실패한다
    (analysis_routes의 옛 주석에 기록된 실전 사례).
  - 렌더는 asyncio 기본 풀이 아니라 PIPELINE_EXECUTOR에서, RENDER_SEM 슬롯을 잡고 돈다.
    기본 풀을 쓰면 시각화 팬아웃이 풀을 채워 채팅 SSE가 스레드를 못 잡고 무한 대기한다.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from services.concurrency import RENDER_SEM, run_pipeline_blocking
from services.model_registry import resolve as resolve_model
from services.models import MODEL_IMAGE, MODEL_IMAGE_OPENAI
from services.pricing import calc_image_cost

logger = logging.getLogger(__name__)

RENDER_TIMEOUT_S = 180.0
HTTP_TIMEOUT_S = 120.0
IMAGE_SIZE = "1536x1024"


@dataclass
class FigureGenResult:
    path: Optional[str]
    provider: Optional[str]
    duration_s: float
    cost_usd: float
    error: Optional[str]


# ---------------------------------------------------------------------------
# [1] Planner
# ---------------------------------------------------------------------------

_PLANNER_SYSTEM = (
    "You are a scientific illustration planner. Turn the request into ONE "
    "detailed, unambiguous image description in English. Specify: overall "
    "layout, background style, color palette, line weight, icon style, and "
    "the EXACT text of every label (short English labels). Vague wording "
    "makes the figure worse — decide everything yourself. Do NOT include a "
    "figure title or caption inside the image."
)


async def _plan_description(viz_target: dict, *, llm_provider: str = "gemini") -> str:
    """텍스트 LLM(기본 Gemini 3.1-pro)으로 렌더러에 넘길 상세 기술서를 만든다.

    llm_provider는 이 기술서를 쓰는 텍스트 모델의 provider다 — 아래 render 단계의
    이미지 provider(preferred_provider, image_provider 설정)와는 다른 축이다.
    """
    from services.llm.interactions_client import call_interaction

    prompt = (
        f"Illustration request:\n"
        f"Title: {viz_target.get('title', '')}\n"
        f"Category: {viz_target.get('category', 'conceptual_illustration')}\n"
        f"Context:\n{viz_target.get('description', '')[:6000]}\n\n"
        "Write the final image description now."
    )
    _choice = resolve_model("viz_image_plan", llm_provider)
    result = await call_interaction(
        prompt,
        lane="pipeline",
        model=_choice.model,
        system_instruction=_PLANNER_SYSTEM,
        thinking_level=_choice.effort,
        store=False,
    )
    return str(result.get("text", "")).strip()


# ---------------------------------------------------------------------------
# [2] Render providers (동기 — 항상 to_thread 안에서 호출된다)
# ---------------------------------------------------------------------------

class ImageProvider(Protocol):
    name: str
    cost_key: str

    def available(self) -> bool: ...
    def generate(self, description: str) -> bytes: ...


_RENDER_INSTRUCTION = (
    "Render an image based on the following detailed description. "
    "Do not include figure titles in the image.\n\n"
)


class OpenAIImageProvider:
    name = "openai"

    def __init__(self, quality: str = "high") -> None:
        self._quality = quality
        self.cost_key = f"{MODEL_IMAGE_OPENAI}:{quality}"

    def available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))

    def generate(self, description: str) -> bytes:
        import httpx  # google-genai의 전이 의존성 — 스레드 안에서 동기 사용

        resp = httpx.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={
                "model": MODEL_IMAGE_OPENAI,
                "prompt": _RENDER_INSTRUCTION + description,
                "size": IMAGE_SIZE,
                "quality": self._quality,
            },
            timeout=HTTP_TIMEOUT_S,
        )
        resp.raise_for_status()
        b64 = resp.json()["data"][0]["b64_json"]
        return base64.b64decode(b64)


class GeminiImageProvider:
    name = "gemini"
    cost_key = MODEL_IMAGE

    def available(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY"))

    def generate(self, description: str) -> bytes:
        # 클라이언트를 스레드 안에서 생성한다 (모듈 docstring의 동시성 규약).
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=int(HTTP_TIMEOUT_S * 1000)),
        )
        response = client.models.generate_content(
            model=MODEL_IMAGE,
            contents=_RENDER_INSTRUCTION + description,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )
        for candidate in response.candidates or []:
            for part in (candidate.content.parts or []) if candidate.content else []:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data
        raise RuntimeError("Gemini returned no image data (text-only response)")


def build_providers(preferred: str, quality: str) -> list:
    """선호 프로바이더를 앞에 둔 폴백 순서."""
    openai: ImageProvider = OpenAIImageProvider(quality=quality)
    gemini: ImageProvider = GeminiImageProvider()
    return [gemini, openai] if preferred == "gemini" else [openai, gemini]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _safe_filename(title: str) -> str:
    safe = re.sub(r"[^\w\s가-힣-]", "", title).strip()
    safe = re.sub(r"[-\s]+", "_", safe)
    return (safe or "illustration")[:80]


async def generate_illustration(
    viz_target: dict,
    paper_dir: str,
    *,
    preferred_provider: str = "openai",
    quality: str = "high",
    llm_provider: str = "gemini",
) -> FigureGenResult:
    """도해 1건 생성. 실패해도 예외를 던지지 않고 error가 담긴 결과를 돌려준다.

    preferred_provider/quality는 렌더(이미지 생성) 단계의 provider·품질이고,
    llm_provider는 플래너(기술서 작성) 단계의 텍스트 LLM provider다 — 서로
    독립적으로 결정된다(예: 텍스트는 openai, 이미지는 gemini 조합도 유효).
    """
    start = time.monotonic()

    try:
        description = await _plan_description(viz_target, llm_provider=llm_provider)
    except Exception as exc:
        logger.warning("figure_gen planner failed for '%s': %s", viz_target.get("title"), exc)
        return FigureGenResult(None, None, round(time.monotonic() - start, 1), 0.0, f"planner: {exc}")

    errors: list[str] = []
    for provider in build_providers(preferred_provider, quality):
        if not provider.available():
            logger.info("figure_gen: provider %s unavailable (no key), skipping", provider.name)
            continue
        try:
            # The slot is taken outside wait_for so time spent queueing for a
            # render is not charged against the provider's own timeout.
            async with RENDER_SEM:
                png = await asyncio.wait_for(
                    run_pipeline_blocking(provider.generate, description),
                    timeout=RENDER_TIMEOUT_S,
                )
        except asyncio.TimeoutError:
            errors.append(f"{provider.name}: timeout after {RENDER_TIMEOUT_S:.0f}s")
            logger.warning("figure_gen: %s timed out for '%s'", provider.name, viz_target.get("title"))
            continue
        except Exception as exc:
            errors.append(f"{provider.name}: {exc}")
            logger.warning("figure_gen: %s failed for '%s': %s", provider.name, viz_target.get("title"), exc)
            continue

        out_dir = Path(paper_dir) / "paperbanana"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{_safe_filename(viz_target.get('title', 'illustration'))}.png"
        out_path.write_bytes(png)
        return FigureGenResult(
            path=str(out_path),
            provider=provider.name,
            duration_s=round(time.monotonic() - start, 1),
            cost_usd=calc_image_cost(provider.cost_key),
            error=None,
        )

    return FigureGenResult(
        None, None, round(time.monotonic() - start, 1), 0.0,
        "; ".join(errors) or "no image provider configured",
    )
