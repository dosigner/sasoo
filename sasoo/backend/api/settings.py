"""
Sasoo - Settings API Router
Endpoints for managing application settings and tracking API costs.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from models.database import LIBRARY_ROOT, fetch_all, fetch_one, get_db
from models.schemas import SettingsModel, SettingsUpdate
from services.agents.profile_loader import (
    list_profiles,
    load_profile,
    profile_exists,
    save_profile,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# ---------------------------------------------------------------------------
# Default settings
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, str] = {
    "gemini_api_key": "",
    "anthropic_api_key": "",
    "library_path": str(LIBRARY_ROOT),
    "default_domain": "optics",
    "auto_analyze": "true",
    "language": "ko",
    "theme": "light",
    "max_concurrent_analyses": "3",
    "gemini_model": "gemini-3-flash-preview",
    "anthropic_model": "claude-sonnet-4-20250514",
    "monthly_budget_limit": "50.0",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _ensure_defaults() -> None:
    """Insert default settings for any missing keys, and sync library_path."""
    db = await get_db()
    for key, value in DEFAULT_SETTINGS.items():
        existing = await fetch_one("SELECT key FROM settings WHERE key = ?", (key,))
        if existing is None:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
    await db.commit()


async def _get_all_settings() -> dict[str, str]:
    """Fetch all settings as a flat dict."""
    await _ensure_defaults()
    rows = await fetch_all("SELECT key, value FROM settings")
    return {row["key"]: row["value"] for row in rows}


async def _set_setting(key: str, value: str) -> None:
    """Upsert a single setting."""
    db = await get_db()
    existing = await fetch_one("SELECT key FROM settings WHERE key = ?", (key,))
    if existing:
        await db.execute(
            "UPDATE settings SET value = ?, updated_at = ? WHERE key = ?",
            (value, datetime.utcnow().isoformat(), key),
        )
    else:
        await db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, datetime.utcnow().isoformat()),
        )
    await db.commit()


def _mask_api_key(key: str) -> str:
    """Mask an API key for safe display: show first 8 and last 4 chars."""
    if not key or len(key) < 16:
        return "***" if key else ""
    return f"{key[:8]}...{key[-4:]}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=SettingsModel)
async def get_settings():
    """
    Get current application settings.
    API keys are masked for security.
    """
    raw = await _get_all_settings()

    return SettingsModel(
        gemini_api_key=_mask_api_key(raw.get("gemini_api_key", "")),
        anthropic_api_key=_mask_api_key(raw.get("anthropic_api_key", "")),
        library_path=raw.get("library_path", str(LIBRARY_ROOT)),
        default_domain=raw.get("default_domain", "optics"),
        auto_analyze=raw.get("auto_analyze", "true").lower() == "true",
        language=raw.get("language", "ko"),
        theme=raw.get("theme", "light"),
        max_concurrent_analyses=int(raw.get("max_concurrent_analyses", "3")),
        gemini_model=raw.get("gemini_model", "gemini-3-flash-preview"),
        anthropic_model=raw.get("anthropic_model", "claude-sonnet-4-20250514"),
    )


@router.put("", response_model=SettingsModel)
async def update_settings(update: SettingsUpdate):
    """
    Update application settings.
    Only non-None fields in the request body are updated.
    API keys are stored as-is but returned masked.
    """
    update_data = update.model_dump(exclude_none=True)

    if not update_data:
        raise HTTPException(status_code=400, detail="No settings to update.")

    for key, value in update_data.items():
        # Convert booleans and enums to string for storage
        if isinstance(value, bool):
            str_value = "true" if value else "false"
        elif hasattr(value, "value"):
            str_value = value.value
        else:
            str_value = str(value)
        await _set_setting(key, str_value)

    # If library_path changed, ensure the directory exists
    if "library_path" in update_data:
        new_path = Path(update_data["library_path"]).expanduser()
        new_path.mkdir(parents=True, exist_ok=True)

    # If API keys changed, update environment variables for current session
    if "gemini_api_key" in update_data and update_data["gemini_api_key"]:
        import os
        os.environ["GEMINI_API_KEY"] = update_data["gemini_api_key"]
        os.environ["GOOGLE_API_KEY"] = update_data["gemini_api_key"]  # PaperBanana uses this

    if "anthropic_api_key" in update_data and update_data["anthropic_api_key"]:
        import os
        os.environ["ANTHROPIC_API_KEY"] = update_data["anthropic_api_key"]

    return await get_settings()


@router.get("/cost")
async def get_cost_summary(
    month: Optional[str] = Query(None, description="Month in YYYY-MM format. Defaults to current month."),
):
    """
    Get enhanced cost data including monthly trends, per-paper breakdown, and budget status.
    """
    if month is None:
        month = datetime.utcnow().strftime("%Y-%m")

    # Validate month format
    try:
        target_date = datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM.")

    # Get budget setting
    raw_settings = await _get_all_settings()
    monthly_limit_usd = float(raw_settings.get("monthly_budget_limit", "50.0"))

    # Calculate date range for current month
    current_month = datetime.utcnow().strftime("%Y-%m")
    year = target_date.year
    month_num = target_date.month
    start_date = f"{year}-{month_num:02d}-01"
    if month_num == 12:
        end_date = f"{year + 1}-01-01"
    else:
        end_date = f"{year}-{month_num + 1:02d}-01"

    # Get monthly cost trends (last 6 months)
    monthly_costs = []
    for i in range(5, -1, -1):
        target = datetime.utcnow() - timedelta(days=30 * i)
        m_year = target.year
        m_month = target.month
        m_start = f"{m_year}-{m_month:02d}-01"
        if m_month == 12:
            m_end = f"{m_year + 1}-01-01"
        else:
            m_end = f"{m_year}-{m_month + 1:02d}-01"

        rows = await fetch_all(
            """SELECT phase, model_used, cost_usd, paper_id
               FROM analysis_results
               WHERE created_at >= ? AND created_at < ? AND phase != 'error'""",
            (m_start, m_end),
        )

        total = sum(r.get("cost_usd") or 0.0 for r in rows)
        papers = len(set(r.get("paper_id") for r in rows if r.get("paper_id")))

        by_model: dict[str, float] = {}
        for r in rows:
            model = r.get("model_used") or "unknown"
            by_model[model] = by_model.get(model, 0.0) + (r.get("cost_usd") or 0.0)

        monthly_costs.append({
            "month": f"{m_year}-{m_month:02d}",
            "total_usd": round(total, 4),
            "papers_analyzed": papers,
            "by_model": {k: round(v, 4) for k, v in by_model.items()},
        })

    # Get per-paper costs
    per_paper_costs = []
    paper_costs_query = await fetch_all(
        """SELECT ar.paper_id, p.title, ar.phase, ar.cost_usd
           FROM analysis_results ar
           LEFT JOIN papers p ON ar.paper_id = p.id
           WHERE ar.phase != 'error'
           ORDER BY ar.paper_id""",
    )

    paper_data: dict[int, dict] = {}
    for row in paper_costs_query:
        pid = row.get("paper_id")
        if not pid:
            continue
        if pid not in paper_data:
            paper_data[pid] = {
                "paper_id": pid,
                "title": row.get("title") or f"Paper {pid}",
                "total_usd": 0.0,
                "phases": {},
            }
        phase = row.get("phase") or "unknown"
        cost = row.get("cost_usd") or 0.0
        paper_data[pid]["total_usd"] += cost
        paper_data[pid]["phases"][phase] = paper_data[pid]["phases"].get(phase, 0.0) + cost

    for pid, data in paper_data.items():
        per_paper_costs.append({
            "paper_id": pid,
            "title": data["title"],
            "total_usd": round(data["total_usd"], 4),
            "phases": {k: round(v, 4) for k, v in data["phases"].items()},
        })

    # Sort by cost descending
    per_paper_costs.sort(key=lambda x: x["total_usd"], reverse=True)

    # Get current month spending
    current_month_rows = await fetch_all(
        """SELECT cost_usd FROM analysis_results
           WHERE created_at >= ? AND created_at < ? AND phase != 'error'""",
        (start_date, end_date),
    )
    current_month_usd = sum(r.get("cost_usd") or 0.0 for r in current_month_rows)
    remaining_usd = monthly_limit_usd - current_month_usd

    # Calculate totals
    all_papers = await fetch_all("SELECT id FROM papers")
    total_papers = len(all_papers)

    all_costs = await fetch_all(
        "SELECT cost_usd FROM analysis_results WHERE phase != 'error'"
    )
    total_cost = sum(r.get("cost_usd") or 0.0 for r in all_costs)
    avg_cost = total_cost / total_papers if total_papers > 0 else 0.0

    return {
        "monthly_costs": monthly_costs,
        "per_paper_costs": per_paper_costs[:20],  # Top 20
        "budget": {
            "monthly_limit_usd": monthly_limit_usd,
            "current_month_usd": round(current_month_usd, 4),
            "remaining_usd": round(remaining_usd, 4),
            "warning_threshold": 0.8,
        },
        "totals": {
            "total_papers": total_papers,
            "total_cost_usd": round(total_cost, 4),
            "avg_cost_per_paper": round(avg_cost, 4),
        },
    }


@router.put("/budget")
async def update_budget(monthly_limit_usd: float = Query(..., ge=0.0, description="Monthly budget limit in USD")):
    """
    Update the monthly budget limit.
    """
    await _set_setting("monthly_budget_limit", str(monthly_limit_usd))
    return {"monthly_limit_usd": monthly_limit_usd, "status": "updated"}


@router.get("/debug/paperbanana")
async def debug_paperbanana():
    """
    Diagnostic endpoint: check PaperBanana availability and configuration.
    Visit http://localhost:8000/api/settings/debug/paperbanana in browser.
    """
    import os
    import sys

    from services.viz.paperbanana_bridge import (
        _IS_FROZEN,
        _IMPORT_ERROR_DETAIL,
        _MEIPASS,
        _PAPERBANANA_AVAILABLE,
        PaperBananaBridge,
    )

    bridge = PaperBananaBridge()
    pipeline_ok = bridge.is_available

    result = {
        "frozen": _IS_FROZEN,
        "meipass": str(_MEIPASS) if _MEIPASS else None,
        "import_ok": _PAPERBANANA_AVAILABLE,
        "import_error": _IMPORT_ERROR_DETAIL[:500] if _IMPORT_ERROR_DETAIL else None,
        "pipeline_ok": pipeline_ok,
        "pipeline_error": bridge.last_error or None,
        "env": {
            "GEMINI_API_KEY": bool(os.environ.get("GEMINI_API_KEY")),
            "GOOGLE_API_KEY": bool(os.environ.get("GOOGLE_API_KEY")),
        },
    }

    # Check data file paths if frozen
    if _IS_FROZEN and _MEIPASS:
        from pathlib import Path
        meipass = Path(str(_MEIPASS))
        result["data_files"] = {
            "prompts_dir": str(meipass / "prompts"),
            "prompts_exists": (meipass / "prompts").exists(),
            "data_dir": str(meipass / "data"),
            "data_exists": (meipass / "data").exists(),
            "configs_dir": str(meipass / "configs"),
            "configs_exists": (meipass / "configs").exists(),
        }

    return result


@router.get("/keys/status")
async def check_api_keys():
    """
    Check which API keys are configured (without revealing them).
    Useful for the frontend to show setup status.
    """
    raw = await _get_all_settings()

    gemini_key = raw.get("gemini_api_key", "")
    anthropic_key = raw.get("anthropic_api_key", "")

    return {
        "gemini": {
            "configured": bool(gemini_key),
            "masked": _mask_api_key(gemini_key),
        },
        "anthropic": {
            "configured": bool(anthropic_key),
            "masked": _mask_api_key(anthropic_key),
        },
    }


# ---------------------------------------------------------------------------
# Agent Profile Endpoints
# ---------------------------------------------------------------------------

@router.get("/agents")
async def list_agent_profiles():
    """
    List all available agent profiles.
    Returns a list of agent names that have YAML profile files.
    """
    profiles = list_profiles()
    return {
        "agents": profiles,
        "count": len(profiles),
    }


@router.get("/agents/{agent_name}")
async def get_agent_profile(agent_name: str):
    """
    Get a specific agent profile by name.
    Returns the full YAML profile data.
    """
    if not profile_exists(agent_name):
        raise HTTPException(
            status_code=404,
            detail=f"Agent profile '{agent_name}' not found"
        )

    profile = load_profile(agent_name)
    if profile is None:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load agent profile '{agent_name}'"
        )

    return profile.to_dict()


@router.put("/agents/{agent_name}")
async def update_agent_profile(agent_name: str, profile_data: dict[str, Any]):
    """
    Update or create an agent profile.
    Accepts a full profile dictionary and saves it to YAML.
    """
    # Validate required fields
    required_fields = ["agent_name", "domain", "display_name", "display_name_ko"]
    for field in required_fields:
        if field not in profile_data:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required field: {field}"
            )

    # Ensure agent_name matches path parameter
    if profile_data.get("agent_name") != agent_name:
        raise HTTPException(
            status_code=400,
            detail="Agent name in URL must match agent_name in profile data"
        )

    # Save profile
    success = save_profile(agent_name, profile_data)
    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save agent profile '{agent_name}'"
        )

    return {
        "status": "saved",
        "agent_name": agent_name,
        "profile": profile_data,
    }
