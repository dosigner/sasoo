"""
Sasoo - Markdown-based Agent
Unified agent implementation that loads from .md profile files.
Replaces all hardcoded agent classes (AgentPhoton, AgentCell, etc.).
"""

from __future__ import annotations

from services.agents.base_agent import AgentInfo, BaseAgent
from services.agents.md_loader import AgentProfile


class MdAgent(BaseAgent):
    """
    Universal agent powered by a parsed .md profile.
    All agents (bundled and custom) use this single class.
    """

    def __init__(self, profile: AgentProfile) -> None:
        self._profile = profile

    @property
    def info(self) -> AgentInfo:
        return AgentInfo(
            name=self._profile.agent_name,
            domain=self._profile.domain,
            display_name=self._profile.display_name,
            display_name_ko=self._profile.display_name_ko,
            description=self._profile.personality,
            description_ko=self._profile.personality,
            personality=self._profile.personality,
            icon=self._profile.agent_name,
        )

    @property
    def profile(self) -> AgentProfile:
        """Access the underlying AgentProfile."""
        return self._profile

    def get_screening_prompt(self) -> str:
        return self._profile.prompts.get("screening", "")

    def get_visual_prompt(self) -> str:
        return self._profile.prompts.get("visual", "")

    def get_recipe_prompt(self) -> str:
        return self._profile.prompts.get("recipe", "")

    def get_deepdive_prompt(self) -> str:
        return self._profile.prompts.get("deepdive", "")

    def get_recipe_parameters(self) -> list[str]:
        return self._profile.recipe_parameters
