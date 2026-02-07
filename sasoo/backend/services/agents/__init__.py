from services.agents.base_agent import BaseAgent, AgentInfo
from services.agents.agent_photon import AgentPhoton
from services.agents.agent_cell import AgentCell
from services.agents.agent_neural import AgentNeural

# Agent registry: domain -> agent class
AGENT_REGISTRY: dict[str, type[BaseAgent]] = {
    "optics": AgentPhoton,
    "bio": AgentCell,
    "ai_ml": AgentNeural,
}

def get_agent_for_domain(domain: str) -> BaseAgent:
    """Get an instantiated agent for the given domain. Falls back to AgentPhoton."""
    agent_cls = AGENT_REGISTRY.get(domain, AgentPhoton)
    return agent_cls()

__all__ = [
    "BaseAgent", "AgentInfo",
    "AgentPhoton", "AgentCell", "AgentNeural",
    "AGENT_REGISTRY", "get_agent_for_domain",
]
