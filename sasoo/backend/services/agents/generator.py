"""
Sasoo - LLM-based Agent Profile Generator
Generates a complete AgentProfile from minimal user input using Gemini Pro.

Input:  domain_description (required), personality_hint (optional), color (optional)
Output: Full AgentProfile ready for review and saving.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from services.agents.md_loader import (
    AgentProfile,
    _get_bundled_agents_directory,
    list_all_agents,
)
from services.llm.gemini_client import GeminiClient, MODEL_PRO, _extract_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRESET_COLORS = [
    "#ef4444", "#f97316", "#eab308", "#22c55e",
    "#06b6d4", "#6366f1", "#a855f7", "#ec4899",
]

_SYSTEM_PROMPT = """\
너는 과학 논문 분석 앱 "Sasoo"의 에이전트 프로필 생성 전문가야.
사용자가 설명한 연구 분야에 맞는 에이전트를 생성해.

에이전트는 4단계 파이프라인으로 논문을 분석해:
1. Screening: 논문 초록/결론 기반 빠른 분류 및 핵심 주장 추출
2. Visual: 그래프/그림의 축, 에러바, 데이터 품질 검증
3. Recipe: Methods 섹션에서 실험 파라미터 추출 (EXPLICIT/INFERRED/MISSING 태깅)
4. Deep Dive: 주장-근거 매핑, 오류 전파, 물리적 제약 검증

모든 에이전트의 프롬프트는 영어로 작성해. 단, personality, quote, summary 예시는 한국어 반말이야.

중요한 규칙:
- name: 영문 소문자 1단어, 밑줄 가능 (예: photon, cell, neural)
- keywords: 10~15개의 영문 단일 단어
- weighted_keywords: 10~18개의 영문 복합 키워드 (2~3단어 조합)
- recipe_parameters: 10~15개의 영문 실험 파라미터명 (snake_case)
- prompts: 각 phase별로 기존 예시와 동일한 수준의 상세한 프롬프트 (영어)
  - screening: 키워드 체크 → 논문 유형 분류 → 핵심 주장 5개 → 레드 플래그 → 한국어 요약
  - visual: 축 검증 → 에러바 → 도메인 특화 데이터 품질 → 텍스트-그래프 일치 → 시각 이슈
  - recipe: 파라미터 목록별 추출 + EXPLICIT/INFERRED/MISSING 태깅 → 재현성 점수
  - deepdive: 오류 전파 → 물리적 제약 검증 → 주장-근거 매핑 → 선행연구 비교 → 한계 평가 → 점수 + verdict

응답은 반드시 지정된 JSON 형식으로만 해."""


def _build_user_prompt(
    domain_description: str,
    personality_hint: str,
    existing_keywords: list[str],
    example_agent_md: str,
) -> str:
    """Build the user prompt with few-shot example and constraints."""

    existing_kw_str = ""
    if existing_keywords:
        sample = existing_keywords[:50]  # cap to avoid prompt bloat
        existing_kw_str = (
            "\n\n주의: 다음 키워드들은 이미 다른 에이전트가 사용 중이니 "
            "가능하면 겹치지 않게 해줘:\n"
            f"{json.dumps(sample, ensure_ascii=False)}"
        )

    return f"""\
아래는 기존 에이전트 예시야 (photon.md). 이 수준과 형식을 참고해서 생성해:

--- 예시 시작 ---
{example_agent_md}
--- 예시 끝 ---
{existing_kw_str}

연구 분야: {domain_description}
성격 힌트: {personality_hint}

다음 JSON 형식으로 응답해 (모든 필드 필수):
{{
  "name": "영문 소문자 1단어 (예: photon, cell, neural)",
  "display_name": "Agent {{Name}} 형식",
  "display_name_ko": "{{한국어음차}} 에이전트",
  "domain": "영문_소문자_키 (예: optics, bio, organic_chem)",
  "domain_display": "English Domain Name",
  "domain_display_ko": "한국어 분야명",
  "personality": "반말 + 특성 설명 (1~2문장, 한국어)",
  "quote": "에이전트 대표 대사 (한국어 반말, 1문장)",
  "keywords": ["word1", "word2", ...],
  "weighted_keywords": ["compound keyword1", ...],
  "recipe_parameters": ["param1", "param2", ...],
  "prompts": {{
    "screening": "전체 프롬프트 (영어, 위 예시 수준)",
    "visual": "전체 프롬프트 (영어, 위 예시 수준)",
    "recipe": "전체 프롬프트 (영어, 위 예시 수준)",
    "deepdive": "전체 프롬프트 (영어, 위 예시 수준)"
  }}
}}"""


# ---------------------------------------------------------------------------
# AgentGenerator
# ---------------------------------------------------------------------------

class AgentGenerator:
    """Generate a full AgentProfile from minimal user input via Gemini Pro."""

    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    async def generate(
        self,
        domain_description: str,
        personality_hint: Optional[str] = None,
        color: Optional[str] = None,
    ) -> AgentProfile:
        """
        Generate a complete AgentProfile using LLM.

        Args:
            domain_description: Research domain description (required).
            personality_hint: Personality/tone hint (optional).
            color: Hex color (optional, auto-assigned if None).

        Returns:
            A fully populated AgentProfile (not yet saved).

        Raises:
            RuntimeError: If generation or parsing fails.
        """
        example_md = self._load_example_agent()
        existing_kw = self._get_existing_keywords()
        hint = personality_hint or "자유롭게 정해줘"

        user_prompt = _build_user_prompt(
            domain_description=domain_description,
            personality_hint=hint,
            existing_keywords=existing_kw,
            example_agent_md=example_md,
        )

        response = await self._client._call(
            model=MODEL_PRO,
            contents=user_prompt,
            system_instruction=_SYSTEM_PROMPT,
            thinking_level="high",
            phase="agent_generation",
            response_mime_type="application/json",
        )

        text = self._client._response_text(response)
        data = _extract_json(text)

        if "_parse_error" in data:
            logger.error("Agent generation JSON parse failed: %s", data["_parse_error"])
            raise RuntimeError(
                f"Failed to parse generated agent profile: {data['_parse_error']}"
            )

        return self._data_to_profile(data, color)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_example_agent(self) -> str:
        """Load photon.md as few-shot example."""
        bundled_dir = _get_bundled_agents_directory()
        photon_path = bundled_dir / "photon.md"
        if photon_path.exists():
            return photon_path.read_text(encoding="utf-8")
        logger.warning("photon.md not found at %s, proceeding without example", bundled_dir)
        return "(예시 에이전트 파일 없음)"

    def _get_existing_keywords(self) -> list[str]:
        """Collect all keywords from existing agents to avoid overlap."""
        try:
            agents = list_all_agents()
        except Exception:
            return []
        all_kw: set[str] = set()
        for a in agents:
            all_kw.update(a.keywords)
            all_kw.update(a.weighted_keywords)
        return sorted(all_kw)

    def _pick_color(self, preferred: Optional[str]) -> str:
        """Pick a color: use preferred, or auto-assign one not in use."""
        if preferred:
            return preferred
        try:
            used = {a.color for a in list_all_agents()}
        except Exception:
            used = set()
        for c in PRESET_COLORS:
            if c not in used:
                return c
        return PRESET_COLORS[0]

    def _data_to_profile(self, data: dict, color_override: Optional[str]) -> AgentProfile:
        """Convert LLM JSON output to AgentProfile."""
        prompts_raw = data.get("prompts", {})
        prompts = {
            "screening": prompts_raw.get("screening", ""),
            "visual": prompts_raw.get("visual", ""),
            "recipe": prompts_raw.get("recipe", ""),
            "deepdive": prompts_raw.get("deepdive", ""),
        }

        color = self._pick_color(color_override) if not color_override else color_override
        # If LLM didn't return a color but no override, use auto-pick
        if not color_override:
            color = self._pick_color(None)

        return AgentProfile(
            agent_name=str(data.get("name", "new_agent")),
            display_name=str(data.get("display_name", "")),
            display_name_ko=str(data.get("display_name_ko", "")),
            domain=str(data.get("domain", "")),
            domain_display=str(data.get("domain_display", "")),
            domain_display_ko=str(data.get("domain_display_ko", "")),
            personality=str(data.get("personality", "")),
            quote=str(data.get("quote", "")),
            color=color,
            keywords=list(data.get("keywords", [])),
            weighted_keywords=list(data.get("weighted_keywords", [])),
            recipe_parameters=list(data.get("recipe_parameters", [])),
            model="gemini-pro",
            enabled=True,
            prompts=prompts,
        )
