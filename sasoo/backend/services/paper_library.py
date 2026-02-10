"""
Sasoo - Paper Library Management

Provides CRUD operations, search (SQLite FTS5), tag management, notes,
cost tracking per paper and monthly aggregate, and library statistics.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from models.database import (
    execute_insert,
    execute_update,
    fetch_all,
    fetch_one,
    get_db,
    get_paper_dir,
)

logger = logging.getLogger(__name__)


class PaperLibrary:
    """
    Manages the paper library including CRUD, full-text search, tags,
    notes, cost tracking, and statistics.
    """

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    async def ensure_fts_table(self) -> None:
        """
        Create the FTS5 virtual table for full-text search if it does not
        already exist. Should be called once at startup after init_db().
        """
        db = await get_db()
        try:
            await db.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
                    title, authors, journal, tags, notes,
                    content='papers',
                    content_rowid='id'
                );

                -- Triggers to keep FTS index in sync with papers table
                CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers BEGIN
                    INSERT INTO papers_fts(rowid, title, authors, journal, tags, notes)
                    VALUES (new.id, new.title, new.authors, new.journal, new.tags, new.notes);
                END;

                CREATE TRIGGER IF NOT EXISTS papers_ad AFTER DELETE ON papers BEGIN
                    INSERT INTO papers_fts(papers_fts, rowid, title, authors, journal, tags, notes)
                    VALUES ('delete', old.id, old.title, old.authors, old.journal, old.tags, old.notes);
                END;

                CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers BEGIN
                    INSERT INTO papers_fts(papers_fts, rowid, title, authors, journal, tags, notes)
                    VALUES ('delete', old.id, old.title, old.authors, old.journal, old.tags, old.notes);
                    INSERT INTO papers_fts(rowid, title, authors, journal, tags, notes)
                    VALUES (new.id, new.title, new.authors, new.journal, new.tags, new.notes);
                END;
            """)
            await db.commit()
            logger.info("PaperLibrary: FTS5 table and triggers ensured.")
        except Exception as exc:
            logger.warning("PaperLibrary: FTS5 setup failed (may already exist): %s", exc)

    async def rebuild_fts_index(self) -> None:
        """Rebuild the FTS index from scratch. Useful after bulk imports."""
        db = await get_db()
        try:
            await db.execute("INSERT INTO papers_fts(papers_fts) VALUES ('rebuild')")
            await db.commit()
            logger.info("PaperLibrary: FTS index rebuilt.")
        except Exception as exc:
            logger.error("PaperLibrary: FTS rebuild failed: %s", exc)

    # ------------------------------------------------------------------
    # CRUD: Create
    # ------------------------------------------------------------------

    async def create_paper(
        self,
        title: str,
        folder_name: str,
        authors: Optional[str] = None,
        year: Optional[int] = None,
        journal: Optional[str] = None,
        doi: Optional[str] = None,
        domain: str = "optics",
        agent_used: str = "photon",
        tags: Optional[list[str]] = None,
        notes: Optional[str] = None,
    ) -> int:
        """
        Insert a new paper record.

        Args:
            title: Paper title.
            folder_name: Directory name under papers/ (e.g., "2024_Kim_TMDC_Growth").
            authors: Comma-separated author string.
            year: Publication year.
            journal: Journal name.
            doi: Digital Object Identifier.
            domain: Domain classification.
            agent_used: Agent identifier.
            tags: List of tag strings.
            notes: Free-form user notes.

        Returns:
            The new paper ID.
        """
        tags_json = json.dumps(tags, ensure_ascii=False) if tags else None

        paper_id = await execute_insert(
            """
            INSERT INTO papers
                (title, authors, year, journal, doi, domain, agent_used,
                 folder_name, tags, notes, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (title, authors, year, journal, doi, domain, agent_used,
             folder_name, tags_json, notes),
        )

        logger.info("PaperLibrary: Created paper %d: %s", paper_id, title)
        return paper_id

    # ------------------------------------------------------------------
    # CRUD: Read
    # ------------------------------------------------------------------

    async def get_paper(self, paper_id: int) -> Optional[dict]:
        """Get a single paper by ID."""
        row = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
        if row:
            row["tags"] = self._parse_tags(row.get("tags"))
        return row

    async def list_papers(
        self,
        page: int = 1,
        page_size: int = 20,
        domain: Optional[str] = None,
        status: Optional[str] = None,
        year: Optional[int] = None,
        tag: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "DESC",
    ) -> dict[str, Any]:
        """
        List papers with filtering, pagination, and sorting.

        Returns:
            Dict with keys: papers, total, page, page_size.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if domain:
            conditions.append("domain = ?")
            params.append(domain)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if year:
            conditions.append("year = ?")
            params.append(year)
        if tag:
            # Search inside JSON array stored as text
            conditions.append("tags LIKE ?")
            params.append(f"%{tag}%")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Validate sort column
        valid_sorts = {"created_at", "title", "year", "journal", "status", "analyzed_at"}
        if sort_by not in valid_sorts:
            sort_by = "created_at"
        if sort_order.upper() not in ("ASC", "DESC"):
            sort_order = "DESC"

        # Count
        count_row = await fetch_one(
            f"SELECT COUNT(*) as cnt FROM papers WHERE {where_clause}",
            tuple(params),
        )
        total = count_row["cnt"] if count_row else 0

        # Fetch page
        offset = (page - 1) * page_size
        rows = await fetch_all(
            f"""
            SELECT * FROM papers
            WHERE {where_clause}
            ORDER BY {sort_by} {sort_order}
            LIMIT ? OFFSET ?
            """,
            tuple(params) + (page_size, offset),
        )

        # Parse tags
        for row in rows:
            row["tags"] = self._parse_tags(row.get("tags"))

        return {
            "papers": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # ------------------------------------------------------------------
    # CRUD: Update
    # ------------------------------------------------------------------

    async def update_paper(self, paper_id: int, **fields) -> int:
        """
        Update paper fields.

        Args:
            paper_id: Paper ID to update.
            **fields: Field name-value pairs to update. Supports all papers columns.

        Returns:
            Number of rows affected.
        """
        if not fields:
            return 0

        # Handle tags specially
        if "tags" in fields and isinstance(fields["tags"], list):
            fields["tags"] = json.dumps(fields["tags"], ensure_ascii=False)

        set_parts: list[str] = []
        params: list[Any] = []
        for col, val in fields.items():
            set_parts.append(f"{col} = ?")
            params.append(val)

        params.append(paper_id)

        affected = await execute_update(
            f"UPDATE papers SET {', '.join(set_parts)} WHERE id = ?",
            tuple(params),
        )
        logger.info("PaperLibrary: Updated paper %d, fields: %s", paper_id, list(fields.keys()))
        return affected

    # ------------------------------------------------------------------
    # CRUD: Delete
    # ------------------------------------------------------------------

    async def delete_paper(self, paper_id: int, delete_files: bool = True) -> bool:
        """
        Delete a paper from the database and optionally from disk.

        Args:
            paper_id: Paper ID.
            delete_files: If True, also remove the paper's directory.

        Returns:
            True if deleted, False if not found.
        """
        paper = await self.get_paper(paper_id)
        if not paper:
            return False

        # Delete from DB (CASCADE deletes analysis_results and figures)
        affected = await execute_update("DELETE FROM papers WHERE id = ?", (paper_id,))

        # Delete files
        if delete_files and paper.get("folder_name"):
            import shutil
            paper_path = get_paper_dir(paper["folder_name"])
            if paper_path.exists():
                try:
                    shutil.rmtree(paper_path)
                    logger.info("PaperLibrary: Deleted folder %s", paper_path)
                except Exception as exc:
                    logger.error("PaperLibrary: Failed to delete folder: %s", exc)

        logger.info("PaperLibrary: Deleted paper %d", paper_id)
        return affected > 0

    # ------------------------------------------------------------------
    # Search (FTS5)
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """
        Full-text search using SQLite FTS5.

        Args:
            query: Search query string (supports FTS5 syntax).
            page: Page number (1-based).
            page_size: Results per page.

        Returns:
            Dict with keys: papers, total, page, page_size.
        """
        # Sanitize query for FTS5
        safe_query = self._sanitize_fts_query(query)

        try:
            # Count
            count_row = await fetch_one(
                """
                SELECT COUNT(*) as cnt
                FROM papers_fts
                WHERE papers_fts MATCH ?
                """,
                (safe_query,),
            )
            total = count_row["cnt"] if count_row else 0

            # Fetch results
            offset = (page - 1) * page_size
            rows = await fetch_all(
                """
                SELECT p.*,
                       rank
                FROM papers_fts
                JOIN papers p ON p.id = papers_fts.rowid
                WHERE papers_fts MATCH ?
                ORDER BY rank
                LIMIT ? OFFSET ?
                """,
                (safe_query, page_size, offset),
            )

            for row in rows:
                row["tags"] = self._parse_tags(row.get("tags"))
                row.pop("rank", None)

            return {
                "papers": rows,
                "total": total,
                "page": page,
                "page_size": page_size,
            }

        except Exception as exc:
            logger.error("PaperLibrary: FTS search failed: %s", exc)
            # Fallback to LIKE search
            return await self._search_fallback(query, page, page_size)

    async def _search_fallback(
        self, query: str, page: int, page_size: int
    ) -> dict[str, Any]:
        """LIKE-based fallback search when FTS5 is not available."""
        like_pattern = f"%{query}%"
        conditions = (
            "title LIKE ? OR authors LIKE ? OR journal LIKE ? "
            "OR tags LIKE ? OR notes LIKE ?"
        )
        params = (like_pattern,) * 5

        count_row = await fetch_one(
            f"SELECT COUNT(*) as cnt FROM papers WHERE {conditions}",
            params,
        )
        total = count_row["cnt"] if count_row else 0

        offset = (page - 1) * page_size
        rows = await fetch_all(
            f"""
            SELECT * FROM papers
            WHERE {conditions}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + (page_size, offset),
        )

        for row in rows:
            row["tags"] = self._parse_tags(row.get("tags"))

        return {
            "papers": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # ------------------------------------------------------------------
    # Tag Management
    # ------------------------------------------------------------------

    async def add_tag(self, paper_id: int, tag: str) -> list[str]:
        """
        Add a tag to a paper. Returns the updated tag list.
        """
        paper = await self.get_paper(paper_id)
        if not paper:
            raise ValueError(f"Paper {paper_id} not found")

        tags = paper.get("tags", []) or []
        if isinstance(tags, str):
            tags = self._parse_tags(tags)

        tag = tag.strip()
        if tag and tag not in tags:
            tags.append(tag)
            await self.update_paper(paper_id, tags=tags)

        return tags

    async def remove_tag(self, paper_id: int, tag: str) -> list[str]:
        """
        Remove a tag from a paper. Returns the updated tag list.
        """
        paper = await self.get_paper(paper_id)
        if not paper:
            raise ValueError(f"Paper {paper_id} not found")

        tags = paper.get("tags", []) or []
        if isinstance(tags, str):
            tags = self._parse_tags(tags)

        tag = tag.strip()
        if tag in tags:
            tags.remove(tag)
            await self.update_paper(paper_id, tags=tags)

        return tags

    async def get_all_tags(self) -> list[dict[str, Any]]:
        """
        Get all unique tags across the library with counts.

        Returns:
            List of {"tag": str, "count": int} sorted by count descending.
        """
        rows = await fetch_all("SELECT tags FROM papers WHERE tags IS NOT NULL AND tags != ''")
        tag_counts: dict[str, int] = {}
        for row in rows:
            tags = self._parse_tags(row.get("tags"))
            for t in tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1

        result = [{"tag": t, "count": c} for t, c in tag_counts.items()]
        result.sort(key=lambda x: x["count"], reverse=True)
        return result

    # ------------------------------------------------------------------
    # Notes Management
    # ------------------------------------------------------------------

    async def update_notes(self, paper_id: int, notes: str) -> int:
        """Set or update user notes for a paper."""
        return await self.update_paper(paper_id, notes=notes)

    async def get_notes(self, paper_id: int) -> Optional[str]:
        """Get notes for a paper."""
        paper = await self.get_paper(paper_id)
        return paper.get("notes") if paper else None

    # ------------------------------------------------------------------
    # Cost Tracking
    # ------------------------------------------------------------------

    async def get_paper_cost(self, paper_id: int) -> dict[str, Any]:
        """
        Get the total API cost for analyzing a specific paper.

        Returns:
            Dict with total_cost_usd, total_tokens_in, total_tokens_out,
            by_phase breakdown.
        """
        rows = await fetch_all(
            """
            SELECT phase, model_used, tokens_in, tokens_out, cost_usd
            FROM analysis_results
            WHERE paper_id = ?
            """,
            (paper_id,),
        )

        total_cost = 0.0
        total_in = 0
        total_out = 0
        by_phase: dict[str, float] = {}
        by_model: dict[str, float] = {}

        for row in rows:
            cost = row.get("cost_usd", 0.0) or 0.0
            t_in = row.get("tokens_in", 0) or 0
            t_out = row.get("tokens_out", 0) or 0
            phase = row.get("phase", "unknown")
            model = row.get("model_used", "unknown")

            total_cost += cost
            total_in += t_in
            total_out += t_out
            by_phase[phase] = by_phase.get(phase, 0.0) + cost
            by_model[model] = by_model.get(model, 0.0) + cost

        return {
            "paper_id": paper_id,
            "total_cost_usd": round(total_cost, 6),
            "total_tokens_in": total_in,
            "total_tokens_out": total_out,
            "by_phase": by_phase,
            "by_model": by_model,
        }

    async def get_monthly_cost(
        self, year: Optional[int] = None, month: Optional[int] = None
    ) -> dict[str, Any]:
        """
        Get aggregated API cost for a specific month.

        Args:
            year: Year (default: current year).
            month: Month 1-12 (default: current month).

        Returns:
            Dict matching CostSummary schema.
        """
        now = datetime.now()
        year = year or now.year
        month = month or now.month

        month_str = f"{year}-{month:02d}"
        start = f"{month_str}-01"
        # Compute end of month
        if month == 12:
            end = f"{year + 1}-01-01"
        else:
            end = f"{year}-{month + 1:02d}-01"

        rows = await fetch_all(
            """
            SELECT ar.phase, ar.model_used, ar.tokens_in, ar.tokens_out,
                   ar.cost_usd, ar.created_at
            FROM analysis_results ar
            WHERE ar.created_at >= ? AND ar.created_at < ?
            """,
            (start, end),
        )

        total_cost = 0.0
        total_in = 0
        total_out = 0
        by_model: dict[str, float] = {}
        by_phase: dict[str, float] = {}
        daily: dict[str, dict[str, float]] = {}

        for row in rows:
            cost = row.get("cost_usd", 0.0) or 0.0
            t_in = row.get("tokens_in", 0) or 0
            t_out = row.get("tokens_out", 0) or 0
            model = row.get("model_used", "unknown") or "unknown"
            phase = row.get("phase", "unknown") or "unknown"
            created = row.get("created_at", "")

            total_cost += cost
            total_in += t_in
            total_out += t_out
            by_model[model] = by_model.get(model, 0.0) + cost
            by_phase[phase] = by_phase.get(phase, 0.0) + cost

            # Daily breakdown
            day_str = created[:10] if created else "unknown"
            if day_str not in daily:
                daily[day_str] = {"cost_usd": 0.0, "count": 0}
            daily[day_str]["cost_usd"] += cost
            daily[day_str]["count"] += 1

        daily_breakdown = [
            {"date": d, "cost_usd": round(v["cost_usd"], 6), "analysis_count": v["count"]}
            for d, v in sorted(daily.items())
        ]

        return {
            "month": month_str,
            "total_cost_usd": round(total_cost, 6),
            "total_tokens_in": total_in,
            "total_tokens_out": total_out,
            "by_model": {k: round(v, 6) for k, v in by_model.items()},
            "by_phase": {k: round(v, 6) for k, v in by_phase.items()},
            "daily_breakdown": daily_breakdown,
        }

    # ------------------------------------------------------------------
    # Library Statistics
    # ------------------------------------------------------------------

    async def get_stats(self) -> dict[str, Any]:
        """
        Get overall library statistics.

        Returns:
            Dict with total papers, domain/status/agent counts, cost totals.
        """
        total_row = await fetch_one("SELECT COUNT(*) as cnt FROM papers")
        total = total_row["cnt"] if total_row else 0

        # By status
        status_rows = await fetch_all(
            "SELECT status, COUNT(*) as cnt FROM papers GROUP BY status"
        )
        by_status = {row["status"]: row["cnt"] for row in status_rows}

        # By domain
        domain_rows = await fetch_all(
            "SELECT domain, COUNT(*) as cnt FROM papers GROUP BY domain"
        )
        by_domain = {row["domain"]: row["cnt"] for row in domain_rows}

        # By agent
        agent_rows = await fetch_all(
            "SELECT agent_used, COUNT(*) as cnt FROM papers GROUP BY agent_used"
        )
        by_agent = {row["agent_used"]: row["cnt"] for row in agent_rows}

        # By year
        year_rows = await fetch_all(
            "SELECT year, COUNT(*) as cnt FROM papers WHERE year IS NOT NULL GROUP BY year ORDER BY year DESC"
        )
        by_year = {row["year"]: row["cnt"] for row in year_rows}

        # Total cost
        cost_row = await fetch_one(
            "SELECT SUM(cost_usd) as total_cost, SUM(tokens_in) as total_in, "
            "SUM(tokens_out) as total_out FROM analysis_results"
        )
        total_cost = cost_row["total_cost"] if cost_row and cost_row["total_cost"] else 0.0
        total_tokens_in = cost_row["total_in"] if cost_row and cost_row["total_in"] else 0
        total_tokens_out = cost_row["total_out"] if cost_row and cost_row["total_out"] else 0

        # Total analyses
        analysis_count_row = await fetch_one(
            "SELECT COUNT(*) as cnt FROM analysis_results"
        )
        total_analyses = analysis_count_row["cnt"] if analysis_count_row else 0

        # Total figures
        figure_count_row = await fetch_one(
            "SELECT COUNT(*) as cnt FROM figures"
        )
        total_figures = figure_count_row["cnt"] if figure_count_row else 0

        # Average cost per paper
        completed_row = await fetch_one(
            "SELECT COUNT(DISTINCT paper_id) as cnt FROM analysis_results"
        )
        analyzed_count = completed_row["cnt"] if completed_row else 0
        avg_cost = total_cost / analyzed_count if analyzed_count > 0 else 0.0

        return {
            "total_papers": total,
            "by_status": by_status,
            "by_domain": by_domain,
            "by_agent": by_agent,
            "by_year": by_year,
            "total_analyses": total_analyses,
            "total_figures": total_figures,
            "total_cost_usd": round(total_cost, 4),
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "avg_cost_per_paper": round(avg_cost, 4),
            "analyzed_papers": analyzed_count,
        }

    # ------------------------------------------------------------------
    # Analysis Results (read-only convenience)
    # ------------------------------------------------------------------

    async def get_analysis_results(self, paper_id: int) -> list[dict]:
        """Get all analysis results for a paper."""
        rows = await fetch_all(
            """
            SELECT * FROM analysis_results
            WHERE paper_id = ?
            ORDER BY created_at ASC
            """,
            (paper_id,),
        )
        for row in rows:
            # Parse JSON result
            try:
                row["parsed_result"] = json.loads(row.get("result", "{}"))
            except (json.JSONDecodeError, TypeError):
                row["parsed_result"] = {"raw": row.get("result", "")}
        return rows

    async def get_phase_result(self, paper_id: int, phase: str) -> Optional[dict]:
        """Get a specific phase result for a paper."""
        row = await fetch_one(
            """
            SELECT * FROM analysis_results
            WHERE paper_id = ? AND phase = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (paper_id, phase),
        )
        if row:
            try:
                row["parsed_result"] = json.loads(row.get("result", "{}"))
            except (json.JSONDecodeError, TypeError):
                row["parsed_result"] = {"raw": row.get("result", "")}
        return row

    async def get_figures(self, paper_id: int) -> list[dict]:
        """Get all figures for a paper."""
        return await fetch_all(
            "SELECT * FROM figures WHERE paper_id = ? ORDER BY figure_num",
            (paper_id,),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_tags(self, tags_value: Any) -> list[str]:
        """Parse tags from DB value (JSON string or already list)."""
        if tags_value is None:
            return []
        if isinstance(tags_value, list):
            return tags_value
        if isinstance(tags_value, str):
            try:
                parsed = json.loads(tags_value)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
            # Might be comma-separated
            if "," in tags_value:
                return [t.strip() for t in tags_value.split(",") if t.strip()]
            return [tags_value] if tags_value.strip() else []
        return []

    def _sanitize_fts_query(self, query: str) -> str:
        """
        Sanitize a user query for FTS5 MATCH syntax.
        Wraps each token in double quotes to prevent syntax errors.
        """
        # Remove FTS5 special characters that could cause parse errors
        # but preserve user intent
        query = query.strip()
        if not query:
            return '""'

        # If query already uses FTS5 operators, pass through
        fts_operators = {" AND ", " OR ", " NOT ", " NEAR/"}
        if any(op in query.upper() for op in fts_operators):
            return query

        # Otherwise, wrap each word in quotes for safety
        tokens = query.split()
        safe_tokens = [f'"{t}"' for t in tokens if t]
        return " ".join(safe_tokens)
