"""
Sasoo - Visualization Router

Determines visualization targets from Phase 3-4 analysis results and routes
them to the appropriate renderer:
  - Text/structural based  -> Mermaid (Claude Sonnet 4.5)
  - Physical/visual based  -> PaperBanana (Gemini Pro Image)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & Data Classes
# ---------------------------------------------------------------------------

class RenderTarget(str, Enum):
    """Where the visualization should be rendered."""
    MERMAID = "mermaid"
    PAPERBANANA = "paperbanana"


class DiagramCategory(str, Enum):
    """High-level category that drives routing decisions."""
    # Mermaid targets (text/structural)
    EXPERIMENTAL_PROTOCOL = "experimental_protocol"
    ALGORITHM_FLOW = "algorithm_flow"
    SIGNAL_FLOW = "signal_flow"
    SYSTEM_ARCHITECTURE = "system_architecture"
    COMPONENT_RELATIONSHIPS = "component_relationships"
    TIMELINE = "timeline"
    COMPARISON = "comparison"

    # PaperBanana targets (physical/visual)
    EQUIPMENT_APPEARANCE = "equipment_appearance"
    OPTICAL_TABLE_LAYOUT = "optical_table_layout"
    CELL_MOLECULE_SCHEMATIC = "cell_molecule_schematic"
    PHYSICAL_SETUP = "physical_setup"
    CONCEPTUAL_ILLUSTRATION = "conceptual_illustration"


# Routing table: category -> render target
_ROUTING_TABLE: dict[DiagramCategory, RenderTarget] = {
    # Text/structural -> Mermaid
    DiagramCategory.EXPERIMENTAL_PROTOCOL: RenderTarget.MERMAID,
    DiagramCategory.ALGORITHM_FLOW: RenderTarget.MERMAID,
    DiagramCategory.SIGNAL_FLOW: RenderTarget.MERMAID,
    DiagramCategory.SYSTEM_ARCHITECTURE: RenderTarget.MERMAID,
    DiagramCategory.COMPONENT_RELATIONSHIPS: RenderTarget.MERMAID,
    DiagramCategory.TIMELINE: RenderTarget.MERMAID,
    DiagramCategory.COMPARISON: RenderTarget.MERMAID,
    # Physical/visual -> PaperBanana
    DiagramCategory.EQUIPMENT_APPEARANCE: RenderTarget.PAPERBANANA,
    DiagramCategory.OPTICAL_TABLE_LAYOUT: RenderTarget.PAPERBANANA,
    DiagramCategory.CELL_MOLECULE_SCHEMATIC: RenderTarget.PAPERBANANA,
    DiagramCategory.PHYSICAL_SETUP: RenderTarget.PAPERBANANA,
    DiagramCategory.CONCEPTUAL_ILLUSTRATION: RenderTarget.PAPERBANANA,
}

# Keyword heuristics for category classification when LLM routing is unavailable
_MERMAID_KEYWORDS: list[str] = [
    "protocol", "procedure", "step", "workflow", "algorithm", "pipeline",
    "data flow", "signal flow", "sequence", "architecture", "component",
    "relationship", "connection", "dependency", "hierarchy", "timeline",
    "phase", "stage", "process", "flowchart", "decision", "branch",
]

_PAPERBANANA_KEYWORDS: list[str] = [
    "appearance", "photo", "3d", "layout", "setup", "bench",
    "optical table", "equipment", "cell", "molecule", "schematic",
    "illustration", "diagram", "physical", "structure", "morphology",
    "device", "fabrication", "cross-section", "top view", "side view",
]


@dataclass
class SourceRef:
    """Reference back to the original paper location."""
    page: Optional[int] = None
    section: Optional[str] = None


@dataclass
class DiagramNode:
    """A node in a structural diagram."""
    id: str
    label: str
    detail: str = ""


@dataclass
class DiagramEdge:
    """An edge connecting two nodes."""
    from_id: str
    to_id: str
    label: str = ""


@dataclass
class VizTarget:
    """A single visualization target identified by the router."""
    type: str  # flowchart, sequence, class, state, conceptual, etc.
    title: str
    render_target: str  # "mermaid" or "paperbanana"
    category: str = ""
    description: str = ""
    nodes: list[dict[str, str]] = field(default_factory=list)
    edges: list[dict[str, str]] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "title": self.title,
            "render_target": self.render_target,
            "category": self.category,
            "description": self.description,
            "nodes": self.nodes,
            "edges": self.edges,
            "source": self.source,
        }


@dataclass
class VizRouterOutput:
    """Complete output from the visualization router."""
    paper_id: int
    diagrams: list[VizTarget] = field(default_factory=list)

    @property
    def mermaid_targets(self) -> list[VizTarget]:
        return [d for d in self.diagrams if d.render_target == RenderTarget.MERMAID.value]

    @property
    def paperbanana_targets(self) -> list[VizTarget]:
        return [d for d in self.diagrams if d.render_target == RenderTarget.PAPERBANANA.value]

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "diagrams": [d.to_dict() for d in self.diagrams],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# VizRouter
# ---------------------------------------------------------------------------

class VizRouter:
    """
    Determines visualization targets from Phase 3-4 analysis results and
    routes each to either Mermaid (text/structural) or PaperBanana
    (physical/visual) renderer.

    Supports two modes:
      1. LLM-assisted routing: pass analysis text to Gemini Pro to identify
         visualization candidates and classify them.
      2. Heuristic routing: parse structured analysis results (recipe, deep
         dive) using keyword matching when LLM is unavailable.
    """

    def __init__(self, gemini_client: Any = None):
        """
        Args:
            gemini_client: Optional GeminiClient for LLM-assisted routing.
                           If None, falls back to heuristic routing.
        """
        self._gemini = gemini_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def route(
        self,
        paper_id: int,
        recipe_result: Optional[dict] = None,
        deep_dive_result: Optional[dict] = None,
        screening_result: Optional[dict] = None,
        visual_result: Optional[dict] = None,
    ) -> VizRouterOutput:
        """
        Analyze Phase 3-4 results and identify visualization targets.

        Args:
            paper_id: ID of the paper being analyzed.
            recipe_result: Phase 3 recipe extraction result dict.
            deep_dive_result: Phase 4 deep dive analysis result dict.
            screening_result: Phase 1 screening result dict (optional, for context).
            visual_result: Phase 2 visual result dict (optional, for context).

        Returns:
            VizRouterOutput with categorized diagram targets.
        """
        output = VizRouterOutput(paper_id=paper_id)

        # Attempt LLM-assisted routing first
        if self._gemini is not None:
            try:
                llm_targets = await self._route_with_llm(
                    recipe_result=recipe_result,
                    deep_dive_result=deep_dive_result,
                )
                if llm_targets:
                    output.diagrams = llm_targets
                    logger.info(
                        "VizRouter: LLM routing identified %d targets for paper %d",
                        len(llm_targets), paper_id,
                    )
                    return output
            except Exception as exc:
                logger.warning(
                    "VizRouter: LLM routing failed, falling back to heuristic: %s", exc
                )

        # Fallback: heuristic routing
        heuristic_targets = self._route_heuristic(
            recipe_result=recipe_result,
            deep_dive_result=deep_dive_result,
        )
        output.diagrams = heuristic_targets
        logger.info(
            "VizRouter: Heuristic routing identified %d targets for paper %d",
            len(heuristic_targets), paper_id,
        )
        return output

    # ------------------------------------------------------------------
    # LLM-assisted routing
    # ------------------------------------------------------------------

    async def _route_with_llm(
        self,
        recipe_result: Optional[dict],
        deep_dive_result: Optional[dict],
    ) -> list[VizTarget]:
        """Use Gemini Pro to identify and classify visualization targets."""

        # Build context from results
        context_parts: list[str] = []
        if recipe_result:
            context_parts.append(
                "=== Recipe Extraction (Phase 3) ===\n"
                + json.dumps(recipe_result, ensure_ascii=False, indent=2)
            )
        if deep_dive_result:
            context_parts.append(
                "=== Deep Dive Analysis (Phase 4) ===\n"
                + json.dumps(deep_dive_result, ensure_ascii=False, indent=2)
            )

        if not context_parts:
            return []

        context = "\n\n".join(context_parts)

        prompt = f"""You are a Visualization Router for a research paper analysis system.

Given the analysis results below, identify ALL elements that would benefit from
a diagram or illustration. For each, classify it into one of two rendering targets:

MERMAID targets (text/structural diagrams -- flowcharts, sequences, architectures):
- Experimental protocol / procedure steps
- Algorithm or data flow
- Signal flow diagrams
- System architecture
- Component relationships / dependencies
- Timelines

PAPERBANANA targets (physical/visual illustrations):
- Equipment appearance or internal structure
- Optical table / lab bench 3D layout
- Cell / molecule schematic
- Physical setup that needs a realistic illustration
- Conceptual illustrations requiring artistic rendering

For each target output a JSON object with:
- "type": diagram type (flowchart, sequence, class, state, conceptual, illustration)
- "title": short descriptive title
- "render_target": "mermaid" or "paperbanana"
- "category": one of [{', '.join(c.value for c in DiagramCategory)}]
- "description": 2-3 sentence description of what to visualize
- "nodes": list of {{"id": "...", "label": "...", "detail": "..."}} (for mermaid targets)
- "edges": list of {{"from": "...", "to": "...", "label": "..."}} (for mermaid targets)
- "source": {{"page": <int or null>, "section": "<section name>"}}

Return a JSON object: {{"diagrams": [<list of diagram objects>]}}
Return ONLY valid JSON. No markdown fences, no explanation.

--- Analysis Results ---
{context}
"""

        response = await self._gemini.generate(
            prompt=prompt,
            model="gemini-3-pro-preview",
            temperature=0.3,
            response_mime_type="application/json",
        )

        return self._parse_llm_response(response)

    def _parse_llm_response(self, response: Any) -> list[VizTarget]:
        """Parse the LLM JSON response into VizTarget objects."""
        try:
            # Handle both string and dict responses
            if isinstance(response, str):
                data = json.loads(response)
            elif isinstance(response, dict):
                data = response
            else:
                # Try to extract text from response object
                text = getattr(response, "text", str(response))
                # Strip markdown fences if present
                text = text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text.rsplit("```", 1)[0]
                text = text.strip()
                data = json.loads(text)

            diagrams_raw = data.get("diagrams", [])
            targets: list[VizTarget] = []

            for d in diagrams_raw:
                render_target = d.get("render_target", "mermaid")
                if render_target not in ("mermaid", "paperbanana"):
                    render_target = self._classify_render_target(
                        d.get("category", ""),
                        d.get("description", ""),
                    )

                targets.append(VizTarget(
                    type=d.get("type", "flowchart"),
                    title=d.get("title", "Untitled Diagram"),
                    render_target=render_target,
                    category=d.get("category", ""),
                    description=d.get("description", ""),
                    nodes=d.get("nodes", []),
                    edges=d.get("edges", []),
                    source=d.get("source", {}),
                ))

            return targets

        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            logger.warning("VizRouter: Failed to parse LLM response: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Heuristic routing
    # ------------------------------------------------------------------

    def _route_heuristic(
        self,
        recipe_result: Optional[dict],
        deep_dive_result: Optional[dict],
    ) -> list[VizTarget]:
        """
        Heuristic routing: extract visualization targets from structured
        analysis results using keyword matching and structural analysis.
        """
        targets: list[VizTarget] = []

        # --- Recipe result (Phase 3) ---
        if recipe_result:
            targets.extend(self._extract_recipe_viz_targets(recipe_result))

        # --- Deep dive result (Phase 4) ---
        if deep_dive_result:
            targets.extend(self._extract_deep_dive_viz_targets(deep_dive_result))

        return targets

    def _extract_recipe_viz_targets(self, recipe: dict) -> list[VizTarget]:
        """Extract visualization targets from Phase 3 recipe result."""
        targets: list[VizTarget] = []

        # 1. Experimental protocol flowchart (always generate if steps exist)
        recipe_card = recipe.get("recipe", recipe)
        steps = recipe_card.get("steps", [])
        if steps:
            nodes = []
            edges = []
            for i, step in enumerate(steps):
                node_id = chr(65 + i) if i < 26 else f"N{i}"
                label = step if isinstance(step, str) else str(step)
                # Truncate long labels
                if len(label) > 60:
                    label = label[:57] + "..."
                nodes.append({"id": node_id, "label": label, "detail": ""})
                if i > 0:
                    prev_id = chr(65 + i - 1) if (i - 1) < 26 else f"N{i-1}"
                    edges.append({"from": prev_id, "to": node_id, "label": "sequential"})

            targets.append(VizTarget(
                type="flowchart",
                title="Experimental Protocol",
                render_target=RenderTarget.MERMAID.value,
                category=DiagramCategory.EXPERIMENTAL_PROTOCOL.value,
                description="Step-by-step experimental protocol extracted from the Methods section.",
                nodes=nodes,
                edges=edges,
                source={"page": None, "section": "Method"},
            ))

        # 2. Equipment / setup illustration (PaperBanana)
        equipment = recipe_card.get("equipment", [])
        materials = recipe_card.get("materials", [])
        if equipment:
            desc_parts = ["Equipment and setup: " + ", ".join(equipment[:10])]
            if materials:
                desc_parts.append("Materials: " + ", ".join(materials[:10]))
            targets.append(VizTarget(
                type="conceptual",
                title="Experimental Setup",
                render_target=RenderTarget.PAPERBANANA.value,
                category=DiagramCategory.PHYSICAL_SETUP.value,
                description=" ".join(desc_parts),
                source={"page": None, "section": "Method"},
            ))

        # 3. Parameter relationship diagram (if many parameters)
        parameters = recipe_card.get("parameters", [])
        if len(parameters) >= 4:
            nodes = []
            for i, param in enumerate(parameters[:12]):
                p = param if isinstance(param, dict) else {"name": str(param), "value": ""}
                node_id = f"P{i}"
                label = p.get("name", f"Param{i}")
                detail = p.get("value", "")
                if p.get("unit"):
                    detail += f" {p['unit']}"
                nodes.append({"id": node_id, "label": label, "detail": detail})

            targets.append(VizTarget(
                type="flowchart",
                title="Key Parameters Overview",
                render_target=RenderTarget.MERMAID.value,
                category=DiagramCategory.COMPONENT_RELATIONSHIPS.value,
                description="Overview of key experimental parameters and their values.",
                nodes=nodes,
                edges=[],
                source={"page": None, "section": "Method"},
            ))

        return targets

    def _extract_deep_dive_viz_targets(self, deep_dive: dict) -> list[VizTarget]:
        """Extract visualization targets from Phase 4 deep dive result."""
        targets: list[VizTarget] = []

        # 1. Research logic / motivation flow
        analysis_text = deep_dive.get("detailed_analysis", "")
        if analysis_text and len(analysis_text) > 100:
            # Build a simple motivation -> method -> result flow
            nodes = [
                {"id": "M", "label": "Research Motivation", "detail": ""},
                {"id": "A", "label": "Approach / Method", "detail": ""},
                {"id": "R", "label": "Key Results", "detail": ""},
                {"id": "C", "label": "Conclusions", "detail": ""},
            ]
            edges = [
                {"from": "M", "to": "A", "label": "leads to"},
                {"from": "A", "to": "R", "label": "produces"},
                {"from": "R", "to": "C", "label": "supports"},
            ]

            # Add strengths/weaknesses as branches if available
            strengths = deep_dive.get("strengths", [])
            weaknesses = deep_dive.get("weaknesses", [])
            if strengths:
                nodes.append({"id": "S", "label": "Strengths", "detail": "; ".join(strengths[:3])})
                edges.append({"from": "R", "to": "S", "label": ""})
            if weaknesses:
                nodes.append({"id": "W", "label": "Weaknesses", "detail": "; ".join(weaknesses[:3])})
                edges.append({"from": "R", "to": "W", "label": ""})

            targets.append(VizTarget(
                type="flowchart",
                title="Research Logic Flow",
                render_target=RenderTarget.MERMAID.value,
                category=DiagramCategory.ALGORITHM_FLOW.value,
                description="High-level flow of the research: motivation, approach, results, conclusions.",
                nodes=nodes,
                edges=edges,
                source={"page": None, "section": "Introduction + Results"},
            ))

        # 2. Prior work comparison (if available)
        comparison = deep_dive.get("comparison_to_prior_work", "")
        if comparison and len(comparison) > 50:
            targets.append(VizTarget(
                type="conceptual",
                title="Prior Work Comparison",
                render_target=RenderTarget.MERMAID.value,
                category=DiagramCategory.COMPARISON.value,
                description=f"Comparison with prior work: {comparison[:200]}",
                nodes=[],
                edges=[],
                source={"page": None, "section": "Introduction"},
            ))

        return targets

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _classify_render_target(self, category: str, description: str) -> str:
        """Classify render target from category string and description text."""
        combined = (category + " " + description).lower()

        # Check against known categories first
        for cat in DiagramCategory:
            if cat.value == category:
                return _ROUTING_TABLE.get(cat, RenderTarget.MERMAID).value

        # Keyword-based fallback
        pb_score = sum(1 for kw in _PAPERBANANA_KEYWORDS if kw in combined)
        mm_score = sum(1 for kw in _MERMAID_KEYWORDS if kw in combined)

        if pb_score > mm_score:
            return RenderTarget.PAPERBANANA.value
        return RenderTarget.MERMAID.value
