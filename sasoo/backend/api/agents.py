"""
Sasoo - Agent Read API
Read-only access to agent .md profiles (bundled + user overrides).

Agent CRUD (create/update/delete/duplicate/toggle/export/import) and
LLM-based agent generation have been removed. Agents are now managed by
editing .md files directly (bundled: <backend>/agents/*.md, user overrides:
%APPDATA%/Sasoo/agents/*.md). The loader (services.agents.md_loader) still
supports writing/deleting files for that manual workflow, but no HTTP
surface exposes it.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from services.agents.md_loader import list_all_agents

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_agents():
    """List all agents (bundled + custom)."""
    agents = list_all_agents()
    return [p.to_dict() for p in agents]


@router.get("/{name}")
async def get_agent(name: str):
    """Get agent detail including raw .md content."""
    agents = list_all_agents()
    for p in agents:
        if p.agent_name == name:
            data = p.to_dict()
            data["raw_md"] = p.raw_md
            return data
    raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
