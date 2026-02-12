"""
Sasoo - PaperBanana Bridge

Bridges the VizRouter output to the PaperBanana package for generating
publication-quality scientific illustrations using Gemini Pro Image.

If paperbanana is not installed, degrades gracefully (returns None with warning).
"""

from __future__ import annotations

import logging
import os
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

print(f"[PaperBanana] Module loading: frozen={_IS_FROZEN}, MEIPASS={_MEIPASS}")

# ---------------------------------------------------------------------------
# Step-by-step import of paperbanana (optional dependency)
# ---------------------------------------------------------------------------

_PAPERBANANA_AVAILABLE = False
_PaperBananaPipeline = None
_GenerationInput = None
_DiagramType = None
_PaperBananaSettings = None
_IMPORT_ERROR_DETAIL = ""


def _try_import_paperbanana() -> bool:
    """Import paperbanana with step-by-step diagnostics.

    Returns True if all imports succeed, False otherwise.
    Sets module-level _PAPERBANANA_AVAILABLE and related globals.
    """
    global _PAPERBANANA_AVAILABLE, _PaperBananaPipeline, _GenerationInput
    global _DiagramType, _PaperBananaSettings, _IMPORT_ERROR_DETAIL

    steps: list[str] = []

    try:
        # Step 1: Core dependencies
        import structlog  # noqa: F401
        steps.append("structlog OK")

        import yaml  # noqa: F401
        steps.append("yaml OK")

        from pydantic_settings import BaseSettings  # noqa: F401
        steps.append("pydantic_settings OK")

        from tenacity import retry  # noqa: F401
        steps.append("tenacity OK")

        # Step 2: PaperBanana core types (lightest import)
        from paperbanana.core.types import DiagramType, GenerationInput
        steps.append("core.types OK")

        # Step 3: PaperBanana config
        from paperbanana.core.config import Settings as PBSettings
        steps.append("core.config OK")

        # Step 4: Full pipeline (pulls in agents, providers, etc.)
        from paperbanana import PaperBananaPipeline
        steps.append("PaperBananaPipeline OK")

        # All imports succeeded
        _PaperBananaPipeline = PaperBananaPipeline
        _GenerationInput = GenerationInput
        _DiagramType = DiagramType
        _PaperBananaSettings = PBSettings
        _PAPERBANANA_AVAILABLE = True

        print(f"[PaperBanana] Import SUCCESS: {' -> '.join(steps)}")
        logger.info("PaperBanana package is available (frozen=%s).", _IS_FROZEN)
        return True

    except Exception as exc:
        _IMPORT_ERROR_DETAIL = f"{exc}\n{traceback.format_exc()}"
        print(
            f"[PaperBanana] Import FAILED at step [{' -> '.join(steps)}]: "
            f"{exc.__class__.__name__}: {exc}"
        )
        logger.warning(
            "PaperBanana import failed: steps=%s, error=%s",
            steps, exc,
        )
        return False


_try_import_paperbanana()


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
        self.last_error: str = ""  # Expose failure reason for diagnostics

    def _ensure_pipeline(self) -> bool:
        """Lazily initialize the pipeline with the current API key.

        This is called before each generation so that API keys loaded from
        the database after app startup are picked up correctly (production
        mode loads keys from DB in the lifespan handler, which runs after
        module-level imports).
        """
        self.last_error = ""

        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""

        # Already initialized with the same key
        if self._pipeline is not None and api_key == self._last_api_key:
            return True

        if not api_key:
            self.last_error = (
                f"No API key (GEMINI={bool(os.environ.get('GEMINI_API_KEY'))}, "
                f"GOOGLE={bool(os.environ.get('GOOGLE_API_KEY'))})"
            )
            print(f"[PaperBanana] {self.last_error}")
            return False

        if not _PAPERBANANA_AVAILABLE:
            self.last_error = (
                f"Import failed: {_IMPORT_ERROR_DETAIL[:300]}"
            )
            print(f"[PaperBanana] {self.last_error}")
            return False

        if _PaperBananaPipeline is None or _PaperBananaSettings is None:
            self.last_error = (
                f"Package partially loaded (pipeline={_PaperBananaPipeline is not None}, "
                f"settings={_PaperBananaSettings is not None})"
            )
            print(f"[PaperBanana] {self.last_error}")
            return False

        try:
            # Build settings — in frozen mode, use absolute MEIPASS paths
            # so PaperBanana finds its data files inside _internal/
            settings_kwargs: dict[str, Any] = {"google_api_key": api_key}

            if _IS_FROZEN and _MEIPASS is not None:
                meipass_str = str(_MEIPASS)
                ref_path = str(_MEIPASS / "data" / "reference_sets")
                guide_path = str(_MEIPASS / "data" / "guidelines")
                out_path = str(_MEIPASS / "outputs")

                settings_kwargs["reference_set_path"] = ref_path
                settings_kwargs["guidelines_path"] = guide_path
                settings_kwargs["output_dir"] = out_path

                print(
                    f"[PaperBanana] Frozen mode: MEIPASS={meipass_str}, "
                    f"ref={ref_path}, guide={guide_path}, out={out_path}"
                )

            settings = _PaperBananaSettings(**settings_kwargs)
            print(f"[PaperBanana] Settings created (api_key_len={len(api_key)})")

            self._pipeline = _PaperBananaPipeline(settings=settings)
            self._last_api_key = api_key
            print(f"[PaperBanana] Pipeline created OK")

            # --- PyInstaller fix: patch prompt_dir for frozen executables ---
            if _IS_FROZEN and _MEIPASS is not None:
                meipass_prompts = _MEIPASS / "prompts"
                if meipass_prompts.exists():
                    # Patch all agents to use the _MEIPASS prompts directory
                    patched = []
                    for agent_name in ("retriever", "planner", "stylist", "visualizer", "critic"):
                        agent = getattr(self._pipeline, agent_name, None)
                        if agent is not None:
                            agent.prompt_dir = meipass_prompts
                            patched.append(agent_name)
                    print(f"[PaperBanana] Patched prompt_dir for agents: {patched}")
                else:
                    print(f"[PaperBanana] WARNING: prompts not found at {meipass_prompts}")

                # Patch reference_store path
                meipass_refs = _MEIPASS / "data" / "reference_sets"
                if meipass_refs.exists() and hasattr(self._pipeline, "reference_store"):
                    self._pipeline.reference_store.path = meipass_refs
                    self._pipeline.reference_store._loaded = False
                    print(f"[PaperBanana] Patched reference_store to {meipass_refs}")

            print(
                f"[PaperBanana] Pipeline ready (frozen={_IS_FROZEN}, "
                f"key_len={len(api_key)})"
            )
            return True

        except Exception as exc:
            self.last_error = f"Pipeline init failed: {exc}"
            print(f"[PaperBanana] {self.last_error}")
            print(f"[PaperBanana] Traceback: {traceback.format_exc()}")
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
            print(
                f"[PaperBanana] Pipeline not ready for '{viz_target.get('title', '?')}': "
                f"{self.last_error}"
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

            print(f"[PaperBanana] Generating '{title}' (type={diagram_type})...")
            result = await self._pipeline.generate(generation_input)

            # Copy result image to paper directory
            save_path = self._save_image(result, title, paper_dir)
            print(f"[PaperBanana] Generated '{title}' -> {save_path}")
            return save_path

        except Exception as exc:
            self.last_error = f"Generation failed: {exc}"
            print(f"[PaperBanana] {self.last_error}")
            logger.error(
                "PaperBananaBridge: Failed to generate '%s': %s\n%s",
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
                "PaperBananaBridge: Could not extract image from result. "
                "Type: %s, attrs: %s",
                type(result).__name__,
                dir(result),
            )
            return ""

        return str(save_path)
