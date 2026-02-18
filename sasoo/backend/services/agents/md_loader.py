"""
Sasoo - Markdown Agent Loader
Parses and serializes agent definitions from .md files with YAML frontmatter.

Agent .md format (Claude Code subagent compatible):
  ---
  name: photon
  display_name: Agent Photon
  ...
  ---
  # Screening
  prompt text...
  # Visual
  prompt text...
  # Recipe
  prompt text...
  # Deep Dive
  prompt text...

Storage locations:
  - Bundled (read-only):  <backend>/agents/*.md
  - User overrides:       %APPDATA%/Sasoo/agents/*.md
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Section heading → prompt key mapping
# ---------------------------------------------------------------------------

_SECTION_KEY_MAP: dict[str, str] = {
    "screening": "screening",
    "visual": "visual",
    "recipe": "recipe",
    "deep dive": "deepdive",
    "deep_dive": "deepdive",
    "deepdive": "deepdive",
}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _is_bundled() -> bool:
    """Check if running as a PyInstaller bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def _get_bundled_agents_directory() -> Path:
    """Get bundled agents directory (read-only, shipped with app)."""
    if _is_bundled():
        return Path(sys._MEIPASS) / "agents"
    # Development fallback: <backend>/agents/
    return Path(__file__).resolve().parent.parent.parent / "agents"


def get_user_agents_directory() -> Path:
    """Get user-writable agents directory (%APPDATA%/Sasoo/agents/)."""
    from models.database import APP_DATA_ROOT
    d = APP_DATA_ROOT / "agents"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# AgentProfile
# ---------------------------------------------------------------------------

class AgentProfile:
    """
    Represents an agent loaded from a .md file with YAML frontmatter.

    Frontmatter fields map to .md `name` key (not `agent_name`):
        name, display_name, display_name_ko, domain, domain_display,
        domain_display_ko, personality, quote, color, keywords,
        weighted_keywords, recipe_parameters, model, enabled

    Body sections: # Screening, # Visual, # Recipe, # Deep Dive
    """

    def __init__(
        self,
        agent_name: str = "",
        display_name: str = "",
        display_name_ko: str = "",
        domain: str = "",
        domain_display: str = "",
        domain_display_ko: str = "",
        personality: str = "",
        quote: str = "",
        color: str = "#6b7280",
        keywords: Optional[list[str]] = None,
        weighted_keywords: Optional[list[str]] = None,
        recipe_parameters: Optional[list[str]] = None,
        model: str = "gemini-pro",
        enabled: bool = True,
        prompts: Optional[dict[str, str]] = None,
        raw_md: str = "",
        builtin: bool = False,
    ) -> None:
        self.agent_name = agent_name
        self.display_name = display_name
        self.display_name_ko = display_name_ko
        self.domain = domain
        self.domain_display = domain_display
        self.domain_display_ko = domain_display_ko
        self.personality = personality
        self.quote = quote
        self.color = color
        self.keywords: list[str] = keywords or []
        self.weighted_keywords: list[str] = weighted_keywords or []
        self.recipe_parameters: list[str] = recipe_parameters or []
        self.model = model
        self.enabled = enabled
        self.prompts: dict[str, str] = prompts or {}
        self.raw_md = raw_md
        self.builtin = builtin

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for API responses."""
        return {
            "name": self.agent_name,
            "display_name": self.display_name,
            "display_name_ko": self.display_name_ko,
            "domain": self.domain,
            "domain_display": self.domain_display,
            "domain_display_ko": self.domain_display_ko,
            "personality": self.personality,
            "quote": self.quote,
            "color": self.color,
            "keywords": self.keywords,
            "weighted_keywords": self.weighted_keywords,
            "recipe_parameters": self.recipe_parameters,
            "model": self.model,
            "enabled": self.enabled,
            "prompts": self.prompts,
            "builtin": self.builtin,
        }


# ---------------------------------------------------------------------------
# Parse / serialize
# ---------------------------------------------------------------------------

def parse_agent_md(text: str) -> AgentProfile:
    """
    Parse a .md file with YAML frontmatter into an AgentProfile.

    Expected format:
        ---
        name: photon
        domain: optics
        ...
        ---
        # Screening
        prompt text...
        # Visual
        ...
    """
    raw_md = text
    frontmatter: dict[str, Any] = {}
    body = text

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError as exc:
                logger.warning("Failed to parse frontmatter: %s", exc)
            body = parts[2].strip()

    # Parse prompt sections from body by # headings (single hash, not ##)
    prompts: dict[str, str] = {}
    current_section: Optional[str] = None
    section_lines: list[str] = []

    for line in body.splitlines():
        # Match lines like "# Screening", "# Deep Dive", etc.
        # but NOT "## Sub-heading" (double hash = content within a section)
        if line.startswith("# ") and not line.startswith("## "):
            # Save previous section
            if current_section is not None:
                prompts[current_section] = "\n".join(section_lines).strip()
            # Map heading to prompt key
            heading = line[2:].strip().lower()
            current_section = _SECTION_KEY_MAP.get(heading, heading.replace(" ", "_"))
            section_lines = []
        else:
            section_lines.append(line)

    if current_section is not None:
        prompts[current_section] = "\n".join(section_lines).strip()

    # Frontmatter uses "name" key, maps to agent_name internally
    return AgentProfile(
        agent_name=str(frontmatter.get("name", "")),
        display_name=str(frontmatter.get("display_name", "")),
        display_name_ko=str(frontmatter.get("display_name_ko", "")),
        domain=str(frontmatter.get("domain", "")),
        domain_display=str(frontmatter.get("domain_display", "")),
        domain_display_ko=str(frontmatter.get("domain_display_ko", "")),
        personality=str(frontmatter.get("personality", "")),
        quote=str(frontmatter.get("quote", "")),
        color=str(frontmatter.get("color", "#6b7280")),
        keywords=list(frontmatter.get("keywords", [])),
        weighted_keywords=list(frontmatter.get("weighted_keywords", [])),
        recipe_parameters=list(frontmatter.get("recipe_parameters", [])),
        model=str(frontmatter.get("model", "gemini-pro")),
        enabled=bool(frontmatter.get("enabled", True)),
        prompts=prompts,
        raw_md=raw_md,
    )


def serialize_agent_md(profile: AgentProfile) -> str:
    """Serialize an AgentProfile back to .md format with YAML frontmatter."""
    frontmatter_data = {
        "name": profile.agent_name,
        "display_name": profile.display_name,
        "display_name_ko": profile.display_name_ko,
        "personality": profile.personality,
        "quote": profile.quote,
        "color": profile.color,
        "domain": profile.domain,
        "domain_display": profile.domain_display,
        "domain_display_ko": profile.domain_display_ko,
        "keywords": profile.keywords,
        "weighted_keywords": profile.weighted_keywords,
        "recipe_parameters": profile.recipe_parameters,
        "model": profile.model,
        "enabled": profile.enabled,
    }

    fm_str = yaml.dump(
        frontmatter_data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )

    # Serialize prompts back to # heading sections
    _PROMPT_HEADINGS = {
        "screening": "# Screening",
        "visual": "# Visual",
        "recipe": "# Recipe",
        "deepdive": "# Deep Dive",
    }

    sections = []
    for key, heading in _PROMPT_HEADINGS.items():
        if key in profile.prompts and profile.prompts[key]:
            sections.append(f"{heading}\n\n{profile.prompts[key]}")

    body = "\n\n".join(sections)
    return f"---\n{fm_str}---\n\n{body}\n" if body else f"---\n{fm_str}---\n"


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def load_agent_file(path: Path) -> Optional[AgentProfile]:
    """Load a single .md agent file from disk."""
    try:
        text = path.read_text(encoding="utf-8")
        profile = parse_agent_md(text)
        profile.raw_md = text
        # If name was missing from frontmatter, use filename
        if not profile.agent_name:
            profile.agent_name = path.stem
        return profile
    except Exception as exc:
        logger.error("Failed to load agent file %s: %s", path, exc)
        return None


def save_agent_file(agent_name: str, profile: AgentProfile) -> None:
    """Save an agent profile to the user agents directory."""
    user_dir = get_user_agents_directory()
    path = user_dir / f"{agent_name}.md"
    md = serialize_agent_md(profile)
    path.write_text(md, encoding="utf-8")
    logger.info("Saved agent '%s' to %s", agent_name, path)


def delete_agent_file(agent_name: str) -> bool:
    """Delete a user agent file. Returns True if deleted, False if not found."""
    user_dir = get_user_agents_directory()
    path = user_dir / f"{agent_name}.md"
    if path.exists():
        path.unlink()
        logger.info("Deleted agent file: %s", path)
        return True
    return False


def is_builtin_agent(agent_name: str) -> bool:
    """Check whether an agent exists in the bundled agents directory."""
    bundled_dir = _get_bundled_agents_directory()
    return (bundled_dir / f"{agent_name}.md").exists()


# ---------------------------------------------------------------------------
# Agent listing (bundled + user, with user taking precedence)
# ---------------------------------------------------------------------------

def list_all_agents() -> list[AgentProfile]:
    """
    Return all agent profiles: bundled defaults merged with user overrides.
    User files take precedence over bundled files with the same agent_name.
    """
    profiles: dict[str, AgentProfile] = {}

    # Load bundled agents first
    bundled_dir = _get_bundled_agents_directory()
    if bundled_dir.exists():
        for md_file in sorted(bundled_dir.glob("*.md")):
            profile = load_agent_file(md_file)
            if profile and profile.agent_name:
                profile.builtin = True
                profiles[profile.agent_name] = profile

    # Load user agents (overrides bundled if same name)
    try:
        user_dir = get_user_agents_directory()
        if user_dir.exists():
            for md_file in sorted(user_dir.glob("*.md")):
                profile = load_agent_file(md_file)
                if profile and profile.agent_name:
                    profile.builtin = False
                    profiles[profile.agent_name] = profile
    except Exception as exc:
        logger.warning("Could not load user agents: %s", exc)

    return list(profiles.values())
