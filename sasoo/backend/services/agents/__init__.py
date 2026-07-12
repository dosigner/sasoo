"""
Sasoo - Agent Registry
Dynamic agent loading from .md files. No hardcoded agent classes.
"""

from services.agents.base_agent import BaseAgent, AgentInfo
from services.agents.md_agent import MdAgent
from services.agents.md_loader import (
    AgentProfile,
    list_all_agents,
    load_agent_file,
    is_builtin_agent,
    parse_agent_md,
    get_user_agents_directory,
)

# ---------------------------------------------------------------------------
# Agent cache (loaded at startup, refreshed on CRUD)
# ---------------------------------------------------------------------------

_AGENT_CACHE: dict[str, MdAgent] = {}


def load_all_agents() -> None:
    """Load all .md agents from bundled + user directories into cache."""
    _AGENT_CACHE.clear()
    for profile in list_all_agents():
        if profile.enabled:
            _AGENT_CACHE[profile.domain] = MdAgent(profile)
            # Also index by agent name for direct lookup
            _AGENT_CACHE[profile.agent_name] = MdAgent(profile)


def get_agent_for_domain(domain: str) -> BaseAgent:
    """Get an agent for the given domain key. Falls back to first available."""
    if not _AGENT_CACHE:
        load_all_agents()
    if domain in _AGENT_CACHE:
        return _AGENT_CACHE[domain]
    # Fallback to first agent
    if _AGENT_CACHE:
        return next(iter(_AGENT_CACHE.values()))
    # Emergency fallback: create a minimal agent
    from services.agents.md_loader import AgentProfile as _AP
    return MdAgent(_AP(agent_name="unknown", domain="unknown",
                       display_name="Unknown", display_name_ko="알 수 없음"))


def get_all_cached_agents() -> list[MdAgent]:
    """Return all cached agents (unique by agent_name)."""
    if not _AGENT_CACHE:
        load_all_agents()
    seen = set()
    result = []
    for agent in _AGENT_CACHE.values():
        if agent.name not in seen:
            seen.add(agent.name)
            result.append(agent)
    return result


def reload_agents() -> None:
    """Reload all agents from disk (call after CRUD operations)."""
    load_all_agents()


__all__ = [
    "BaseAgent",
    "AgentInfo",
    "MdAgent",
    "AgentProfile",
    "load_all_agents",
    "get_agent_for_domain",
    "get_all_cached_agents",
    "reload_agents",
    "list_all_agents",
    "load_agent_file",
    "is_builtin_agent",
    "parse_agent_md",
    "get_user_agents_directory",
]
