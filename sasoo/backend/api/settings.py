"""
Sasoo - Settings API Router
Endpoints for managing application settings and tracking API costs.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from models.database import (
    fetch_all,
    fetch_one,
    get_db,
    get_library_root,
    invalidate_library_root_cache,
    library_path_setting_key,
    usable_library_path,
)
from models.schemas import SettingsModel, SettingsUpdate
from services.crypto import decrypt_value, encrypt_value, is_encrypted, is_unreadable

router = APIRouter(prefix="/api/settings", tags=["settings"])

# ---------------------------------------------------------------------------
# Default settings
# ---------------------------------------------------------------------------

# library_path is deliberately absent: it is per-machine, so it lives under a
# platform-scoped key and is seeded by _ensure_library_path() below.
DEFAULT_SETTINGS: dict[str, str] = {
    "gemini_api_key": "",
    "openai_api_key": "",
    "image_provider": "openai",
    "image_quality": "high",
    "library_path": str(get_library_root()),
    "default_domain": "optics",
    "auto_analyze": "true",
    "language": "ko",
    "theme": "light",
    "max_concurrent_analyses": "3",
    "pdf_parser_mode": "java",
    "extraction_pipeline_version": "resolver_v1",
    "research_context": "",
    "default_explanation_level": "masters",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _ensure_library_path(db) -> None:
    """
    Give this platform its own library path, and repair an unusable one.

    get_library_root() resolves in order: this platform's key, then the legacy
    single-platform key (only if it is absolute here), then the platform
    default. So a Windows path found on a Mac -- or a stale value glued onto
    the working directory by an older build -- is replaced rather than used.
    """
    # Resolve from a fresh read: comparing against a stale cache entry would
    # "repair" a legitimate value someone just wrote to the DB out-of-band.
    invalidate_library_root_cache()
    key = library_path_setting_key()
    row = await fetch_one("SELECT value FROM settings WHERE key = ?", (key,))
    stored = str((row or {}).get("value") or "").strip()
    resolved = str(get_library_root().resolve(strict=False))

    if stored == resolved:
        return

    Path(resolved).mkdir(parents=True, exist_ok=True)
    if row is None:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)", (key, resolved)
        )
    else:
        await db.execute(
            "UPDATE settings SET value = ?, updated_at = ? WHERE key = ?",
            (resolved, datetime.utcnow().isoformat(), key),
        )


async def _ensure_defaults() -> None:
    """Insert default settings for any missing keys, and sync the library path."""
    db = await get_db()
    for key, value in DEFAULT_SETTINGS.items():
        existing = await fetch_one("SELECT key, value FROM settings WHERE key = ?", (key,))
        if existing is None:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        elif key == "extraction_pipeline_version":
            existing_value = str(existing.get("value") or "").strip().lower()
            if existing_value == "legacy":
                await db.execute(
                    "UPDATE settings SET value = ?, updated_at = ? WHERE key = ?",
                    ("resolver_v1", datetime.utcnow().isoformat(), key),
                )
    await _ensure_library_path(db)
    await db.commit()


_API_KEY_FIELDS = {"gemini_api_key", "openai_api_key"}


async def _unreadable_api_keys() -> set[str]:
    """
    API keys that are stored but cannot be decrypted.

    From the outside this looks exactly like "no key configured", which is why
    a lost encryption key used to be undiagnosable. Callers surface it so the
    user is told to re-enter the key rather than left guessing.
    """
    rows = await fetch_all("SELECT key, value FROM settings")
    return {
        row["key"]
        for row in rows
        if row["key"] in _API_KEY_FIELDS and is_unreadable(row["value"])
    }


async def _get_all_settings() -> dict[str, str]:
    """Fetch all settings as a flat dict. API keys are decrypted transparently."""
    await _ensure_defaults()
    rows = await fetch_all("SELECT key, value FROM settings")
    result = {}
    for row in rows:
        key, value = row["key"], row["value"]
        if key in _API_KEY_FIELDS and value:
            decrypted = decrypt_value(value)
            # Auto-migrate plaintext keys to encrypted
            if not is_encrypted(value) and decrypted:
                encrypted = encrypt_value(decrypted)
                await _set_setting(key, encrypted)
            result[key] = decrypted
        else:
            result[key] = value
    if result.get("pdf_parser_mode") != "java":
        await _set_setting("pdf_parser_mode", "java")
        result["pdf_parser_mode"] = "java"
    if result.get("extraction_pipeline_version") == "legacy":
        await _set_setting("extraction_pipeline_version", "resolver_v1")
        result["extraction_pipeline_version"] = "resolver_v1"
    # The API always speaks of "library_path" -- the path for THIS machine --
    # while storage keeps one per platform.
    result["library_path"] = str(get_library_root())
    return result


async def get_raw_settings() -> dict:
    """Return all settings as a flat dict without masking (internal use only, not a route).

    API keys are decrypted transparently. Callers must not expose this over the API.
    """
    return await _get_all_settings()


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
    unreadable = await _unreadable_api_keys()

    return SettingsModel(
        gemini_api_key=_mask_api_key(raw.get("gemini_api_key", "")),
        gemini_key_unreadable="gemini_api_key" in unreadable,
        openai_api_key=_mask_api_key(raw.get("openai_api_key", "")),
        openai_key_unreadable="openai_api_key" in unreadable,
        image_provider=raw.get("image_provider", "openai"),
        image_quality=raw.get("image_quality", "high"),
        library_path=raw.get("library_path", str(get_library_root())),
        default_domain=raw.get("default_domain", "optics"),
        auto_analyze=raw.get("auto_analyze", "true").lower() == "true",
        language=raw.get("language", "ko"),
        theme=raw.get("theme", "light"),
        max_concurrent_analyses=int(raw.get("max_concurrent_analyses", "3")),
        pdf_parser_mode=raw.get("pdf_parser_mode", "java"),
        extraction_pipeline_version=raw.get("extraction_pipeline_version", "resolver_v1"),
        research_context=raw.get("research_context", ""),
        default_explanation_level=raw.get("default_explanation_level", "masters"),
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

    if "library_path" in update_data and update_data["library_path"] is not None:
        candidate = usable_library_path(update_data.pop("library_path"))
        if candidate is None:
            raise HTTPException(
                status_code=400,
                detail="보관함 경로는 절대 경로여야 합니다. (예: /Users/이름/Documents/sasoo)",
            )
        new_path = candidate.resolve(strict=False)
        new_path.mkdir(parents=True, exist_ok=True)
        # Stored per platform, so a Mac and a Windows machine sharing this
        # settings database each keep their own.
        await _set_setting(library_path_setting_key(), str(new_path))
        invalidate_library_root_cache()

    for key, value in update_data.items():
        # Convert booleans and enums to string for storage
        if isinstance(value, bool):
            str_value = "true" if value else "false"
        elif hasattr(value, "value"):
            str_value = value.value
        else:
            str_value = str(value)
        # Skip empty or masked API key values (empty = no change, masked = stale)
        if key in _API_KEY_FIELDS:
            if not str_value or "..." in str_value:
                continue
            str_value = encrypt_value(str_value)
        if key == "pdf_parser_mode" and str_value != "java":
            raise HTTPException(status_code=400, detail="Slim build supports only 'java' for pdf_parser_mode.")
        if key == "extraction_pipeline_version" and str_value != "resolver_v1":
            raise HTTPException(status_code=400, detail="extraction_pipeline_version must be 'resolver_v1'.")
        await _set_setting(key, str_value)

    # If API keys changed, update environment variables for current session
    # (use original plaintext value, not encrypted)
    if "gemini_api_key" in update_data and update_data["gemini_api_key"]:
        os.environ["GEMINI_API_KEY"] = update_data["gemini_api_key"]
    if "openai_api_key" in update_data and update_data["openai_api_key"]:
        os.environ["OPENAI_API_KEY"] = update_data["openai_api_key"]

    return await get_settings()


@router.get("/cost")
async def get_cost_summary(
    month: Optional[str] = Query(None, description="Month in YYYY-MM format. Defaults to current month."),
):
    """
    Get usage & cost data including monthly trends, token usage,
    model breakdown, and per-paper costs.

    Historical usage view: these aggregates intentionally reflect cumulative
    analysis_results history rather than latest-per-phase semantics.
    """
    if month is None:
        month = datetime.utcnow().strftime("%Y-%m")

    try:
        target_date = datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM.")

    year = target_date.year
    month_num = target_date.month
    start_date = f"{year}-{month_num:02d}-01"
    end_date = f"{year + 1}-01-01" if month_num == 12 else f"{year}-{month_num + 1:02d}-01"

    # --- Monthly cost trends (last 6 months) ---
    monthly_costs = []
    for i in range(5, -1, -1):
        target = datetime.utcnow() - timedelta(days=30 * i)
        m_year, m_month = target.year, target.month
        m_start = f"{m_year}-{m_month:02d}-01"
        m_end = f"{m_year + 1}-01-01" if m_month == 12 else f"{m_year}-{m_month + 1:02d}-01"

        rows = await fetch_all(
            """SELECT model_used, cost_usd, tokens_in, tokens_out, paper_id
               FROM analysis_results
               WHERE created_at >= ? AND created_at < ? AND phase != 'error'""",
            (m_start, m_end),
        )

        total = sum(r.get("cost_usd") or 0.0 for r in rows)
        t_in = sum(r.get("tokens_in") or 0 for r in rows)
        t_out = sum(r.get("tokens_out") or 0 for r in rows)
        papers = len(set(r.get("paper_id") for r in rows if r.get("paper_id")))

        by_model: dict[str, float] = {}
        for r in rows:
            model = r.get("model_used") or "unknown"
            by_model[model] = by_model.get(model, 0.0) + (r.get("cost_usd") or 0.0)

        monthly_costs.append({
            "month": f"{m_year}-{m_month:02d}",
            "total_usd": round(total, 4),
            "papers_analyzed": papers,
            "tokens_in": t_in,
            "tokens_out": t_out,
            "by_model": {k: round(v, 4) for k, v in by_model.items()},
        })

    # --- Per-paper costs (with token data) ---
    paper_costs_rows = await fetch_all(
        """SELECT ar.paper_id, p.title, ar.phase, ar.cost_usd,
                  ar.tokens_in, ar.tokens_out
           FROM analysis_results ar
           LEFT JOIN papers p ON ar.paper_id = p.id
           WHERE ar.phase != 'error'
           ORDER BY ar.paper_id""",
    )

    paper_data: dict[int, dict] = {}
    for row in paper_costs_rows:
        pid = row.get("paper_id")
        if not pid:
            continue
        if pid not in paper_data:
            paper_data[pid] = {
                "paper_id": pid,
                "title": row.get("title") or f"Paper {pid}",
                "total_usd": 0.0,
                "tokens_in": 0,
                "tokens_out": 0,
                "phases": {},
            }
        phase = row.get("phase") or "unknown"
        cost = row.get("cost_usd") or 0.0
        paper_data[pid]["total_usd"] += cost
        paper_data[pid]["tokens_in"] += row.get("tokens_in") or 0
        paper_data[pid]["tokens_out"] += row.get("tokens_out") or 0
        paper_data[pid]["phases"][phase] = paper_data[pid]["phases"].get(phase, 0.0) + cost

    per_paper_costs = sorted(
        [
            {
                "paper_id": d["paper_id"],
                "title": d["title"],
                "total_usd": round(d["total_usd"], 4),
                "tokens_in": d["tokens_in"],
                "tokens_out": d["tokens_out"],
                "phases": {k: round(v, 4) for k, v in d["phases"].items()},
            }
            for d in paper_data.values()
        ],
        key=lambda x: x["total_usd"],
        reverse=True,
    )

    # --- Model breakdown (all-time) ---
    all_rows = await fetch_all(
        """SELECT model_used, cost_usd, tokens_in, tokens_out
           FROM analysis_results WHERE phase != 'error'"""
    )

    model_agg: dict[str, dict] = {}
    for r in all_rows:
        model = r.get("model_used") or "unknown"
        if model not in model_agg:
            model_agg[model] = {"calls": 0, "cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0}
        model_agg[model]["calls"] += 1
        model_agg[model]["cost_usd"] += r.get("cost_usd") or 0.0
        model_agg[model]["tokens_in"] += r.get("tokens_in") or 0
        model_agg[model]["tokens_out"] += r.get("tokens_out") or 0

    by_model_list = [
        {
            "model": model,
            "calls": stats["calls"],
            "cost_usd": round(stats["cost_usd"], 4),
            "tokens_in": stats["tokens_in"],
            "tokens_out": stats["tokens_out"],
        }
        for model, stats in sorted(model_agg.items(), key=lambda x: x[1]["cost_usd"], reverse=True)
    ]

    phase_call_counts: dict[str, int] = {}
    for row in await fetch_all(
        """SELECT phase, COUNT(*) as cnt
           FROM analysis_results
           WHERE phase != 'error'
           GROUP BY phase"""
    ):
        phase_call_counts[str(row.get("phase") or "unknown")] = int(row.get("cnt") or 0)

    cache_rows = await fetch_all(
        """SELECT estimated_cost_usd
           FROM analysis_cache_events"""
    )
    estimated_cached_calls_saved = len(cache_rows)
    estimated_cached_cost_usd_saved = round(
        sum(row.get("estimated_cost_usd") or 0.0 for row in cache_rows),
        4,
    )

    table_repair_row = await fetch_one(
        """SELECT
               SUM(CASE WHEN COALESCE(repair_attempted, 0) = 1 THEN 1 ELSE 0 END) AS repair_attempts,
               SUM(CASE WHEN COALESCE(review_required, 0) = 1 THEN 1 ELSE 0 END) AS review_required
           FROM tables"""
    )
    uncertain_table_repair_calls = int(table_repair_row.get("repair_attempts") or 0) if table_repair_row else 0
    review_required_tables = int(table_repair_row.get("review_required") or 0) if table_repair_row else 0

    # --- Current month stats ---
    cm_rows = await fetch_all(
        """SELECT cost_usd, tokens_in, tokens_out, paper_id
           FROM analysis_results
           WHERE created_at >= ? AND created_at < ? AND phase != 'error'""",
        (start_date, end_date),
    )
    cm_cost = sum(r.get("cost_usd") or 0.0 for r in cm_rows)
    cm_tokens_in = sum(r.get("tokens_in") or 0 for r in cm_rows)
    cm_tokens_out = sum(r.get("tokens_out") or 0 for r in cm_rows)
    cm_papers = len(set(r.get("paper_id") for r in cm_rows if r.get("paper_id")))

    # --- Totals ---
    all_papers = await fetch_all("SELECT id FROM papers")
    total_papers = len(all_papers)
    total_cost = sum(r.get("cost_usd") or 0.0 for r in all_rows)
    total_tokens_in = sum(r.get("tokens_in") or 0 for r in all_rows)
    total_tokens_out = sum(r.get("tokens_out") or 0 for r in all_rows)
    avg_cost = total_cost / total_papers if total_papers > 0 else 0.0

    return {
        "monthly_costs": monthly_costs,
        "per_paper_costs": per_paper_costs[:20],
        "by_model": by_model_list,
        "current_month": {
            "month": month,
            "cost_usd": round(cm_cost, 4),
            "tokens_in": cm_tokens_in,
            "tokens_out": cm_tokens_out,
            "papers_analyzed": cm_papers,
        },
        "totals": {
            "total_papers": total_papers,
            "total_cost_usd": round(total_cost, 4),
            "avg_cost_per_paper": round(avg_cost, 4),
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
        },
        "efficiency": {
            "phase_call_counts": phase_call_counts,
            "estimated_cached_calls_saved": estimated_cached_calls_saved,
            "estimated_cached_cost_usd_saved": estimated_cached_cost_usd_saved,
            "uncertain_table_repair_calls": uncertain_table_repair_calls,
            "review_required_tables": review_required_tables,
        },
    }
