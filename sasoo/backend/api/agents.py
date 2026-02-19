"""
Sasoo - Agent CRUD API
Manages agent .md profiles (create, read, update, delete, import, export).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from services.agents import (
    get_all_cached_agents,
    reload_agents,
    parse_agent_md,
    serialize_agent_md,
    save_agent_file,
    delete_agent_file,
    is_builtin_agent,
    get_user_agents_directory,
    AgentProfile,
)
from services.agents.md_loader import load_agent_file as _load_agent_file, list_all_agents

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AgentCreateRequest(BaseModel):
    name: str
    display_name: str = ""
    display_name_ko: str = ""
    personality: str = ""
    quote: str = ""
    color: str = "#6b7280"
    domain: str = ""
    domain_display: str = ""
    domain_display_ko: str = ""
    keywords: list[str] = []
    weighted_keywords: list[str] = []
    recipe_parameters: list[str] = []
    model: str = "gemini-pro"
    enabled: bool = True
    prompts: dict[str, str] = {}
    raw_md: Optional[str] = None


class AgentToggleRequest(BaseModel):
    enabled: bool


class AgentGenerateRequest(BaseModel):
    domain_description: str
    personality_hint: Optional[str] = None
    color: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/generate")
async def generate_agent(req: AgentGenerateRequest):
    """
    Generate an agent profile using LLM (does NOT save).
    Frontend reviews the result, then saves via POST /api/agents.
    """
    if not req.domain_description.strip():
        raise HTTPException(status_code=400, detail="domain_description is required")

    from services.llm.gemini_client import GeminiClient
    from services.agents.generator import AgentGenerator

    try:
        client = GeminiClient()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        generator = AgentGenerator(client)
        profile = await generator.generate(
            domain_description=req.domain_description,
            personality_hint=req.personality_hint,
            color=req.color,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"Agent generation failed: {exc}")

    result = profile.to_dict()
    result["_generation_usage"] = client.get_usage_summary()
    return result


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


@router.post("")
async def create_agent(req: AgentCreateRequest):
    """Create a new custom agent."""
    # Check name collision with builtin
    if is_builtin_agent(req.name):
        # Allow override (saves to user dir)
        pass

    # Check name collision with existing user agents
    user_dir = get_user_agents_directory()
    if (user_dir / f"{req.name}.md").exists():
        raise HTTPException(status_code=409, detail=f"Agent '{req.name}' already exists")

    if req.raw_md:
        # Parse from raw markdown
        profile = parse_agent_md(req.raw_md)
        if not profile.agent_name:
            profile.agent_name = req.name
    else:
        profile = AgentProfile(
            agent_name=req.name,
            display_name=req.display_name or req.name.title(),
            display_name_ko=req.display_name_ko,
            personality=req.personality,
            quote=req.quote,
            color=req.color,
            domain=req.domain,
            domain_display=req.domain_display,
            domain_display_ko=req.domain_display_ko,
            keywords=req.keywords,
            weighted_keywords=req.weighted_keywords,
            recipe_parameters=req.recipe_parameters,
            model=req.model,
            enabled=req.enabled,
            prompts=req.prompts,
        )

    save_agent_file(req.name, profile)
    reload_agents()
    return profile.to_dict()


@router.put("/{name}")
async def update_agent(name: str, req: AgentCreateRequest):
    """Update an existing agent (creates override for builtin)."""
    if req.raw_md:
        profile = parse_agent_md(req.raw_md)
        if not profile.agent_name:
            profile.agent_name = name
    else:
        profile = AgentProfile(
            agent_name=name,
            display_name=req.display_name,
            display_name_ko=req.display_name_ko,
            personality=req.personality,
            quote=req.quote,
            color=req.color,
            domain=req.domain,
            domain_display=req.domain_display,
            domain_display_ko=req.domain_display_ko,
            keywords=req.keywords,
            weighted_keywords=req.weighted_keywords,
            recipe_parameters=req.recipe_parameters,
            model=req.model,
            enabled=req.enabled,
            prompts=req.prompts,
        )

    save_agent_file(name, profile)
    reload_agents()
    return profile.to_dict()


@router.delete("/{name}")
async def delete_agent(name: str):
    """Delete a custom agent. Cannot delete bundled agents."""
    if is_builtin_agent(name):
        # Check if there's a user override
        user_dir = get_user_agents_directory()
        if (user_dir / f"{name}.md").exists():
            delete_agent_file(name)
            reload_agents()
            return {"detail": f"User override for '{name}' removed. Bundled version restored."}
        raise HTTPException(
            status_code=403,
            detail=f"Cannot delete bundled agent '{name}'. You can disable it instead."
        )

    if not delete_agent_file(name):
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    reload_agents()
    return {"detail": f"Agent '{name}' deleted"}


@router.post("/{name}/duplicate")
async def duplicate_agent(name: str):
    """Duplicate an agent with a new name."""
    agents = list_all_agents()
    source = None
    for p in agents:
        if p.agent_name == name:
            source = p
            break
    if not source:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # Generate new name
    new_name = f"{name}_copy"
    counter = 1
    user_dir = get_user_agents_directory()
    while (user_dir / f"{new_name}.md").exists():
        counter += 1
        new_name = f"{name}_copy{counter}"

    new_profile = AgentProfile(
        agent_name=new_name,
        display_name=f"{source.display_name} (Copy)",
        display_name_ko=f"{source.display_name_ko} (복사)" if source.display_name_ko else "",
        personality=source.personality,
        quote=source.quote,
        color=source.color,
        domain=f"{source.domain}_custom",
        domain_display=source.domain_display,
        domain_display_ko=source.domain_display_ko,
        keywords=list(source.keywords),
        weighted_keywords=list(source.weighted_keywords),
        recipe_parameters=list(source.recipe_parameters),
        model=source.model,
        enabled=True,
        prompts=dict(source.prompts),
    )

    save_agent_file(new_name, new_profile)
    reload_agents()
    return new_profile.to_dict()


@router.patch("/{name}/toggle")
async def toggle_agent(name: str, req: AgentToggleRequest):
    """Toggle agent enabled/disabled."""
    agents = list_all_agents()
    source = None
    for p in agents:
        if p.agent_name == name:
            source = p
            break
    if not source:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    source.enabled = req.enabled
    save_agent_file(name, source)
    reload_agents()
    return source.to_dict()


@router.get("/{name}/export")
async def export_agent(name: str):
    """Export agent as .md file content."""
    agents = list_all_agents()
    for p in agents:
        if p.agent_name == name:
            md_content = serialize_agent_md(p)
            return PlainTextResponse(
                content=md_content,
                media_type="text/markdown",
                headers={
                    "Content-Disposition": f'attachment; filename="{name}.md"'
                },
            )
    raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")


@router.post("/import")
async def import_agent(file: UploadFile = File(...)):
    """Import agent from .md file upload."""
    if not file.filename or not file.filename.endswith(".md"):
        raise HTTPException(status_code=400, detail="Only .md files are accepted")

    content = await file.read()
    text = content.decode("utf-8")

    profile = parse_agent_md(text)
    if not profile.agent_name:
        # Use filename as agent name
        profile.agent_name = file.filename.replace(".md", "")

    if not profile.domain:
        raise HTTPException(
            status_code=400,
            detail="Invalid agent file: missing 'domain' in frontmatter"
        )

    # Check collision
    user_dir = get_user_agents_directory()
    if (user_dir / f"{profile.agent_name}.md").exists():
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{profile.agent_name}' already exists. Delete it first or rename."
        )

    save_agent_file(profile.agent_name, profile)
    reload_agents()
    return profile.to_dict()
