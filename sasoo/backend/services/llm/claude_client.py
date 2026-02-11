"""
Sasoo - Claude LLM Client
Wraps Anthropic SDK for Mermaid diagram generation.

Model: claude-sonnet-4-5-20250929
Purpose: Convert visualization JSON specs into Mermaid diagram code.

Config: <project>/library/config.json  ->  { "anthropic_api_key": "..." }
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import anthropic

from services.pricing import calc_cost

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

from models.database import CONFIG_PATH

MODEL_SONNET = "claude-sonnet-4-5-20250929"

MAX_TOKENS = 4096


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
            "Claude usage | model=%s phase=%s in=%d out=%d cost=$%.6f latency=%dms",
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
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_api_key() -> str:
    """Load Anthropic API key from library/config.json."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Config file not found: {CONFIG_PATH}. "
            "Create it with: {\"anthropic_api_key\": \"YOUR_KEY\"}"
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    key = config.get("anthropic_api_key", "")
    if not key:
        raise ValueError("anthropic_api_key is empty in config.json")
    return key




def _extract_mermaid(text: str) -> str:
    """
    Extract Mermaid code block from model output.
    Handles responses wrapped in ```mermaid ... ``` fences.
    Returns raw Mermaid code without fences.
    """
    cleaned = text.strip()

    # Look for ```mermaid ... ``` block
    mermaid_start = cleaned.find("```mermaid")
    if mermaid_start != -1:
        code_start = cleaned.index("\n", mermaid_start) + 1
        code_end = cleaned.find("```", code_start)
        if code_end != -1:
            return cleaned[code_start:code_end].strip()

    # Look for generic ``` ... ``` block
    generic_start = cleaned.find("```")
    if generic_start != -1:
        first_newline = cleaned.index("\n", generic_start)
        code_start = first_newline + 1
        code_end = cleaned.find("```", code_start)
        if code_end != -1:
            return cleaned[code_start:code_end].strip()

    # No fence found, return as-is (might already be raw Mermaid)
    return cleaned


# ---------------------------------------------------------------------------
# Mermaid Diagram Type Prompts
# ---------------------------------------------------------------------------

_MERMAID_TYPE_GUIDANCE: dict[str, str] = {
    "flowchart": (
        "Use `flowchart TD` (top-down) or `flowchart LR` (left-right).\n"
        "Use rounded boxes `([ ])` for start/end, rectangles `[ ]` for steps, "
        "diamonds `{ }` for decisions.\n"
        "Use descriptive edge labels with `-->|label|`.\n"
    ),
    "mindmap": (
        "Use `mindmap` syntax.\n"
        "Central topic as root, branches for sub-topics.\n"
        "Use indentation to define hierarchy.\n"
    ),
    "timeline": (
        "Use `timeline` syntax.\n"
        "Each entry: `title : event`.\n"
        "Group events by section if needed.\n"
    ),
    "comparison_table": (
        "Since Mermaid has no native table, use a `flowchart LR` with "
        "subgraph boxes arranged in a grid pattern to simulate a table.\n"
        "Each column as a subgraph, rows as nodes.\n"
    ),
    "claim_evidence_graph": (
        "Use `flowchart TD`.\n"
        "Claims as colored boxes (classDef claim fill:#f9f), "
        "evidence as separate boxes (classDef evidence fill:#9f9).\n"
        "Edge labels show strength: strong/moderate/weak.\n"
        "Use different line styles: `-->` strong, `-.->` moderate, `..>` weak.\n"
    ),
    "parameter_radar": (
        "Mermaid doesn't support radar charts natively. "
        "Use `xychart-beta` with bar format to approximate, "
        "or use `flowchart` with a visual layout.\n"
    ),
    "quality_dashboard": (
        "Use `flowchart LR` with subgraphs for each metric category.\n"
        "Use colored nodes (classDef) for status:\n"
        "  green for good, yellow for fair, red for poor.\n"
    ),
    "error_tree": (
        "Use `flowchart TD` to show error propagation.\n"
        "Root node is the main measurement.\n"
        "Child nodes are error sources.\n"
        "Edge labels show contribution magnitude.\n"
    ),
}


# ---------------------------------------------------------------------------
# ClaudeClient
# ---------------------------------------------------------------------------

class ClaudeClient:
    """
    Async client for Claude Sonnet interactions in Sasoo.
    Primary purpose: convert visualization JSON specs to Mermaid code.

    Usage:
        client = ClaudeClient()
        mermaid_code = await client.generate_mermaid(viz_json)
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or _load_api_key()
        self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        self.usage = UsageTracker()

    # ------------------------------------------------------------------
    # Mermaid Generation
    # ------------------------------------------------------------------

    async def generate_mermaid(
        self,
        viz_json: dict,
    ) -> str:
        """
        Convert a visualization spec JSON to Mermaid diagram code.

        The viz_json should contain:
            - viz_type: type of diagram (flowchart, mindmap, timeline, etc.)
            - title: display title
            - description: what this viz shows
            - data: the actual data/content to visualize

        Args:
            viz_json: Visualization specification from the Viz Router.

        Returns:
            Valid Mermaid diagram code string (without fences).
        """
        viz_type = viz_json.get("viz_type", "flowchart")
        title = viz_json.get("title", "Diagram")
        description = viz_json.get("description", "")
        data = viz_json.get("data", viz_json)

        type_guidance = _MERMAID_TYPE_GUIDANCE.get(viz_type, "")

        system = (
            "You are a Mermaid diagram expert. "
            "Convert the given visualization specification into valid Mermaid code.\n\n"
            "CRITICAL RULES (Mermaid v10.x compatibility):\n"
            "1. Output ONLY the Mermaid code inside a ```mermaid``` fence. No other text.\n"
            "2. The diagram must be syntactically valid Mermaid v10.x.\n"
            "3. Use Korean for all labels and text content.\n"
            "4. Keep labels concise (under 30 characters per node).\n"
            "5. NEVER use --- frontmatter blocks or accTitle. Start directly with the diagram type keyword.\n"
            "6. ALWAYS wrap node labels containing special characters in double quotes: A[\"레이저 소스 (1064nm)\"].\n"
            "7. Special characters that MUST be quoted: parentheses (), brackets [], braces {}, colons :, semicolons ;, pipes |, angles <>.\n"
            "8. Add classDef for color coding where appropriate.\n"
            "9. Use simple alphanumeric node IDs (e.g., A, B, step1, step2). Avoid Korean in node IDs.\n"
            "10. Do NOT use HTML tags inside labels except <br/> for line breaks.\n\n"
            f"Diagram type: {viz_type}\n"
            f"{type_guidance}\n"
        )

        prompt = (
            f"Title: {title}\n"
            f"Description: {description}\n\n"
            f"Data to visualize:\n"
            f"{json.dumps(data, ensure_ascii=False, indent=2)}\n\n"
            f"Generate the Mermaid code for a {viz_type} diagram."
        )

        start = time.monotonic()
        last_error: Optional[Exception] = None

        for attempt in range(3):
            try:
                message = await self._client.messages.create(
                    model=MODEL_SONNET,
                    max_tokens=MAX_TOKENS,
                    system=system,
                    messages=[
                        {"role": "user", "content": prompt},
                    ],
                )
                break
            except anthropic.APIStatusError as exc:
                last_error = exc
                logger.warning(
                    "Claude call attempt %d/%d failed (status %d): %s",
                    attempt + 1,
                    3,
                    exc.status_code,
                    exc.message,
                )
                if exc.status_code == 429 or exc.status_code >= 500:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
            except anthropic.APIConnectionError as exc:
                last_error = exc
                logger.warning(
                    "Claude connection attempt %d/%d failed: %s",
                    attempt + 1,
                    3,
                    exc,
                )
                if attempt < 2:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
        else:
            raise RuntimeError(
                f"Claude call failed after 3 attempts: {last_error}"
            ) from last_error

        latency_ms = (time.monotonic() - start) * 1000

        # Extract usage
        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens
        cost = calc_cost(MODEL_SONNET, input_tokens, output_tokens)

        self.usage.add(UsageRecord(
            model=MODEL_SONNET,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=round(latency_ms, 1),
            phase="mermaid_generation",
        ))

        # Extract text content
        text_parts = []
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
        raw_text = "\n".join(text_parts)

        return _extract_mermaid(raw_text)

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
        """Clear all usage records."""
        self.usage.records.clear()
