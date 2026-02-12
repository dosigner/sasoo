"""
Sasoo - PaperBanana Bridge

Bridges the VizRouter output to the PaperBanana package for generating
publication-quality scientific illustrations using Gemini Pro Image.

If paperbanana is not installed, degrades gracefully (returns None with warning).
"""

from __future__ import annotations

import logging
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PyInstaller _MEIPASS detection
# ---------------------------------------------------------------------------

_IS_FROZEN = getattr(sys, "frozen", False)
_MEIPASS = Path(getattr(sys, "_MEIPASS", "")) if _IS_FROZEN else None

# ---------------------------------------------------------------------------
# Attempt to import paperbanana (optional dependency)
# ---------------------------------------------------------------------------

_PAPERBANANA_AVAILABLE = False
_PaperBananaPipeline = None
_GenerationInput = None
_DiagramType = None
_IMPORT_ERROR_DETAIL = ""

try:
    from paperbanana import PaperBananaPipeline, GenerationInput, DiagramType
    from paperbanana.core.config import Settings as PaperBananaSettings

    _PaperBananaPipeline = PaperBananaPipeline
    _GenerationInput = GenerationInput
    _DiagramType = DiagramType
    _PaperBananaSettings = PaperBananaSettings
    _PAPERBANANA_AVAILABLE = True
    logger.info("PaperBanana package is available (frozen=%s).", _IS_FROZEN)
except ImportError as _import_err:
    _PaperBananaSettings = None
    _IMPORT_ERROR_DETAIL = f"{_import_err}\n{traceback.format_exc()}"
    logger.warning(
        "PaperBanana package import failed: %s. "
        "Install with: pip install paperbanana. "
        "PaperBanana illustrations will be unavailable.\n"
        "Full traceback: %s",
        _import_err,
        traceback.format_exc(),
    )
except Exception as _exc:
    # Catch non-ImportError exceptions (e.g. AttributeError in transitive imports)
    _PaperBananaSettings = None
    _IMPORT_ERROR_DETAIL = f"{_exc}\n{traceback.format_exc()}"
    logger.warning(
        "PaperBanana package import failed with unexpected error: %s\n%s",
        _exc,
        traceback.format_exc(),
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
        self._last_api_key: str = ""
        logger.info(
            "PaperBananaBridge: Created. Package available: %s",
            _PAPERBANANA_AVAILABLE,
        )

    def _ensure_pipeline(self) -> bool:
        """Lazily initialize the pipeline with the current API key.

        This is called before each generation so that API keys loaded from
        the database after app startup are picked up correctly (production
        mode loads keys from DB in the lifespan handler, which runs after
        module-level imports).
        """
        import os

        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""

        # Already initialized with the same key
        if self._pipeline is not None and api_key == self._last_api_key:
            return True

        if not api_key:
            logger.warning(
                "PaperBananaBridge: No API key available "
                "(GEMINI_API_KEY=%s, GOOGLE_API_KEY=%s, frozen=%s)",
                bool(os.environ.get("GEMINI_API_KEY")),
                bool(os.environ.get("GOOGLE_API_KEY")),
                _IS_FROZEN,
            )
            return False

        if not (_PAPERBANANA_AVAILABLE and _PaperBananaPipeline is not None and _PaperBananaSettings is not None):
            logger.warning(
                "PaperBananaBridge: Package not available "
                "(available=%s, pipeline_cls=%s, settings_cls=%s, import_err=%s)",
                _PAPERBANANA_AVAILABLE,
                _PaperBananaPipeline is not None,
                _PaperBananaSettings is not None,
                _IMPORT_ERROR_DETAIL[:200] if _IMPORT_ERROR_DETAIL else "none",
            )
            return False

        try:
            settings = _PaperBananaSettings(google_api_key=api_key)
            self._pipeline = _PaperBananaPipeline(settings=settings)
            self._last_api_key = api_key

            # --- PyInstaller fix: patch prompt_dir for frozen executables ---
            if _IS_FROZEN and _MEIPASS is not None:
                meipass_prompts = _MEIPASS / "prompts"
                if meipass_prompts.exists():
                    prompt_dir_str = str(meipass_prompts)
                    # Patch all agents to use the _MEIPASS prompts directory
                    for agent_name in ("retriever", "planner", "stylist", "visualizer", "critic"):
                        agent = getattr(self._pipeline, agent_name, None)
                        if agent is not None:
                            agent.prompt_dir = Path(prompt_dir_str)
                    logger.info(
                        "PaperBananaBridge: Patched agent prompt_dir to %s",
                        prompt_dir_str,
                    )
                else:
                    logger.warning(
                        "PaperBananaBridge: _MEIPASS/prompts not found at %s",
                        meipass_prompts,
                    )

                # Also patch reference_set_path and guidelines if available
                meipass_data = _MEIPASS / "data"
                if meipass_data.exists():
                    ref_path = meipass_data / "reference_sets"
                    if ref_path.exists() and hasattr(self._pipeline, "reference_store"):
                        self._pipeline.reference_store.path = ref_path
                        self._pipeline.reference_store._loaded = False
                        logger.info("PaperBananaBridge: Patched reference_store path to %s", ref_path)

            logger.info(
                "PaperBananaBridge: Pipeline initialized successfully "
                "(frozen=%s, api_key_len=%d)",
                _IS_FROZEN, len(api_key),
            )
            return True
        except Exception as exc:
            logger.warning(
                "PaperBananaBridge: Failed to initialize pipeline: %s\n%s",
                exc, traceback.format_exc(),
            )
            self._pipeline = None
            return False

    @property
    def is_available(self) -> bool:
        """Return True if PaperBanana is installed and pipeline can be initialized."""
        return self._ensure_pipeline()

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
        if not self._ensure_pipeline():
            logger.warning(
                "PaperBananaBridge: Pipeline not ready (pipeline=%s, pkg_available=%s). "
                "Cannot generate illustration for '%s'.",
                self._pipeline,
                _PAPERBANANA_AVAILABLE,
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
                "PaperBananaBridge: Failed to generate illustration '%s': %s\nTraceback: %s",
                title, exc, traceback.format_exc(),
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
