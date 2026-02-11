"""
Sasoo - Base Agent
Abstract base class for domain-specific analysis agents.

Each agent provides domain-tailored prompts for the 4-phase analysis pipeline:
  Phase 1: Screening   - quick triage and relevance check
  Phase 2: Visual      - figure/graph analysis guidance
  Phase 3: Recipe      - methodology/parameter extraction
  Phase 4: DeepDive    - critical claim-vs-evidence evaluation

Agents also define which domain-specific parameters to extract in Phase 3.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentInfo:
    """Metadata about a domain agent."""
    name: str                    # Internal identifier (e.g., "photon")
    domain: str                  # Domain key (e.g., "optics")
    display_name: str            # Human-readable name
    display_name_ko: str         # Korean display name
    description: str             # What this agent specializes in
    description_ko: str          # Korean description
    personality: str             # Personality/tone description
    icon: str = ""               # UI icon identifier


class BaseAgent(ABC):
    """
    Abstract base class for all domain-specific analysis agents.

    Subclasses MUST implement:
      - info (property): Return AgentInfo with agent metadata.
      - get_screening_prompt(): Phase 1 prompt overlay.
      - get_visual_prompt(): Phase 2 prompt overlay.
      - get_recipe_prompt(): Phase 3 prompt overlay.
      - get_deepdive_prompt(): Phase 4 prompt overlay.
      - get_recipe_parameters(): Domain-specific parameters to extract.

    Usage:
        agent = AgentPhoton()
        prompt = agent.get_screening_prompt()
        # Pass prompt to GeminiClient as agent_prompt parameter
    """

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def info(self) -> AgentInfo:
        """Return agent metadata."""
        ...

    @property
    def name(self) -> str:
        """Agent internal name."""
        return self.info.name

    @property
    def domain(self) -> str:
        """Domain key this agent handles."""
        return self.info.domain

    @property
    def description(self) -> str:
        """Agent description."""
        return self.info.description

    # ------------------------------------------------------------------
    # Abstract methods: Phase prompts
    # ------------------------------------------------------------------

    @abstractmethod
    def get_screening_prompt(self) -> str:
        """
        Return the Phase 1 (Screening) prompt overlay.

        This prompt is appended to the base system prompt when calling
        Gemini Flash for initial paper triage. It should instruct the
        model to focus on domain-specific indicators.

        Returns:
            Domain-specific screening instructions as a string.
        """
        ...

    @abstractmethod
    def get_visual_prompt(self) -> str:
        """
        Return the Phase 2 (Visual Analysis) prompt overlay.

        This prompt guides the multimodal figure analysis, telling
        the model what to look for in domain-specific graphs, images,
        and diagrams.

        Returns:
            Domain-specific visual analysis instructions as a string.
        """
        ...

    @abstractmethod
    def get_recipe_prompt(self) -> str:
        """
        Return the Phase 3 (Recipe Extraction) prompt overlay.

        This prompt tells the model which domain-specific parameters
        to extract from the methods section and how to tag them
        (EXPLICIT/INFERRED/MISSING).

        Returns:
            Domain-specific recipe extraction instructions as a string.
        """
        ...

    @abstractmethod
    def get_deepdive_prompt(self) -> str:
        """
        Return the Phase 4 (DeepDive) prompt overlay.

        This prompt guides deep critical analysis, including
        domain-specific error propagation checks, physical constraint
        validation, and claim-vs-evidence evaluation criteria.

        Returns:
            Domain-specific deep analysis instructions as a string.
        """
        ...

    @abstractmethod
    def get_recipe_parameters(self) -> list[str]:
        """
        Return a list of domain-specific parameter names to extract
        during Phase 3 (Recipe Extraction).

        These are the key experimental parameters that must be captured
        for this domain. Each parameter should be a short identifier
        (e.g., "wavelength", "beam_quality").

        Returns:
            List of parameter name strings.
        """
        ...

    # ------------------------------------------------------------------
    # Utility methods (shared by all agents)
    # ------------------------------------------------------------------

    # Korean output instruction prepended to all phase prompts
    _OUTPUT_LANG_INSTRUCTION = (
        "[OUTPUT LANGUAGE] Always respond in casual Korean (반말). "
        "Use a conversational, senior-researcher tone. "
        "Technical terms may remain in English.\n\n"
    )

    def get_system_prompt(self, phase: str) -> str:
        """
        Return the prompt for a given phase name.
        This is the primary dispatcher used by AnalysisPipeline.
        Prepends Korean output language instruction to all prompts.
        """
        prompts = self.get_all_prompts()
        # Normalize phase name (deep_dive -> deepdive)
        normalized = phase.replace("_", "")
        for key, value in prompts.items():
            if key.replace("_", "") == normalized:
                return self._OUTPUT_LANG_INSTRUCTION + value
        # Fallback
        raw = prompts.get(phase, "")
        return self._OUTPUT_LANG_INSTRUCTION + raw if raw else ""

    def get_all_prompts(self) -> dict[str, str]:
        """Return all phase prompts as a dict."""
        return {
            "screening": self.get_screening_prompt(),
            "visual": self.get_visual_prompt(),
            "recipe": self.get_recipe_prompt(),
            "deepdive": self.get_deepdive_prompt(),
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize agent info to dict."""
        info = self.info
        return {
            "name": info.name,
            "domain": info.domain,
            "display_name": info.display_name,
            "display_name_ko": info.display_name_ko,
            "description": info.description,
            "description_ko": info.description_ko,
            "personality": info.personality,
            "icon": info.icon,
            "recipe_parameters": self.get_recipe_parameters(),
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} domain={self.domain!r}>"
