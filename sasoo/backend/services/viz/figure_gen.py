"""
Sasoo - 논문 도해 생성 (PaperBanana 패키지 대체)

Two stages: plan with a text model, then render with the chosen image model.
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
from services.models import MODEL_IMAGE, MODEL_IMAGE_OPENAI, MODEL_IMAGE_SUNBURST
from services.pricing import PricingUsageError, calc_image_cost

logger = logging.getLogger(__name__)

RENDER_TIMEOUT_S = 180.0
HTTP_TIMEOUT_S = 120.0
IMAGE_SIZE = "1536x1024"
GEMINI_IMAGE_SIZE = "1K"
GEMINI_IMAGE_ASPECT_RATIO = "3:2"
GEMINI_IMAGE_THINKING = "minimal"


@dataclass
class FigureGenResult:
    path: Optional[str]
    provider: Optional[str]
    duration_s: float
    cost_usd: float | None
    error: Optional[str]


# ---------------------------------------------------------------------------
# [1] Planner
# ---------------------------------------------------------------------------

_TYPOGRAPHY_INSTRUCTION = (
    "Typography: use a normal-width sans-serif such as Arial or Helvetica, "
    "with natural character proportions and normal letter spacing. Never use "
    "condensed, narrow, compressed, or horizontally scaled lettering. "
    "At 1536x1024, keep labels at least 28 px tall, with generous padding and "
    "clear separation from arrows and diagram edges. Reserve space for text "
    "before arranging the graphics. Prefer short labels; preserve all required "
    "wording, symbols, and units. Wrap long labels at word boundaries onto "
    "multiple lines or widen their panels. Never squeeze or shrink text to fit. "
    "Simplify decorative graphics if space is tight."
)
_GEMINI_TYPOGRAPHY_INSTRUCTION = _TYPOGRAPHY_INSTRUCTION.replace(
    "At 1536x1024", "At 1K 3:2 resolution"
)

_PLANNER_SYSTEM = (
    "You are a scientific illustration planner. Turn the request into ONE "
    "detailed, unambiguous image description in English. Specify: overall "
    "layout, background style, color palette, line weight, icon style, and "
    "the EXACT text of every label (short English labels). Vague wording "
    "makes the figure worse — decide everything yourself. Do NOT include a "
    "figure title or caption inside the image. Use only supplied scientific "
    "facts. Never invent numerical results, performance curves, or equipment. "
    "Use context to check facts, not as a list of content to draw. For structure "
    "images, focus on components and connections; omit result plots and "
    "baseline comparisons unless the request explicitly asks for them. "
    "Do not draw quantitative plots or introduce equations unless explicitly "
    "requested. Supplied formulas are context, not instructions to draw axes. "
    "For state snapshots, use pictorial states and short labels, not time plots. "
    "For process images, show the SAME input changing across 3-5 numbered panels. "
    "For comparisons, use aligned baseline and proposed panels with matching "
    "scales and highlight only supported differences.\n\n" + _TYPOGRAPHY_INSTRUCTION
)


async def _plan_description(viz_target: dict, *, llm_provider: str = "gemini") -> str:
    """Build the image description with the selected provider's text model."""
    from services.llm.interactions_client import call_interaction

    prompt = (
        f"Illustration request:\n"
        f"Title: {viz_target.get('title', '')}\n"
        f"Category: {viz_target.get('category', 'conceptual_illustration')}\n"
        f"Purpose: {viz_target.get('diagram_type', 'structure')}\n"
        f"Context:\n{viz_target.get('description', '')[:6000]}\n\n"
        "Write the final image description now."
    )
    _choice = resolve_model("viz_image_plan", llm_provider)
    result = await call_interaction(
        prompt,
        lane="pipeline",
        model=_choice.model,
        system_instruction=(
            _PLANNER_SYSTEM.replace(_TYPOGRAPHY_INSTRUCTION, _GEMINI_TYPOGRAPHY_INSTRUCTION)
            if llm_provider == "gemini" else _PLANNER_SYSTEM
        ),
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

    def __init__(self, quality: str = "high", model: str = MODEL_IMAGE_OPENAI) -> None:
        if model not in {MODEL_IMAGE_OPENAI, MODEL_IMAGE_SUNBURST}:
            raise ValueError(f"Unsupported image model: {model}")
        self._quality = quality
        self._model = model
        self.cost_key = f"{model}:{quality}"
        self.usage: dict | None = None

    def available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))

    def generate(self, description: str) -> bytes:
        import httpx  # google-genai의 전이 의존성 — 스레드 안에서 동기 사용

        resp = httpx.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={
                "model": self._model,
                "prompt": _RENDER_INSTRUCTION + description + "\n\n" + _TYPOGRAPHY_INSTRUCTION,
                "size": IMAGE_SIZE,
                "quality": self._quality,
                "output_format": "png",
            },
            timeout=HTTP_TIMEOUT_S,
        )
        resp.raise_for_status()
        payload = resp.json()
        self.usage = payload.get("usage")
        b64 = payload["data"][0]["b64_json"]
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
        interaction = client.interactions.create(
            model=MODEL_IMAGE,
            input=_RENDER_INSTRUCTION + description + "\n\n" + _GEMINI_TYPOGRAPHY_INSTRUCTION,
            response_format={
                "type": "image",
                "mime_type": "image/png",
                "aspect_ratio": GEMINI_IMAGE_ASPECT_RATIO,
                "image_size": GEMINI_IMAGE_SIZE,
            },
            generation_config={"thinking_level": GEMINI_IMAGE_THINKING},
            store=False,
        )
        self.usage = interaction.usage.model_dump(exclude_none=True) if interaction.usage else None
        if interaction.status != "completed" or not interaction.output_image or not interaction.output_image.data:
            raise RuntimeError(f"Gemini image interaction ended without an image ({interaction.status})")
        png = base64.b64decode(interaction.output_image.data, validate=True)
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Gemini image response is not PNG")
        return png


def build_providers(preferred: str, quality: str, image_model: str | None = None) -> list:
    """Use the selected provider for this render request."""
    if preferred == "gemini":
        return [GeminiImageProvider()]
    return [OpenAIImageProvider(quality=quality, model=image_model or MODEL_IMAGE_OPENAI)]


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
    llm_provider: str | None = None,
    image_model: str | None = None,
) -> FigureGenResult:
    """Generate one figure and return an error result on failure.

    The planner and renderer use the same provider by default.
    """
    start = time.monotonic()
    llm_provider = llm_provider or preferred_provider

    try:
        description = await _plan_description(viz_target, llm_provider=llm_provider)
    except Exception as exc:
        logger.warning("figure_gen planner failed for '%s': %s", viz_target.get("title"), exc)
        return FigureGenResult(None, None, round(time.monotonic() - start, 1), 0.0, f"planner: {exc}")

    errors: list[str] = []
    for provider in build_providers(preferred_provider, quality, image_model):
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
        prefix = f"{viz_target['id']}_" if viz_target.get("id") is not None else ""
        filename = _safe_filename(viz_target.get("title", "illustration"))
        if image_model:
            # Keep model changes from overwriting or reusing a cached image URL.
            prefix += f"{_safe_filename(image_model)}_{quality}_"
            filename = filename[:40]  # Leave room for the prefix with UTF-8 titles.
        out_path = out_dir / f"{prefix}{filename}.png"
        out_path.write_bytes(png)
        try:
            cost = calc_image_cost(provider.cost_key, usage=getattr(provider, "usage", None))
        except PricingUsageError as exc:
            # Keep a successful image even when the provider omits billing usage.
            logger.warning("figure_gen: %s cost unavailable: %s", provider.name, exc)
            cost = None
        return FigureGenResult(
            path=str(out_path),
            provider=provider.name,
            duration_s=round(time.monotonic() - start, 1),
            cost_usd=cost,
            error=None,
        )

    return FigureGenResult(
        None, None, round(time.monotonic() - start, 1), 0.0,
        "; ".join(errors) or "no image provider configured",
    )
