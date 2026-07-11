# figure_gen (PaperBanana 대체) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PaperBanana 패키지를 자체 2단 파이프라인(Gemini Planner → gpt-image-2/Nano Banana 2 렌더)으로 교체하고, 이미지 생성이 이벤트 루프를 블로킹하던 결함을 제거한다.

**Architecture:** 새 모듈 `services/viz/figure_gen.py` 하나가 Planner(Gemini 3.1-pro 상세 기술서)와 ImageProvider 프로토콜(OpenAI/Gemini, 자동 폴백)을 담는다. 렌더는 `asyncio.wait_for(asyncio.to_thread(...), 180)` — 동기 클라이언트를 **스레드 안에서 생성**해야 한다(과거 async 클라이언트를 to_thread로 옮겼다가 조용히 실패한 전례가 analysis_routes.py 주석에 있음). 시각화 항목은 하나 끝날 때마다 DB에 upsert한다.

**Tech Stack:** Python 3.14 / FastAPI / google-genai(동기 API) / httpx(동기, google-genai의 기존 전이 의존성) / pytest

**작업 디렉터리:** `/Users/dongj/dev/논문_사수_개발중/sasoo/backend` (테스트: `.venv/bin/python -m pytest`)
**프론트엔드:** `/Users/dongj/dev/논문_사수_개발중/sasoo/frontend` (검증: `pnpm exec tsc --noEmit`)
**커밋 위치:** 저장소 루트는 `/Users/dongj/dev/논문_사수_개발중` (sasoo/ 프리픽스로 add)

## Global Constraints

- 모델 ID는 `services/models.py` 상수만 사용. 이미지 모델: `MODEL_IMAGE = "gemini-3.1-flash-image"`로 **변경**(Nano Banana 2), OpenAI는 `"gpt-image-2"`.
- gpt-image-2 기본 quality `"high"`, size `"1536x1024"`. 단가: low $0.005 / medium $0.041 / high $0.165 (1536x1024 기준).
- 저장 경로 `{paper_dir}/paperbanana/` 유지 (프론트 URL 호환). `get_paperbanana_dir`도 유지.
- 렌더 타임아웃 180초. 프로바이더 HTTP 타임아웃 120초.
- 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- `paperbanana_profile` 설정/UI는 이번 범위에서 건드리지 않는다 (후속).
- 기존 테스트가 깨지면 안 됨: 시작 전 75 passed 상태.

---

### Task 1: pricing에 gpt-image-2 단가 추가

**Files:**
- Modify: `sasoo/backend/services/pricing.py`
- Test: `sasoo/backend/services/test_pricing_images.py` (신규)

**Interfaces:**
- Produces: `IMAGE_PRICING["gpt-image-2:high"] == 0.165` 등 quality별 키, `calc_image_cost("gpt-image-2:high") == 0.165`

- [ ] **Step 1: 실패하는 테스트 작성** — `services/test_pricing_images.py`:

```python
import unittest

from services.pricing import IMAGE_PRICING, calc_image_cost


class ImagePricingTests(unittest.TestCase):
    def test_gpt_image_2_quality_tiers(self):
        # 1536x1024 기준 공식 단가 (2026-07-11 developers.openai.com)
        self.assertEqual(IMAGE_PRICING["gpt-image-2:low"], 0.005)
        self.assertEqual(IMAGE_PRICING["gpt-image-2:medium"], 0.041)
        self.assertEqual(IMAGE_PRICING["gpt-image-2:high"], 0.165)

    def test_nano_banana_2(self):
        self.assertEqual(IMAGE_PRICING["gemini-3.1-flash-image"], 0.067)

    def test_calc_image_cost(self):
        self.assertEqual(calc_image_cost("gpt-image-2:high"), 0.165)
        self.assertEqual(calc_image_cost("gpt-image-2:high", 2), 0.33)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest services/test_pricing_images.py -q` → Expected: FAIL (KeyError `gpt-image-2:low`)

- [ ] **Step 3: 구현** — `pricing.py`의 `IMAGE_PRICING`에 3개 키 추가:

```python
# USD per generated image (1K-2K resolution).
IMAGE_PRICING: dict[str, float] = {
    "gemini-3-pro-image": 0.134,
    "gemini-3-pro-image-preview": 0.134,
    "gemini-3.1-flash-image": 0.067,
    "gemini-3.1-flash-image-preview": 0.067,
    # gpt-image-2, 1536x1024 (quality별 출력 토큰 차이로 장당 가격이 갈린다)
    "gpt-image-2:low": 0.005,
    "gpt-image-2:medium": 0.041,
    "gpt-image-2:high": 0.165,
}
```

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest services/test_pricing_images.py -q` → PASS
- [ ] **Step 5: 커밋** — `git add sasoo/backend/services/pricing.py sasoo/backend/services/test_pricing_images.py && git commit -m "feat(pricing): gpt-image-2 per-image quality tiers"`

---

### Task 2: figure_gen 코어 모듈

**Files:**
- Create: `sasoo/backend/services/viz/figure_gen.py`
- Modify: `sasoo/backend/services/models.py` (MODEL_IMAGE → Nano Banana 2)
- Test: `sasoo/backend/services/test_figure_gen.py` (신규)

**Interfaces:**
- Consumes: `services.llm.gemini_client.GeminiClient` (`_call`/`_response_text`), `services.models.MODEL_PRO`, `services.pricing.calc_image_cost`
- Produces (Task 4가 사용):
  - `@dataclass FigureGenResult: path: Optional[str]; provider: Optional[str]; duration_s: float; cost_usd: float; error: Optional[str]`
  - `async generate_illustration(viz_target: dict, paper_dir: str, *, preferred_provider: str = "openai", quality: str = "high") -> FigureGenResult`
  - `def build_providers(preferred: str, quality: str) -> list` (테스트/폴백 순서 노출용)

- [ ] **Step 1: models.py 변경** — `MODEL_IMAGE = "gemini-3-pro-image"` → 다음으로 교체:

```python
# Image generation
MODEL_IMAGE = "gemini-3.1-flash-image"   # Nano Banana 2 ($0.067/장)
MODEL_IMAGE_OPENAI = "gpt-image-2"
```

주석 블록의 IMAGE 설명("Nano Banana Pro ... published text-rendering error rate")을 다음으로 교체:

```python
#   IMAGE       - Nano Banana 2 as the Gemini-side renderer; gpt-image-2
#                 (Arena text-to-image #1) is the default. Provider choice and
#                 fallback live in services/viz/figure_gen.py.
```

- [ ] **Step 2: 실패하는 테스트 작성** — `services/test_figure_gen.py`:

```python
"""
figure_gen 테스트.

지키는 것: (1) 폴백 순서, (2) 타임아웃이 실제로 발화하고 그동안 이벤트 루프가
살아있음 — PaperBanana가 루프를 블로킹해 서버 전체가 죽던 2026-07-11 사고의 회귀 방지,
(3) 프로바이더 전무 시 에러 결과, (4) 파일명 안전성.
"""

import asyncio
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from services.viz import figure_gen
from services.viz.figure_gen import FigureGenResult, generate_illustration

PNG_1PX = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _FakeProvider:
    def __init__(self, name, *, ok=True, delay=0.0, unavailable=False):
        self.name = name
        self._ok = ok
        self._delay = delay
        self._unavailable = unavailable
        self.calls = 0
        self.cost_key = "gpt-image-2:high"

    def available(self):
        return not self._unavailable

    def generate(self, description):
        self.calls += 1
        if self._delay:
            time.sleep(self._delay)
        if not self._ok:
            raise RuntimeError(f"{self.name} boom")
        return PNG_1PX


def _target(title="개념도 테스트"):
    return {"title": title, "description": "레이저가 거울에 반사되는 개념도"}


class FigureGenTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.paper_dir = self._tmp.name
        # Planner는 전 테스트에서 스텁: 실제 Gemini 호출 금지
        self._plan = patch.object(
            figure_gen, "_plan_description",
            new=self._fake_plan,
        )
        self._plan.start()

    async def _fake_plan(self, viz_target):
        return "A minimal schematic: laser, mirror, labeled arrows."

    def tearDown(self):
        self._plan.stop()
        self._tmp.cleanup()

    async def test_success_saves_png_and_reports_provider(self):
        p = _FakeProvider("openai")
        with patch.object(figure_gen, "build_providers", return_value=[p]):
            r = await generate_illustration(_target(), self.paper_dir)
        self.assertIsNone(r.error)
        self.assertEqual(r.provider, "openai")
        self.assertTrue(Path(r.path).exists())
        self.assertTrue(Path(r.path).name.endswith(".png"))
        self.assertIn("paperbanana", Path(r.path).parts)

    async def test_fallback_when_first_provider_fails(self):
        bad = _FakeProvider("openai", ok=False)
        good = _FakeProvider("gemini")
        with patch.object(figure_gen, "build_providers", return_value=[bad, good]):
            r = await generate_illustration(_target(), self.paper_dir)
        self.assertEqual(r.provider, "gemini")
        self.assertEqual(bad.calls, 1)

    async def test_unavailable_provider_is_skipped_without_calling(self):
        nokey = _FakeProvider("openai", unavailable=True)
        good = _FakeProvider("gemini")
        with patch.object(figure_gen, "build_providers", return_value=[nokey, good]):
            r = await generate_illustration(_target(), self.paper_dir)
        self.assertEqual(r.provider, "gemini")
        self.assertEqual(nokey.calls, 0)

    async def test_all_providers_fail_returns_error_result(self):
        with patch.object(
            figure_gen, "build_providers",
            return_value=[_FakeProvider("openai", ok=False), _FakeProvider("gemini", ok=False)],
        ):
            r = await generate_illustration(_target(), self.paper_dir)
        self.assertIsNone(r.path)
        self.assertIsNone(r.provider)
        self.assertIn("boom", r.error)

    async def test_timeout_fires_and_loop_stays_alive(self):
        """느린 렌더 중에도 루프가 굴러가고, 타임아웃이 실제로 잘라야 한다."""
        slow = _FakeProvider("openai", delay=3.0)
        good = _FakeProvider("gemini")
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            for _ in range(20):
                await asyncio.sleep(0.05)
                ticks += 1

        with (
            patch.object(figure_gen, "build_providers", return_value=[slow, good]),
            patch.object(figure_gen, "RENDER_TIMEOUT_S", 0.5),
        ):
            hb = asyncio.create_task(heartbeat())
            r = await generate_illustration(_target(), self.paper_dir)
            await hb

        self.assertEqual(r.provider, "gemini")   # 타임아웃 후 폴백
        self.assertGreater(ticks, 5, "렌더 중 이벤트 루프가 멈춰 있었다")

    async def test_filename_is_sanitized(self):
        p = _FakeProvider("openai")
        with patch.object(figure_gen, "build_providers", return_value=[p]):
            r = await generate_illustration(
                _target(title='광학 테이블 <셋업>: "실험"/구성?'), self.paper_dir
            )
        name = Path(r.path).name
        for ch in '<>:"/\\?*':
            self.assertNotIn(ch, name)


class ProviderOrderTests(unittest.TestCase):
    def test_preferred_first(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "x", "GEMINI_API_KEY": "y"}):
            names = [p.name for p in figure_gen.build_providers("gemini", "high")]
        self.assertEqual(names, ["gemini", "openai"])

    def test_default_openai_first(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "x", "GEMINI_API_KEY": "y"}):
            names = [p.name for p in figure_gen.build_providers("openai", "high")]
        self.assertEqual(names, ["openai", "gemini"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 실패 확인** — Run: `.venv/bin/python -m pytest services/test_figure_gen.py -q` → FAIL (ModuleNotFoundError)

- [ ] **Step 4: 구현** — `services/viz/figure_gen.py` 전체:

```python
"""
Sasoo - 논문 도해 생성 (PaperBanana 패키지 대체)

2단 파이프라인: Planner(Gemini 3.1-pro가 상세 기술서 작성) → Render(ImageProvider).
품질은 렌더 프롬프트가 아니라 Planner 기술서에서 나온다 — 배경 스타일, 색, 선 굵기,
아이콘 스타일, 라벨 텍스트까지 텍스트로 확정한 뒤 렌더러에는 실행만 시킨다.

동시성 규약 (2026-07-11 사고의 재발 방지):
  - 렌더는 asyncio.wait_for(asyncio.to_thread(...), RENDER_TIMEOUT_S).
    스레드로 빼야 이벤트 루프가 살아 있고, 그래야 타임아웃 타이머도 실제로 발화한다.
    (PaperBanana는 루프 안에서 동기 호출을 해서 /health까지 죽었고, asyncio 타임아웃은
    루프가 막혀 영영 발화하지 못했다.)
  - 프로바이더의 HTTP 클라이언트는 반드시 "스레드 안에서, 동기 API로" 생성·사용한다.
    async 클라이언트를 스레드로 옮기면 원래 루프에 묶여 조용히 실패한다
    (analysis_routes의 옛 주석에 기록된 실전 사례).
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

from services.models import MODEL_IMAGE, MODEL_IMAGE_OPENAI, MODEL_PRO
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


async def _plan_description(viz_target: dict) -> str:
    """Gemini 3.1-pro로 렌더러에 넘길 상세 기술서를 만든다."""
    from services.llm.gemini_client import GeminiClient

    client = GeminiClient()
    prompt = (
        f"Illustration request:\n"
        f"Title: {viz_target.get('title', '')}\n"
        f"Category: {viz_target.get('category', 'conceptual_illustration')}\n"
        f"Context:\n{viz_target.get('description', '')[:6000]}\n\n"
        "Write the final image description now."
    )
    response = await client._call(
        model=MODEL_PRO,
        contents=prompt,
        system_instruction=_PLANNER_SYSTEM,
        thinking_level="medium",
        phase="figure_planner",
    )
    return client._response_text(response).strip()


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
) -> FigureGenResult:
    """도해 1건 생성. 실패해도 예외를 던지지 않고 error가 담긴 결과를 돌려준다."""
    start = time.monotonic()

    try:
        description = await _plan_description(viz_target)
    except Exception as exc:
        logger.warning("figure_gen planner failed for '%s': %s", viz_target.get("title"), exc)
        return FigureGenResult(None, None, time.monotonic() - start, 0.0, f"planner: {exc}")

    errors: list[str] = []
    for provider in build_providers(preferred_provider, quality):
        if not provider.available():
            logger.info("figure_gen: provider %s unavailable (no key), skipping", provider.name)
            continue
        try:
            png = await asyncio.wait_for(
                asyncio.to_thread(provider.generate, description),
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
```

- [ ] **Step 5: 통과 확인** — Run: `.venv/bin/python -m pytest services/test_figure_gen.py services/test_pricing_images.py -q` → 전부 PASS. `calc_image_cost`의 기본 폴백 키가 `gemini-3.1-flash-image`인지 확인(기존 코드 그대로면 OK).
- [ ] **Step 6: 전체 테스트** — `.venv/bin/python -m pytest -q` → 기존 75 + 신규 전부 PASS
- [ ] **Step 7: 커밋** — `git commit -m "feat(viz): figure_gen two-stage pipeline with provider fallback"`

---

### Task 3: OpenAI 키·이미지 설정 플러밍 (백엔드)

**Files:**
- Modify: `sasoo/backend/api/settings.py`, `sasoo/backend/models/schemas.py`, `sasoo/backend/main.py`

**Interfaces:**
- Produces: 설정 키 `openai_api_key`(암호화), `image_provider`("openai"|"gemini", 기본 "openai"), `image_quality`("low"|"medium"|"high", 기본 "high"); env `OPENAI_API_KEY`; `SettingsModel.openai_api_key/openai_key_unreadable/image_provider/image_quality`

- [ ] **Step 1: settings.py 수정** (4곳)

`DEFAULT_SETTINGS`에 추가:
```python
    "openai_api_key": "",
    "image_provider": "openai",
    "image_quality": "high",
```

`_API_KEY_FIELDS = {"gemini_api_key"}` → `_API_KEY_FIELDS = {"gemini_api_key", "openai_api_key"}`

`get_settings()`의 `return SettingsModel(` 안에 추가 (gemini_key_unreadable 줄 뒤):
```python
        openai_api_key=_mask_api_key(raw.get("openai_api_key", "")),
        openai_key_unreadable="openai_api_key" in unreadable,
        image_provider=raw.get("image_provider", "openai"),
        image_quality=raw.get("image_quality", "high"),
```

`update_settings()`의 gemini env 동기화 블록 아래에 추가:
```python
    if "openai_api_key" in update_data and update_data["openai_api_key"]:
        os.environ["OPENAI_API_KEY"] = update_data["openai_api_key"]
```

`check_api_keys()` 반환 dict에 추가:
```python
        "openai": {
            "configured": bool(raw.get("openai_api_key", "")),
            "masked": _mask_api_key(raw.get("openai_api_key", "")),
            "unreadable": "openai_api_key" in unreadable,
        },
```

- [ ] **Step 2: schemas.py 수정** — `SettingsModel`의 `gemini_key_unreadable` 아래:
```python
    openai_api_key: Optional[str] = None
    openai_key_unreadable: bool = False
    image_provider: str = "openai"      # openai | gemini
    image_quality: str = "high"         # low | medium | high
```
`SettingsUpdate`의 `gemini_api_key` 아래:
```python
    openai_api_key: Optional[str] = None
    image_provider: Optional[str] = None
    image_quality: Optional[str] = None
```

- [ ] **Step 3: main.py 기동 로딩** — 기존 gemini 키 로딩 블록을 두 키로 확장:
```python
        rows = await fetch_all("SELECT key, value FROM settings WHERE key IN ('gemini_api_key', 'openai_api_key')")
        env_names = {"gemini_api_key": "GEMINI_API_KEY", "openai_api_key": "OPENAI_API_KEY"}
        for row in rows:
            if row["value"]:
                decrypted = decrypt_value(row["value"])
                if decrypted:
                    os.environ[env_names[row["key"]]] = decrypted
        print("[Sasoo] API keys loaded from database into environment.")
```

- [ ] **Step 4: 검증** — `.venv/bin/python -m pytest -q` 전부 PASS + `.venv/bin/python -c "import sys; sys.path.insert(0,'.'); import main, api.settings" ` OK
- [ ] **Step 5: 커밋** — `git commit -m "feat(settings): OpenAI API key and image provider/quality settings"`

---

### Task 4: 호출부 교체 + 항목별 즉시 저장 + 기동 복구

**Files:**
- Modify: `sasoo/backend/api/analysis_routes.py` (`_generate_single_paperbanana` 본문, viz 저장 루프), `sasoo/backend/main.py` (기동 복구)

**Interfaces:**
- Consumes: Task 2의 `generate_illustration`, Task 3의 설정 키
- Produces: 시각화 항목이 완료될 때마다 `analysis_results`의 `visualization` 행이 갱신됨

- [ ] **Step 1: `_generate_single_paperbanana` 교체** — 함수 본문에서 "Try using the PaperBanana bridge" try/except 블록(옛 to_thread 실패 주석 포함)과 "Fallback: Generate with PIL" 이하 PIL 블록 전체를 삭제하고 다음으로 교체 (enriched_item 조립부는 유지):

```python
    from services.viz.figure_gen import generate_illustration
    from api.settings import _get_all_settings

    settings = await _get_all_settings()
    result = await generate_illustration(
        enriched_item,
        str(get_paper_dir(folder_name)),
        preferred_provider=settings.get("image_provider", "openai"),
        quality=settings.get("image_quality", "high"),
    )
    if result.path:
        url = f"/static/library/{folder_name}/paperbanana/{Path(result.path).name}"
        _logger.info(
            "figure_gen ok '%s' via %s in %.1fs ($%.3f)",
            title, result.provider, result.duration_s, result.cost_usd,
        )
        return {
            "image_path": result.path,
            "image_url": url,
            "provider": result.provider,
            "duration_s": result.duration_s,
            "cost_usd": result.cost_usd,
        }
    _logger.warning("figure_gen failed for '%s': %s", title, result.error)
    return {"error": result.error or "generation failed"}
```

주의: 이 함수의 기존 반환 계약(성공 시 `image_path`/`image_url` dict, 실패 시 에러 표시)을 호출부 `generate_one`이 어떻게 소비하는지 먼저 읽고, 실패 시 기존 형태(예: `{"error": ...}` 또는 status 필드)에 맞춰라. PIL 폴백은 실패를 가리는 장치였으므로 제거한다.

- [ ] **Step 2: 항목별 즉시 저장** — viz 생성 루프(`_plan_visualizations` 뒤 mermaid/paperbanana/other 실행부)에서, 완료된 항목이 누적될 때마다 저장하는 헬퍼를 추가하고 각 항목 완료 지점에서 호출:

```python
async def _store_visualization_progress(
    paper_id: int, items: list[dict], cache_input: str, done: bool
) -> None:
    """항목이 하나 끝날 때마다 visualization 행을 갱신한다 (중간 사망 시 유실 방지)."""
    payload = json.dumps(
        {
            "items": sorted(items, key=lambda x: x.get("id", 0)),
            "total_count": len(items),
            "model_used": MODEL_VIZ_PLANNING,
            "planned_at": _utcnow_iso(),
            "complete": done,
        },
        ensure_ascii=False,
    )
    row = await fetch_one(
        "SELECT id FROM analysis_results WHERE paper_id = ? AND phase = 'visualization' ORDER BY id DESC LIMIT 1",
        (paper_id,),
    )
    if row:
        await execute_update(
            "UPDATE analysis_results SET result = ?, input_hash = ? WHERE id = ?",
            (payload, _input_hash(cache_input), row["id"]),
        )
    else:
        await _insert_analysis_result(
            paper_id, "visualization", payload, MODEL_VIZ_PLANNING, 0, 0, 0.0, cache_input,
        )
```

주의: `execute_update`/`_input_hash`가 없으면 이 파일과 `models/database.py`에서 실제 존재하는 update 헬퍼·해시 함수 이름을 찾아 그걸 쓰라 (`grep -n "def execute\|input_hash" models/database.py api/analysis_routes.py`). 기존 "Step 3: Store all visualization results in DB" 블록은 `_store_visualization_progress(paper_id, all_results, visualization_cache_input, done=True)` 호출로 대체. paperbanana 순차 루프와 mermaid gather 완료 지점, other 완료 지점마다 누적 리스트로 호출.

- [ ] **Step 3: 기동 복구** — `main.py`의 API 키 로딩 블록 다음에:

```python
    # 프로세스가 중간에 죽으면 papers.status가 'analyzing'으로 영구 고착된다.
    # 기동 시점에 살아있는 분석은 없으므로 전부 error로 정리한다.
    try:
        from models.database import execute_update
        n = await execute_update(
            "UPDATE papers SET status = 'error' WHERE status = 'analyzing'"
        )
        if n:
            print(f"[Sasoo] Recovered {n} paper(s) stuck in 'analyzing'.")
    except Exception as exc:
        print(f"[Sasoo] Warning: stuck-analysis recovery failed: {exc}")
```

주의: `execute_update`의 실제 시그니처/반환을 `models/database.py`에서 확인하고 맞춰라.

- [ ] **Step 4: 검증** — `.venv/bin/python -m pytest -q` 전부 PASS (test_analysis_routes의 스텁이 `api.report_service` 등을 모킹하므로 import 경로 변화에 주의)
- [ ] **Step 5: 커밋** — `git commit -m "feat(viz): route figure generation through figure_gen, checkpoint per item, recover stuck papers"`

---

### Task 5: PaperBanana 제거

**Files:**
- Delete: `sasoo/backend/services/viz/paperbanana_bridge.py`
- Modify: `sasoo/backend/api/settings.py` (debug 엔드포인트 2개 삭제), `sasoo/backend/main.py`·`sasoo/backend/api/settings.py` (`GOOGLE_API_KEY` 동기화 제거), `sasoo/backend/requirements.txt` (`paperbanana` 줄 삭제)

- [ ] **Step 1: 참조 전수 확인** — `grep -rn "paperbanana_bridge\|import paperbanana\|PaperBananaBridge" --include="*.py" . | grep -v .venv` → Task 4 이후 남은 참조는 settings.py debug 2개와 bridge 자신뿐이어야 함. `report_service._generate_paperbanana_image`(PIL 요약 카드)와 `get_paperbanana_dir`, `paperbanana_profile` 설정은 **남긴다**.
- [ ] **Step 2: 삭제** — `rm services/viz/paperbanana_bridge.py`; settings.py의 `@router.get("/debug/paperbanana")`·`@router.get("/debug/paperbanana/test")` 함수 블록(그걸 감싸는 조건문 포함) 삭제; requirements.txt에서 `paperbanana` 줄 삭제 (`structlog`/`tenacity` 등은 남김 — 다른 곳 사용 여부 grep 후 미사용이면 함께 제거 가능하나 필수 아님).
- [ ] **Step 3: GOOGLE_API_KEY 핵 제거** — main.py의 "Always sync GOOGLE_API_KEY" 블록과 settings.py update의 `os.environ["GOOGLE_API_KEY"] = ...` 줄 삭제 (PaperBanana만 이 변수명을 썼다. 제거 후 `grep -rn "GOOGLE_API_KEY" --include="*.py" . | grep -v .venv` 로 잔여 0 확인).
- [ ] **Step 4: 검증** — `.venv/bin/python -m pytest -q` PASS + `.venv/bin/python -c "import sys; sys.path.insert(0,'.'); import main"` OK + `grep -rn "import paperbanana" --include="*.py" . | grep -v .venv` 결과 없음
- [ ] **Step 5: 커밋** — `git commit -m "chore: remove the paperbanana package integration"`

---

### Task 6: 프론트엔드 Settings UI

**Files:**
- Modify: `sasoo/frontend/src/lib/api.ts`, `sasoo/frontend/src/lib/strings.ts`, `sasoo/frontend/src/pages/Settings.tsx`

**Interfaces:**
- Consumes: Task 3의 `openai_api_key`/`openai_key_unreadable`/`image_provider`/`image_quality` API 필드

- [ ] **Step 1: api.ts** — `Settings` 인터페이스의 `gemini_key_unreadable: boolean;` 아래:
```typescript
  openai_api_key: string;
  openai_key_unreadable: boolean;
  image_provider: 'openai' | 'gemini';
  image_quality: 'low' | 'medium' | 'high';
```

- [ ] **Step 2: strings.ts** — `keyUnreadableHelp` 아래:
```typescript
    openaiKey: 'OpenAI API 키',
    openaiHelp: '논문 도해 생성(gpt-image-2)에 사용됩니다.',
    imageProvider: '도해 생성 모델',
    imageProviderOpenai: 'gpt-image-2 (기본)',
    imageProviderGemini: 'Nano Banana 2 (Gemini)',
    imageQuality: '도해 품질',
```

- [ ] **Step 3: Settings.tsx** — Gemini 키 입력 블록과 동일한 패턴으로 OpenAI 키 입력 블록 추가 (상태 `openaiKey`/`openaiKeyStatus`/`openaiKeyUnreadable`/`showOpenaiKey`, ref `openaiInputRef` — Claude 키 제거 커밋(430e06b)의 역방향이 정확한 본보기: `git show 430e06b -- sasoo/frontend/src/pages/Settings.tsx`). `defaultSettings`에 `openai_api_key: ''`, `openai_key_unreadable: false`, `image_provider: 'openai'`, `image_quality: 'high'` 추가. 저장 payload에 `if (openaiKey.trim()) payload.openai_api_key = openaiKey.trim();` 추가. `hasChanges`에 `openaiKey.trim() !== '' ||` 추가. 로드/저장 시 `setOpenaiKeyStatus(data.openai_api_key || '')`·`setOpenaiKeyUnreadable(data.openai_key_unreadable ?? false)`.

도해 설정 select 2개는 보관함 경로 카드 위에 추가 (기존 select 패턴 — `pdf_parser_mode` select가 본보기):
```tsx
<div className="grid grid-cols-2 gap-4">
  <div>
    <label className="text-xs text-fg-muted mb-1.5 block">{S.settings.imageProvider}</label>
    <select className="input" value={imageProvider}
            onChange={(e) => setImageProvider(e.target.value as 'openai' | 'gemini')}>
      <option value="openai">{S.settings.imageProviderOpenai}</option>
      <option value="gemini">{S.settings.imageProviderGemini}</option>
    </select>
  </div>
  <div>
    <label className="text-xs text-fg-muted mb-1.5 block">{S.settings.imageQuality}</label>
    <select className="input" value={imageQuality}
            onChange={(e) => setImageQuality(e.target.value as 'low' | 'medium' | 'high')}>
      <option value="high">high ($0.17/장)</option>
      <option value="medium">medium ($0.04/장)</option>
      <option value="low">low ($0.005/장)</option>
    </select>
  </div>
</div>
```
상태 `imageProvider`/`imageQuality`는 `applySettingsToForm`에서 로드, 저장 payload와 `hasChanges` 비교에 포함.

- [ ] **Step 4: 검증** — `cd sasoo/frontend && pnpm exec tsc --noEmit` 에러 0
- [ ] **Step 5: 커밋** — `git commit -m "feat(settings-ui): OpenAI key input and image provider/quality controls"`

---

### Task 7: 최종 검증

- [ ] **Step 1:** `.venv/bin/python -m pytest -q` — 전부 PASS (75 + 신규)
- [ ] **Step 2:** `pnpm exec tsc --noEmit` — 에러 0
- [ ] **Step 3:** 성공 기준 4번: `grep -rn "import paperbanana\|from paperbanana" sasoo/backend --include="*.py" | grep -v .venv` → 0건
- [ ] **Step 4:** 앱 기동 스모크 — `pnpm dev` 후 `/health` 200, `GET /api/settings`에 `image_provider`/`image_quality` 포함, 로그에 `GOOGLE_API_KEY` 중복 경고 없음
- [ ] **Step 5:** 커밋 잔여분 정리 커밋

**실키 스모크(성공 기준 1·2·3)는 계획 밖:** 사용자가 Settings 화면에서 OpenAI 키를 입력한 뒤 오케스트레이터가 paper_id=49로 직접 수행한다.
