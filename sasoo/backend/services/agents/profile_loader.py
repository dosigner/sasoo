"""
Sasoo - Agent Profile YAML Loader
Loads and saves agent profiles from YAML files.

Agent profiles allow customization of:
  - Agent metadata (display names, personality, icon)
  - Recipe parameters (domain-specific extraction fields)
  - Phase prompts (optional overrides for screening/visual/recipe/deepdive)

Profile Location: ~/sasoo-library/agent_profiles/{agent_name}_default.yaml
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def get_profiles_directory() -> Path:
    """Get the agent profiles directory path."""
    return Path.home() / "sasoo-library" / "agent_profiles"


# ---------------------------------------------------------------------------
# Profile Loader
# ---------------------------------------------------------------------------

class AgentProfile:
    """
    Represents an agent profile loaded from YAML.

    Structure:
        agent_name: str
        domain: str
        display_name: str
        display_name_ko: str
        personality: str
        icon: str
        recipe_parameters: list[str]
        prompts: dict[str, str]  # Optional phase prompt overrides
    """

    def __init__(self, data: dict[str, Any]):
        self.agent_name: str = data.get("agent_name", "")
        self.domain: str = data.get("domain", "")
        self.display_name: str = data.get("display_name", "")
        self.display_name_ko: str = data.get("display_name_ko", "")
        self.personality: str = data.get("personality", "")
        self.icon: str = data.get("icon", "")
        self.recipe_parameters: list[str] = data.get("recipe_parameters", [])
        self.prompts: dict[str, str] = data.get("prompts", {})

    def to_dict(self) -> dict[str, Any]:
        """Convert profile to dictionary."""
        return {
            "agent_name": self.agent_name,
            "domain": self.domain,
            "display_name": self.display_name,
            "display_name_ko": self.display_name_ko,
            "personality": self.personality,
            "icon": self.icon,
            "recipe_parameters": self.recipe_parameters,
            "prompts": self.prompts,
        }

    def has_prompt_override(self, phase: str) -> bool:
        """Check if this profile has a prompt override for the given phase."""
        return phase in self.prompts

    def get_prompt_override(self, phase: str) -> Optional[str]:
        """Get prompt override for the given phase, or None if not set."""
        return self.prompts.get(phase)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_profile(agent_name: str) -> Optional[AgentProfile]:
    """
    Load an agent profile from YAML file.

    Args:
        agent_name: Agent identifier (e.g., "photon", "cell", "neural")

    Returns:
        AgentProfile if file exists, None otherwise
    """
    profiles_dir = get_profiles_directory()
    yaml_path = profiles_dir / f"{agent_name}_default.yaml"

    if not yaml_path.exists():
        logger.info(f"No profile found for agent '{agent_name}' at {yaml_path}")
        return None

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            logger.warning(f"Empty YAML file for agent '{agent_name}'")
            return None

        profile = AgentProfile(data)
        logger.info(f"Loaded profile for agent '{agent_name}' from {yaml_path}")
        return profile

    except yaml.YAMLError as e:
        logger.error(f"Failed to parse YAML for agent '{agent_name}': {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to load profile for agent '{agent_name}': {e}")
        return None


def save_profile(agent_name: str, data: dict[str, Any]) -> bool:
    """
    Save an agent profile to YAML file.

    Args:
        agent_name: Agent identifier
        data: Profile data dictionary

    Returns:
        True if saved successfully, False otherwise
    """
    profiles_dir = get_profiles_directory()
    profiles_dir.mkdir(parents=True, exist_ok=True)

    yaml_path = profiles_dir / f"{agent_name}_default.yaml"

    try:
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

        logger.info(f"Saved profile for agent '{agent_name}' to {yaml_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to save profile for agent '{agent_name}': {e}")
        return False


def list_profiles() -> list[str]:
    """
    List all available agent profile names.

    Returns:
        List of agent names (without _default.yaml suffix)
    """
    profiles_dir = get_profiles_directory()

    if not profiles_dir.exists():
        return []

    profiles = []
    for yaml_file in profiles_dir.glob("*_default.yaml"):
        agent_name = yaml_file.stem.replace("_default", "")
        profiles.append(agent_name)

    return sorted(profiles)


def profile_exists(agent_name: str) -> bool:
    """Check if a profile exists for the given agent."""
    profiles_dir = get_profiles_directory()
    yaml_path = profiles_dir / f"{agent_name}_default.yaml"
    return yaml_path.exists()


# ---------------------------------------------------------------------------
# Integration with BaseAgent
# ---------------------------------------------------------------------------

def apply_profile_to_agent(agent: Any, profile: AgentProfile) -> None:
    """
    Apply profile overrides to an agent instance.

    This modifies the agent's methods to return profile values when available.
    Note: This is a runtime monkey-patch approach. Use with caution.

    Args:
        agent: BaseAgent instance
        profile: AgentProfile to apply
    """
    # Store original methods
    original_screening = agent.get_screening_prompt
    original_visual = agent.get_visual_prompt
    original_recipe = agent.get_recipe_prompt
    original_deepdive = agent.get_deepdive_prompt
    original_params = agent.get_recipe_parameters

    # Create wrapper functions that use profile overrides
    def get_screening_prompt():
        override = profile.get_prompt_override("screening")
        return override if override else original_screening()

    def get_visual_prompt():
        override = profile.get_prompt_override("visual")
        return override if override else original_visual()

    def get_recipe_prompt():
        override = profile.get_prompt_override("recipe")
        return override if override else original_recipe()

    def get_deepdive_prompt():
        override = profile.get_prompt_override("deepdive")
        return override if override else original_deepdive()

    def get_recipe_parameters():
        # Use profile parameters if available, otherwise original
        return profile.recipe_parameters if profile.recipe_parameters else original_params()

    # Monkey-patch the methods
    agent.get_screening_prompt = get_screening_prompt
    agent.get_visual_prompt = get_visual_prompt
    agent.get_recipe_prompt = get_recipe_prompt
    agent.get_deepdive_prompt = get_deepdive_prompt
    agent.get_recipe_parameters = get_recipe_parameters

    logger.info(f"Applied profile overrides to agent '{agent.name}'")
