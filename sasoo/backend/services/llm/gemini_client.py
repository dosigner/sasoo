"""
Sasoo - Gemini LLM Client
Wraps google-genai SDK for all Gemini model interactions.

Models:
  - gemini-3-flash-preview   : Phase 1 (Screening) + Phase 2 (Visual)
  - gemini-3-pro-preview     : Phase 3 (Recipe) + Phase 4 (DeepDive)
  - gemini-3-pro-image-preview : PaperBanana image generation

Config: ~/sasoo-library/config.json  ->  { "gemini_api_key": "..." }
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from google import genai
from google.genai import types

from services.pricing import calc_cost

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_ROOT = Path.home() / "sasoo-library"
CONFIG_PATH = LIBRARY_ROOT / "config.json"

# Model identifiers
MODEL_FLASH = "gemini-3-flash-preview"
MODEL_PRO = "gemini-3-pro-preview"
MODEL_PRO_IMAGE = "gemini-3-pro-image-preview"

# Thinking budget by level
THINKING_BUDGETS: dict[str, int] = {
    "minimal": 1024,
    "medium": 4096,
    "high": 8192,
}


# ---------------------------------------------------------------------------
# Token / Cost tracking
# ---------------------------------------------------------------------------

@dataclass
class UsageRecord:
    """Single API call usage."""
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    phase: str


@dataclass
class UsageTracker:
    """Cumulative token usage across a session."""
    records: list[UsageRecord] = field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.records)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.records)

    @property
    def total_cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.records)

    def add(self, record: UsageRecord) -> None:
        self.records.append(record)
        logger.info(
            "Gemini usage | model=%s phase=%s in=%d out=%d cost=$%.6f latency=%dms",
            record.model,
            record.phase,
            record.input_tokens,
            record.output_tokens,
            record.cost_usd,
            record.latency_ms,
        )

    def summary(self) -> dict[str, Any]:
        return {
            "total_calls": len(self.records),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "by_phase": self._by_phase(),
        }

    def _by_phase(self) -> dict[str, dict[str, Any]]:
        phases: dict[str, dict[str, Any]] = {}
        for r in self.records:
            if r.phase not in phases:
                phases[r.phase] = {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                }
            p = phases[r.phase]
            p["calls"] += 1
            p["input_tokens"] += r.input_tokens
            p["output_tokens"] += r.output_tokens
            p["cost_usd"] = round(p["cost_usd"] + r.cost_usd, 6)
        return phases


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_api_key() -> str:
    """Load Gemini API key from ~/sasoo-library/config.json."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Config file not found: {CONFIG_PATH}. "
            "Create it with: {\"gemini_api_key\": \"YOUR_KEY\"}"
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    key = config.get("gemini_api_key", "")
    if not key:
        raise ValueError("gemini_api_key is empty in config.json")
    return key




def _extract_json(text: str) -> dict:
    """
    Parse JSON from model output.
    Handles responses wrapped in ```json ... ``` fences.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (```json or ```)
        first_newline = cleaned.index("\n")
        cleaned = cleaned[first_newline + 1:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse JSON from model output: %s", exc)
        logger.debug("Raw output:\n%s", text)
        return {"_raw": text, "_parse_error": str(exc)}


def is_parse_error(result: dict) -> bool:
    """
    Check if a result dict contains a JSON parse error.

    Args:
        result: Dictionary returned from _extract_json or similar parsing.

    Returns:
        True if the result contains a parse error indicator.
    """
    return "_parse_error" in result


# ---------------------------------------------------------------------------
# GeminiClient
# ---------------------------------------------------------------------------

class GeminiClient:
    """
    Async client for all Gemini model interactions in Sasoo.

    Usage:
        client = GeminiClient()
        result = await client.analyze_screening(abstract, conclusion)
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or _load_api_key()
        self._client = genai.Client(api_key=self._api_key)
        self.usage = UsageTracker()

    # ------------------------------------------------------------------
    # Internal: generic call
    # ------------------------------------------------------------------

    async def _call(
        self,
        *,
        model: str,
        contents: list[types.Content] | list[types.Part] | str,
        system_instruction: Optional[str] = None,
        thinking_level: str = "medium",
        phase: str = "unknown",
        response_mime_type: Optional[str] = None,
    ) -> types.GenerateContentResponse:
        """
        Low-level call to Gemini with thinking budget, usage tracking,
        and automatic retries on transient errors.
        """
        thinking_config = types.ThinkingConfig(
            thinking_budget=THINKING_BUDGETS.get(thinking_level, 4096),
        )

        generation_config_kwargs: dict[str, Any] = {
            "thinking_config": thinking_config,
            "temperature": 1.0,  # Required when thinking is enabled
        }
        if response_mime_type:
            generation_config_kwargs["response_mime_type"] = response_mime_type

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            **generation_config_kwargs,
        )

        start = time.monotonic()
        last_error: Optional[Exception] = None

        for attempt in range(3):
            try:
                response = await self._client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Gemini call attempt %d/%d failed: %s",
                    attempt + 1,
                    3,
                    exc,
                )
                if attempt < 2:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
        else:
            raise RuntimeError(
                f"Gemini call failed after 3 attempts: {last_error}"
            ) from last_error

        latency_ms = (time.monotonic() - start) * 1000

        # Extract usage metadata
        input_tokens = 0
        output_tokens = 0
        if response.usage_metadata:
            input_tokens = response.usage_metadata.prompt_token_count or 0
            output_tokens = response.usage_metadata.candidates_token_count or 0

        cost = calc_cost(model, input_tokens, output_tokens)
        self.usage.add(UsageRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=round(latency_ms, 1),
            phase=phase,
        ))

        return response

    def _response_text(self, response: types.GenerateContentResponse) -> str:
        """Extract text from a Gemini response, concatenating all text parts."""
        parts = []
        if response.candidates:
            for candidate in response.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.text:
                            parts.append(part.text)
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Phase 1: Screening
    # ------------------------------------------------------------------

    async def analyze_screening(
        self,
        abstract: str,
        conclusion: str,
        agent_prompt: Optional[str] = None,
    ) -> dict:
        """
        Phase 1 screening analysis.
        Uses Flash with minimal thinking for fast triage.

        Args:
            abstract: Paper abstract text.
            conclusion: Paper conclusion text.
            agent_prompt: Domain agent's screening prompt overlay.

        Returns:
            Structured dict with screening results:
            {
                "domain": str,
                "relevance_score": float,
                "key_claims": list[str],
                "methodology_type": str,
                "red_flags": list[str],
                "summary": str,
            }
        """
        system = (
            "You are a scientific paper screening assistant. "
            "Analyze the abstract and conclusion to determine the paper's "
            "domain, key claims, methodology type, and potential red flags.\n"
            "Respond ONLY with valid JSON.\n"
        )
        if agent_prompt:
            system += f"\n--- Domain Agent Instructions ---\n{agent_prompt}\n"

        prompt = (
            "=== ABSTRACT ===\n"
            f"{abstract}\n\n"
            "=== CONCLUSION ===\n"
            f"{conclusion}\n\n"
            "Produce a JSON object with these fields:\n"
            '  "domain": string (optics | bio | ai_ml | ee | unknown),\n'
            '  "relevance_score": float 0.0-1.0,\n'
            '  "key_claims": list of strings (max 5),\n'
            '  "methodology_type": string (experimental | computational | theoretical | review | mixed),\n'
            '  "red_flags": list of strings (any suspicious patterns, empty if none),\n'
            '  "summary": string (2-3 sentence Korean summary in 반말)\n'
        )

        response = await self._call(
            model=MODEL_FLASH,
            contents=prompt,
            system_instruction=system,
            thinking_level="minimal",
            phase="screening",
            response_mime_type="application/json",
        )
        return _extract_json(self._response_text(response))

    # ------------------------------------------------------------------
    # Phase 2: Visual Analysis
    # ------------------------------------------------------------------

    async def analyze_visual(
        self,
        figures: list[bytes],
        captions: list[str],
        agent_prompt: Optional[str] = None,
    ) -> dict:
        """
        Phase 2 visual/figure analysis (multimodal).
        Uses Flash with medium thinking for figure interpretation.

        Args:
            figures: List of figure image bytes (PNG/JPEG).
            captions: Corresponding figure captions.
            agent_prompt: Domain agent's visual analysis prompt overlay.

        Returns:
            Structured dict with visual analysis:
            {
                "figures": [
                    {
                        "figure_id": str,
                        "type": str,
                        "axes": {"x": str, "y": str, "scale": str},
                        "has_error_bars": bool,
                        "data_quality": str,
                        "observations": list[str],
                        "issues": list[str],
                    }
                ],
                "overall_visual_quality": str,
                "summary": str,
            }
        """
        system = (
            "You are a scientific figure analysis specialist. "
            "Examine each figure carefully: check axis labels, scales (linear vs log), "
            "error bars, data presentation quality, and consistency with captions.\n"
            "Respond ONLY with valid JSON.\n"
        )
        if agent_prompt:
            system += f"\n--- Domain Agent Instructions ---\n{agent_prompt}\n"

        # Build multimodal content parts
        parts: list[types.Part] = []
        for idx, (img_bytes, caption) in enumerate(zip(figures, captions)):
            parts.append(types.Part.from_text(
                text=f"\n--- Figure {idx + 1} ---\nCaption: {caption}\n"
            ))
            parts.append(types.Part.from_bytes(
                data=img_bytes,
                mime_type="image/png",
            ))

        parts.append(types.Part.from_text(
            text=(
                "\nAnalyze ALL figures above. Return JSON with:\n"
                '  "figures": list of objects with fields:\n'
                '    "figure_id": "figure_N",\n'
                '    "type": (graph | micrograph | schematic | photo | table_figure | other),\n'
                '    "axes": {"x": label, "y": label, "scale": "linear" | "log" | "log-log" | "N/A"},\n'
                '    "has_error_bars": bool,\n'
                '    "data_quality": (excellent | good | fair | poor),\n'
                '    "observations": list of key observations,\n'
                '    "issues": list of any problems detected\n'
                '  "overall_visual_quality": (excellent | good | fair | poor),\n'
                '  "summary": Korean summary in 반말 (2-3 sentences)\n'
            )
        ))

        response = await self._call(
            model=MODEL_FLASH,
            contents=[types.Content(parts=parts, role="user")],
            system_instruction=system,
            thinking_level="medium",
            phase="visual",
            response_mime_type="application/json",
        )
        return _extract_json(self._response_text(response))

    # ------------------------------------------------------------------
    # Phase 3: Recipe Extraction
    # ------------------------------------------------------------------

    async def analyze_recipe(
        self,
        method_text: str,
        agent_prompt: str,
    ) -> dict:
        """
        Phase 3 recipe/methodology extraction.
        Uses Pro with high thinking for deep parameter extraction.

        Args:
            method_text: Full methods/experimental section text.
            agent_prompt: Domain agent's recipe prompt with parameter list.

        Returns:
            Structured dict with extracted recipe:
            {
                "parameters": {
                    "param_name": {
                        "value": str | number,
                        "unit": str,
                        "tag": "EXPLICIT" | "INFERRED" | "MISSING",
                        "source": str (quote or inference reason),
                    }
                },
                "procedure_steps": list[str],
                "equipment": list[str],
                "materials": list[str],
                "missing_critical": list[str],
                "reproducibility_score": float,
                "summary": str,
            }
        """
        system = (
            "You are a scientific methodology extraction specialist. "
            "Extract ALL experimental parameters, procedures, equipment, and materials.\n"
            "For each parameter, tag it:\n"
            "  [EXPLICIT] - directly stated in the text with exact value\n"
            "  [INFERRED] - calculated or inferred from context\n"
            "  [MISSING] - not found but expected for this type of experiment\n"
            "Respond ONLY with valid JSON.\n"
            f"\n--- Domain Agent Instructions ---\n{agent_prompt}\n"
        )

        prompt = (
            "=== METHODS SECTION ===\n"
            f"{method_text}\n\n"
            "Extract ALL experimental parameters and procedures. Return JSON with:\n"
            '  "parameters": object mapping parameter names to:\n'
            '    {"value": ..., "unit": ..., "tag": "EXPLICIT"|"INFERRED"|"MISSING", "source": ...}\n'
            '  "procedure_steps": ordered list of procedure steps,\n'
            '  "equipment": list of equipment used,\n'
            '  "materials": list of materials/chemicals,\n'
            '  "missing_critical": list of parameters that SHOULD be reported but are missing,\n'
            '  "reproducibility_score": float 0.0-1.0 (how reproducible based on info given),\n'
            '  "summary": Korean summary in 반말 (2-3 sentences)\n'
        )

        response = await self._call(
            model=MODEL_PRO,
            contents=prompt,
            system_instruction=system,
            thinking_level="high",
            phase="recipe",
            response_mime_type="application/json",
        )
        return _extract_json(self._response_text(response))

    # ------------------------------------------------------------------
    # Phase 4: DeepDive Analysis
    # ------------------------------------------------------------------

    async def analyze_deepdive(
        self,
        intro_text: str,
        results_text: str,
        agent_prompt: str,
    ) -> dict:
        """
        Phase 4 deep-dive critical analysis.
        Uses Pro with high thinking for rigorous evaluation.

        Args:
            intro_text: Introduction section text.
            results_text: Results and discussion section text.
            agent_prompt: Domain agent's deepdive prompt.

        Returns:
            Structured dict with deep analysis:
            {
                "claim_evidence_map": [
                    {
                        "claim": str,
                        "evidence": str,
                        "strength": "strong" | "moderate" | "weak" | "unsupported",
                        "issues": list[str],
                    }
                ],
                "error_analysis": {
                    "propagation_issues": list[str],
                    "statistical_concerns": list[str],
                    "systematic_risks": list[str],
                },
                "physical_constraints": {
                    "satisfied": list[str],
                    "violated": list[str],
                    "unchecked": list[str],
                },
                "novelty_assessment": str,
                "limitations_acknowledged": list[str],
                "limitations_missed": list[str],
                "overall_score": float,
                "verdict": str,
                "summary": str,
            }
        """
        system = (
            "You are a rigorous scientific paper critic. "
            "Evaluate claims vs evidence, check error propagation, "
            "verify physical constraints, and assess overall scientific quality.\n"
            "Be thorough but fair. Identify both strengths and weaknesses.\n"
            "Respond ONLY with valid JSON.\n"
            f"\n--- Domain Agent Instructions ---\n{agent_prompt}\n"
        )

        prompt = (
            "=== INTRODUCTION ===\n"
            f"{intro_text}\n\n"
            "=== RESULTS & DISCUSSION ===\n"
            f"{results_text}\n\n"
            "Perform deep critical analysis. Return JSON with:\n"
            '  "claim_evidence_map": list of {claim, evidence, strength, issues},\n'
            '  "error_analysis": {propagation_issues, statistical_concerns, systematic_risks},\n'
            '  "physical_constraints": {satisfied, violated, unchecked},\n'
            '  "novelty_assessment": string,\n'
            '  "limitations_acknowledged": list,\n'
            '  "limitations_missed": list,\n'
            '  "overall_score": float 0.0-10.0,\n'
            '  "verdict": Korean verdict in 반말 (1-2 sentences),\n'
            '  "summary": Korean detailed summary in 반말 (3-5 sentences)\n'
        )

        response = await self._call(
            model=MODEL_PRO,
            contents=prompt,
            system_instruction=system,
            thinking_level="high",
            phase="deepdive",
            response_mime_type="application/json",
        )
        return _extract_json(self._response_text(response))

    # ------------------------------------------------------------------
    # Visualization Router
    # ------------------------------------------------------------------

    async def route_visualization(
        self,
        analysis_results: dict,
    ) -> list[dict]:
        """
        Viz Router: decide which visualization types best represent
        the analysis results.

        Uses Flash with medium thinking for fast routing.

        Args:
            analysis_results: Combined dict from all phases.

        Returns:
            List of visualization specs:
            [
                {
                    "viz_type": str,
                    "title": str,
                    "description": str,
                    "data_source": str,
                    "priority": int,
                    "mermaid_suitable": bool,
                }
            ]
        """
        system = (
            "You are a scientific visualization strategist. "
            "Given analysis results from a paper review, decide which "
            "visualizations would best communicate the findings.\n\n"
            "Available visualization types:\n"
            "  - flowchart: for procedures, methodology steps\n"
            "  - mindmap: for concept relationships, paper overview\n"
            "  - timeline: for temporal processes, experimental sequences\n"
            "  - comparison_table: for parameter comparisons\n"
            "  - claim_evidence_graph: for claims vs evidence mapping\n"
            "  - parameter_radar: for multi-dimensional parameter comparison\n"
            "  - quality_dashboard: for overall quality metrics\n"
            "  - error_tree: for error propagation visualization\n"
            "Respond ONLY with valid JSON array.\n"
        )

        prompt = (
            "=== ANALYSIS RESULTS ===\n"
            f"{json.dumps(analysis_results, ensure_ascii=False, indent=2)}\n\n"
            "Select the best visualizations for these results. "
            "Return a JSON array of objects with:\n"
            '  "viz_type": one of the available types,\n'
            '  "title": display title (Korean),\n'
            '  "description": what this viz shows (Korean),\n'
            '  "data_source": which part of the analysis to use,\n'
            '  "priority": 1 (highest) to 5 (lowest),\n'
            '  "mermaid_suitable": bool (can this be rendered as Mermaid?)\n'
        )

        response = await self._call(
            model=MODEL_FLASH,
            contents=prompt,
            system_instruction=system,
            thinking_level="medium",
            phase="viz_router",
            response_mime_type="application/json",
        )

        text = self._response_text(response)
        parsed = _extract_json(text)
        # Handle case where response is a list at top level
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and "visualizations" in parsed:
            return parsed["visualizations"]
        if isinstance(parsed, dict) and "_raw" in parsed:
            # JSON parse failed, try to extract array
            try:
                raw = parsed["_raw"]
                start = raw.index("[")
                end = raw.rindex("]") + 1
                return json.loads(raw[start:end])
            except (ValueError, json.JSONDecodeError):
                logger.error("Could not extract viz list from response")
                return []
        # Wrap single dict in list
        return [parsed]

    # ------------------------------------------------------------------
    # PaperBanana Image Generation
    # ------------------------------------------------------------------

    async def generate_image(
        self,
        prompt: str,
    ) -> bytes:
        """
        Generate a PaperBanana illustration using Gemini Pro Image.

        Args:
            prompt: Detailed image generation prompt.

        Returns:
            Raw image bytes (PNG).

        Raises:
            RuntimeError: If no image was generated.
        """
        system = (
            "You are an artistic scientific illustrator. "
            "Generate a clear, informative, and visually appealing "
            "illustration based on the given description."
        )

        config = types.GenerateContentConfig(
            system_instruction=system,
            response_modalities=["IMAGE", "TEXT"],
            temperature=1.0,
        )

        start = time.monotonic()
        last_error: Optional[Exception] = None

        for attempt in range(3):
            try:
                response = await self._client.aio.models.generate_content(
                    model=MODEL_PRO_IMAGE,
                    contents=prompt,
                    config=config,
                )
                break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Image generation attempt %d/%d failed: %s",
                    attempt + 1,
                    3,
                    exc,
                )
                if attempt < 2:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
        else:
            raise RuntimeError(
                f"Image generation failed after 3 attempts: {last_error}"
            ) from last_error

        latency_ms = (time.monotonic() - start) * 1000

        # Extract usage
        input_tokens = 0
        output_tokens = 0
        if response.usage_metadata:
            input_tokens = response.usage_metadata.prompt_token_count or 0
            output_tokens = response.usage_metadata.candidates_token_count or 0

        cost = calc_cost(MODEL_PRO_IMAGE, input_tokens, output_tokens)
        self.usage.add(UsageRecord(
            model=MODEL_PRO_IMAGE,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=round(latency_ms, 1),
            phase="paperbanana",
        ))

        # Extract image bytes from response
        if response.candidates:
            for candidate in response.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.inline_data and part.inline_data.data:
                            return part.inline_data.data

        raise RuntimeError(
            "Gemini returned a response but no image data was found. "
            "The model may have returned text-only output."
        )

    # ------------------------------------------------------------------
    # Domain classification (used by DomainRouter fallback)
    # ------------------------------------------------------------------

    async def classify_domain(
        self,
        title: str,
        abstract: str,
    ) -> dict:
        """
        Semantic domain classification using Flash.
        Used as fallback when keyword matching confidence is low.

        Args:
            title: Paper title.
            abstract: Paper abstract.

        Returns:
            {
                "domain": str,
                "confidence": float,
                "reasoning": str,
            }
        """
        system = (
            "You are a scientific paper domain classifier. "
            "Classify the paper into exactly ONE domain.\n"
            "Available domains:\n"
            "  - optics: optics, photonics, lasers, fiber optics, imaging systems\n"
            "  - bio: biology, biochemistry, molecular biology, genetics, biomedical\n"
            "  - ai_ml: artificial intelligence, machine learning, deep learning, NLP, CV\n"
            "  - ee: electrical engineering, circuits, semiconductors, power systems\n"
            "  - unknown: cannot determine with confidence\n"
            "Respond ONLY with valid JSON.\n"
        )

        prompt = (
            f"Title: {title}\n\n"
            f"Abstract: {abstract}\n\n"
            "Classify this paper. Return JSON:\n"
            '  "domain": one of (optics | bio | ai_ml | ee | unknown),\n'
            '  "confidence": float 0.0-1.0,\n'
            '  "reasoning": brief explanation\n'
        )

        response = await self._call(
            model=MODEL_FLASH,
            contents=prompt,
            system_instruction=system,
            thinking_level="minimal",
            phase="domain_classification",
            response_mime_type="application/json",
        )
        return _extract_json(self._response_text(response))

    # ------------------------------------------------------------------
    # Generic generate (used by AnalysisPipeline and VizRouter)
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        model: str = MODEL_FLASH,
        system_prompt: Optional[str] = None,
        temperature: float = 0.5,
        thinking_level: str = "medium",
        phase: str = "generic",
        response_mime_type: Optional[str] = None,
    ) -> Any:
        """
        Generic text generation call.

        Args:
            prompt: User prompt text.
            model: Model identifier.
            system_prompt: Optional system instruction.
            temperature: Generation temperature (ignored when thinking is enabled).
            thinking_level: Thinking budget level (minimal/medium/high).
            phase: Phase name for usage tracking.
            response_mime_type: Response format (e.g., 'application/json').

        Returns:
            GenerateContentResponse object.
        """
        response = await self._call(
            model=model,
            contents=prompt,
            system_instruction=system_prompt,
            thinking_level=thinking_level,
            phase=phase,
            response_mime_type=response_mime_type,
        )
        return response

    async def generate_multimodal(
        self,
        prompt: str,
        image_paths: list[str],
        model: str = MODEL_FLASH,
        system_prompt: Optional[str] = None,
        temperature: float = 0.5,
        thinking_level: str = "medium",
        phase: str = "visual",
        response_mime_type: Optional[str] = None,
    ) -> Any:
        """
        Multimodal generation with text + images.

        Args:
            prompt: User prompt text.
            image_paths: List of image file paths to include.
            model: Model identifier.
            system_prompt: Optional system instruction.
            temperature: Generation temperature.
            thinking_level: Thinking budget level.
            phase: Phase name for usage tracking.
            response_mime_type: Response format.

        Returns:
            GenerateContentResponse object.
        """
        parts: list[types.Part] = [types.Part.from_text(text=prompt)]

        for img_path in image_paths:
            path = Path(img_path)
            if path.exists():
                img_bytes = path.read_bytes()
                # Determine mime type
                suffix = path.suffix.lower()
                mime_map = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".gif": "image/gif",
                    ".webp": "image/webp",
                    ".bmp": "image/bmp",
                }
                mime_type = mime_map.get(suffix, "image/png")
                parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime_type))

        content = [types.Content(parts=parts, role="user")]

        response = await self._call(
            model=model,
            contents=content,
            system_instruction=system_prompt,
            thinking_level=thinking_level,
            phase=phase,
            response_mime_type=response_mime_type,
        )
        return response

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_last_usage(self) -> Optional[UsageRecord]:
        """Return the most recent usage record, if any."""
        if self.usage.records:
            return self.usage.records[-1]
        return None

    def get_usage_summary(self) -> dict[str, Any]:
        """Return cumulative usage summary."""
        return self.usage.summary()

    def reset_usage(self) -> None:
        """Clear all usage records (e.g., between papers)."""
        self.usage.records.clear()
