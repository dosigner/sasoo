"""
Sasoo - PaperBanana Bridge

Bridges the VizRouter output to the PaperBanana package for generating
publication-quality scientific illustrations using Gemini Pro Image.

If paperbanana is not installed, degrades gracefully (returns None with warning).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Attempt to import paperbanana (optional dependency)
# ---------------------------------------------------------------------------

_PAPERBANANA_AVAILABLE = False
_PaperBananaPipeline = None
_GenerationInput = None
_DiagramType = None

try:
    from paperbanana import PaperBananaPipeline, GenerationInput, DiagramType

    _PaperBananaPipeline = PaperBananaPipeline
    _GenerationInput = GenerationInput
    _DiagramType = DiagramType
    _PAPERBANANA_AVAILABLE = True
    logger.info("PaperBanana package is available.")
except ImportError:
    logger.warning(
        "PaperBanana package is not installed. "
        "Install with: pip install paperbanana. "
        "PaperBanana illustrations will be unavailable."
    )


# ---------------------------------------------------------------------------
# Diagram type mapping
# ---------------------------------------------------------------------------

# Map category strings from VizRouter to PaperBanana DiagramType enum values
_DIAGRAM_TYPE_MAP: dict[str, str] = {
    "equipment_appearance": "METHODOLOGY",
    "optical_table_layout": "METHODOLOGY",
    "cell_molecule_schematic": "BIOLOGICAL",
    "physical_setup": "METHODOLOGY",
    "conceptual_illustration": "CONCEPTUAL",
}


# ---------------------------------------------------------------------------
# PaperBananaBridge
# ---------------------------------------------------------------------------

class PaperBananaBridge:
    """
    Generates publication-quality illustrations using the PaperBanana package.

    Usage:
        bridge = PaperBananaBridge()
        if bridge.is_available:
            path = await bridge.generate_illustration(viz_target, paper_dir)
    """

    def __init__(self) -> None:
        self._pipeline = None
        if _PAPERBANANA_AVAILABLE and _PaperBananaPipeline is not None:
            try:
                self._pipeline = _PaperBananaPipeline()
            except Exception as exc:
                logger.warning(
                    "PaperBananaBridge: Failed to initialize pipeline: %s", exc
                )

    @property
    def is_available(self) -> bool:
        """Return True if PaperBanana is installed and pipeline is ready."""
        return self._pipeline is not None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_illustration(
        self,
        viz_target: dict[str, Any],
        paper_dir: str,
    ) -> Optional[str]:
        """
        Generate a PaperBanana illustration from a VizRouter target.

        Args:
            viz_target: VizTarget dict with render_target="paperbanana".
            paper_dir: Path to the paper's directory where the image will be saved.

        Returns:
            File path to the generated PNG image, or None if generation failed.
        """
        if not self.is_available:
            logger.warning(
                "PaperBananaBridge: Package not available. "
                "Cannot generate illustration for '%s'.",
                viz_target.get("title", "?"),
            )
            return None

        title = viz_target.get("title", "Illustration")
        description = viz_target.get("description", "")
        category = viz_target.get("category", "conceptual_illustration")

        # Resolve diagram type
        diagram_type = self._resolve_diagram_type(category)

        # Build source context and communicative intent
        source_context = self._build_source_context(viz_target)
        communicative_intent = self._build_intent(viz_target)

        try:
            generation_input = _GenerationInput(
                source_context=source_context,
                communicative_intent=communicative_intent,
                diagram_type=diagram_type,
            )

            result = await self._pipeline.generate(generation_input)

            # Copy result image to paper directory
            save_path = self._save_image(result, title, paper_dir)
            logger.info(
                "PaperBananaBridge: Generated illustration '%s' -> %s",
                title, save_path,
            )
            return save_path

        except Exception as exc:
            logger.error(
                "PaperBananaBridge: Failed to generate illustration '%s': %s",
                title, exc,
            )
            return None

    async def generate_batch(
        self,
        viz_targets: list[dict[str, Any]],
        paper_dir: str,
    ) -> list[Optional[str]]:
        """
        Generate illustrations for multiple VizRouter targets.

        Args:
            viz_targets: List of VizTarget dicts with render_target="paperbanana".
            paper_dir: Path to the paper's directory.

        Returns:
            List of file paths (or None for failed generations).
        """
        results: list[Optional[str]] = []
        for target in viz_targets:
            path = await self.generate_illustration(target, paper_dir)
            results.append(path)
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_diagram_type(self, category: str) -> Any:
        """Map category to PaperBanana DiagramType."""
        if _DiagramType is None:
            return None

        type_name = _DIAGRAM_TYPE_MAP.get(category, "METHODOLOGY")

        try:
            return getattr(_DiagramType, type_name)
        except AttributeError:
            logger.warning(
                "PaperBananaBridge: Unknown DiagramType '%s', using METHODOLOGY.",
                type_name,
            )
            return _DiagramType.METHODOLOGY

    def _build_source_context(self, viz_target: dict[str, Any]) -> str:
        """Build the source_context string for PaperBanana from the target."""
        parts: list[str] = []

        description = viz_target.get("description", "")
        if description:
            parts.append(description)

        # Include node details if available
        nodes = viz_target.get("nodes", [])
        if nodes:
            node_descriptions = []
            for node in nodes:
                label = node.get("label", "")
                detail = node.get("detail", "")
                if label:
                    node_desc = label
                    if detail:
                        node_desc += f" ({detail})"
                    node_descriptions.append(node_desc)
            if node_descriptions:
                parts.append("Components: " + ", ".join(node_descriptions))

        # Include edge relationships
        edges = viz_target.get("edges", [])
        if edges:
            edge_descriptions = []
            for edge in edges:
                from_id = edge.get("from", edge.get("from_id", "?"))
                to_id = edge.get("to", edge.get("to_id", "?"))
                label = edge.get("label", "connects to")
                edge_descriptions.append(f"{from_id} {label} {to_id}")
            if edge_descriptions:
                parts.append("Connections: " + "; ".join(edge_descriptions))

        return " | ".join(parts) if parts else "Scientific experimental setup"

    def _build_intent(self, viz_target: dict[str, Any]) -> str:
        """Build the communicative_intent string for PaperBanana."""
        title = viz_target.get("title", "Experimental Setup")
        category = viz_target.get("category", "")
        source = viz_target.get("source", {})
        section = source.get("section", "")

        intent = f"Publication-quality illustration of {title}."
        if category:
            intent += f" Category: {category.replace('_', ' ')}."
        if section:
            intent += f" Based on the {section} section of the paper."

        return intent

    def _save_image(
        self,
        result: Any,
        title: str,
        paper_dir: str,
    ) -> str:
        """Copy the generated image to the paper's paperbanana/ directory."""
        pb_dir = Path(paper_dir) / "paperbanana"
        pb_dir.mkdir(parents=True, exist_ok=True)

        # Build safe filename
        import re
        safe_title = re.sub(r"[^\w\s-]", "", title).strip()
        safe_title = re.sub(r"[-\s]+", "_", safe_title).lower()
        if not safe_title:
            safe_title = "illustration"

        save_path = pb_dir / f"{safe_title}.png"

        # Avoid overwriting
        counter = 1
        while save_path.exists():
            save_path = pb_dir / f"{safe_title}_{counter}.png"
            counter += 1

        # Copy from PaperBanana result
        source_path = getattr(result, "image_path", None)
        if source_path and Path(source_path).exists():
            shutil.copy2(str(source_path), str(save_path))
        elif hasattr(result, "image_bytes") and result.image_bytes:
            save_path.write_bytes(result.image_bytes)
        elif hasattr(result, "save"):
            result.save(str(save_path))
        else:
            logger.warning(
                "PaperBananaBridge: Could not extract image from result object. "
                "Result type: %s, attributes: %s",
                type(result).__name__,
                dir(result),
            )
            return ""

        return str(save_path)
