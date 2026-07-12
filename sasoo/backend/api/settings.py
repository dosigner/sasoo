"""
Sasoo - Settings API Router
Endpoints for managing application settings and tracking API costs.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from models.database import fetch_all, fetch_one, get_db, get_library_root
from models.schemas import SettingsModel, SettingsUpdate
from services.crypto import decrypt_value, encrypt_value, is_encrypted

router = APIRouter(prefix="/api/settings", tags=["settings"])

# ---------------------------------------------------------------------------
# Default settings
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, str] = {
    "gemini_api_key": "",
    "library_path": str(get_library_root()),
    "default_domain": "optics",
    "auto_analyze": "true",
    "language": "ko",
    "theme": "light",
    "max_concurrent_analyses": "3",
    "pdf_parser_mode": "java",
    "extraction_pipeline_version": "resolver_v1",
    "extraction_pipeline_force_fallback": "false",
    "research_context": "",
    "default_explanation_level": "masters",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_library_path_value(value: Any) -> str:
    """Normalize configured library paths and recover from empty values."""
    text = str(value or "").strip()
    if not text:
        return str(get_library_root())
    return str(Path(text).expanduser().resolve(strict=False))

async def _ensure_defaults() -> None:
    """Insert default settings for any missing keys, and sync library_path."""
    db = await get_db()
    for key, value in DEFAULT_SETTINGS.items():
        existing = await fetch_one("SELECT key, value FROM settings WHERE key = ?", (key,))
        if existing is None:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        elif key == "library_path":
            normalized_path = _normalize_library_path_value(existing.get("value"))
            if str(existing.get("value") or "").strip() != normalized_path:
                Path(normalized_path).mkdir(parents=True, exist_ok=True)
                await db.execute(
                    "UPDATE settings SET value = ?, updated_at = ? WHERE key = ?",
                    (normalized_path, datetime.utcnow().isoformat(), key),
                )
        elif key == "extraction_pipeline_version":
            fallback_row = await fetch_one(
                "SELECT value FROM settings WHERE key = 'extraction_pipeline_force_fallback' LIMIT 1"
            )
            existing_value = str(existing.get("value") or "").strip().lower()
            fallback_forced = str((fallback_row or {}).get("value") or "false").strip().lower() == "true"
            if existing_value == "legacy" and not fallback_forced:
                await db.execute(
                    "UPDATE settings SET value = ?, updated_at = ? WHERE key = ?",
                    ("resolver_v1", datetime.utcnow().isoformat(), key),
                )
    await db.commit()


_API_KEY_FIELDS = {"gemini_api_key"}


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
    if result.get("extraction_pipeline_version") == "legacy" and result.get("extraction_pipeline_force_fallback", "false").lower() != "true":
        await _set_setting("extraction_pipeline_version", "resolver_v1")
        result["extraction_pipeline_version"] = "resolver_v1"
    normalized_library_path = _normalize_library_path_value(result.get("library_path"))
    if result.get("library_path") != normalized_library_path:
        Path(normalized_library_path).mkdir(parents=True, exist_ok=True)
        await _set_setting("library_path", normalized_library_path)
        result["library_path"] = normalized_library_path
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

    return SettingsModel(
        gemini_api_key=_mask_api_key(raw.get("gemini_api_key", "")),
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
        new_path = Path(_normalize_library_path_value(update_data["library_path"]))
        new_path.mkdir(parents=True, exist_ok=True)
        update_data["library_path"] = str(new_path)

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
        if key == "extraction_pipeline_version" and str_value not in {"legacy", "resolver_v1"}:
            raise HTTPException(status_code=400, detail="extraction_pipeline_version must be 'legacy' or 'resolver_v1'.")
        await _set_setting(key, str_value)
        if key == "extraction_pipeline_version":
            await _set_setting(
                "extraction_pipeline_force_fallback",
                "true" if str_value == "legacy" else "false",
            )

    # If API keys changed, update environment variables for current session
    # (use original plaintext value, not encrypted)
    if "gemini_api_key" in update_data and update_data["gemini_api_key"]:
        os.environ["GEMINI_API_KEY"] = update_data["gemini_api_key"]
        os.environ["GOOGLE_API_KEY"] = update_data["gemini_api_key"]  # PaperBanana uses this

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


# ---------------------------------------------------------------------------
# Debug endpoints (only available in development or when SASOO_DEBUG=1)
# ---------------------------------------------------------------------------

def _is_debug_enabled() -> bool:
    """Check if debug endpoints should be available."""
    return os.environ.get("SASOO_ENV") != "production" or os.environ.get("SASOO_DEBUG") == "1"


if _is_debug_enabled():

    @router.get("/debug/paperbanana")
    async def debug_paperbanana():
        """
        Diagnostic endpoint: check PaperBanana availability and configuration.
        Visit http://localhost:8000/api/settings/debug/paperbanana in browser.
        """
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


    @router.get("/debug/paperbanana/test")
    async def test_paperbanana_generation():
        """
        Actually test PaperBanana generation step-by-step.
        Visit http://localhost:8000/api/settings/debug/paperbanana/test
        """
        import traceback

        from services.viz.paperbanana_bridge import (
            _IS_FROZEN,
            _MEIPASS,
            _PAPERBANANA_AVAILABLE,
            PaperBananaBridge,
        )

        steps: dict[str, Any] = {}

        # Step 1: Bridge availability
        try:
            bridge = PaperBananaBridge()
            available = bridge.is_available
            steps["1_bridge_available"] = available
            if not available:
                steps["1_error"] = bridge.last_error
                return {"steps": steps, "conclusion": "Bridge not available"}
        except Exception as exc:
            steps["1_error"] = f"{exc.__class__.__name__}: {exc}"
            return {"steps": steps, "conclusion": "Bridge init failed"}

        # Step 2: Check prompt loading
        try:
            pipeline = bridge._pipeline
            agent = pipeline.retriever
            prompt_dir = agent.prompt_dir
            steps["2_prompt_dir"] = str(prompt_dir)
            steps["2_prompt_dir_exists"] = prompt_dir.exists() if hasattr(prompt_dir, 'exists') else "N/A"

            # Try loading a prompt
            prompt_text = agent.load_prompt("diagram")
            steps["2_prompt_loaded"] = True
            steps["2_prompt_length"] = len(prompt_text)
        except Exception as exc:
            steps["2_prompt_loaded"] = False
            steps["2_error"] = f"{exc.__class__.__name__}: {exc}"
            return {"steps": steps, "conclusion": f"Prompt loading failed: {exc}"}

        # Step 3: Check VLM provider
        try:
            vlm = pipeline._vlm
            steps["3_vlm_type"] = type(vlm).__name__
            steps["3_vlm_model"] = getattr(vlm, '_model', 'unknown')
            steps["3_vlm_has_key"] = bool(getattr(vlm, '_api_key', None))

            # Try a minimal VLM call
            vlm_result = await vlm.generate("Reply with just the word 'OK'.")
            steps["3_vlm_test"] = True
            steps["3_vlm_response"] = vlm_result[:100]
        except Exception as exc:
            steps["3_vlm_test"] = False
            steps["3_error"] = f"{exc.__class__.__name__}: {exc}"
            steps["3_traceback"] = traceback.format_exc()[-500:]
            return {"steps": steps, "conclusion": f"VLM call failed: {exc}"}

        # Step 4: Check image gen provider
        try:
            image_gen = pipeline._image_gen
            steps["4_image_gen_type"] = type(image_gen).__name__
            steps["4_image_gen_model"] = getattr(image_gen, '_model', 'unknown')
            steps["4_image_gen_has_key"] = bool(getattr(image_gen, '_api_key', None))
            steps["4_image_gen_available"] = image_gen.is_available()
        except Exception as exc:
            steps["4_error"] = f"{exc.__class__.__name__}: {exc}"

        # Step 5: Check settings paths
        try:
            settings = pipeline.settings
            steps["5_reference_set_path"] = settings.reference_set_path
            steps["5_guidelines_path"] = settings.guidelines_path
            steps["5_output_dir"] = settings.output_dir
            steps["5_ref_exists"] = Path(settings.reference_set_path).exists()
            steps["5_guide_exists"] = Path(settings.guidelines_path).exists()
            steps["5_api_key_in_settings"] = bool(settings.google_api_key)
        except Exception as exc:
            steps["5_error"] = f"{exc.__class__.__name__}: {exc}"

        # Step 6: Check reference store
        try:
            refs = pipeline.reference_store.get_all()
            steps["6_reference_count"] = len(refs)
        except Exception as exc:
            steps["6_error"] = f"{exc.__class__.__name__}: {exc}"
            steps["6_traceback"] = traceback.format_exc()[-500:]

        return {"steps": steps, "conclusion": "All checks passed (VLM working)"}


@router.get("/keys/status")
async def check_api_keys():
    """
    Check which API keys are configured (without revealing them).
    Useful for the frontend to show setup status.
    """
    raw = await _get_all_settings()

    gemini_key = raw.get("gemini_api_key", "")

    return {
        "gemini": {
            "configured": bool(gemini_key),
            "masked": _mask_api_key(gemini_key),
        },
    }
