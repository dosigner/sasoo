"""
Sasoo - 4-Phase Analysis Pipeline

Orchestrates the sequential analysis of a research paper through four phases:
  Phase 1: Screening (Flash, minimal thinking) - Abstract + Conclusion
  Phase 2: Visual Verification (Flash, medium thinking) - Figures + Captions
  Phase 3: Recipe Extraction (Pro, high thinking) - Method section
  Phase 4: Deep Dive (Pro, high thinking) - Intro + Results

After Phase 3-4, the Visualization Router identifies targets and generates
Mermaid diagrams (Claude Sonnet 4.5) and PaperBanana illustrations (Gemini
Pro Image) in parallel.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

from models.database import (
    execute_insert,
    execute_update,
    fetch_all,
    get_paper_dir,
    PAPERS_DIR,
)
from models.schemas import AnalysisPhase

from services.viz.viz_router import VizRouter, VizRouterOutput
from services.viz.mermaid_generator import MermaidGenerator, MermaidOutput
from services.viz.paperbanana_bridge import PaperBananaBridge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class TokenUsage:
    """Token usage for a single API call."""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model: str = ""


@dataclass
class PhaseResult:
    """Result of a single analysis phase."""
    phase: AnalysisPhase
    status: str = "pending"  # pending | running | completed | error
    result: Optional[dict] = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    error_message: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    @property
    def duration_seconds(self) -> float:
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return 0.0


@dataclass
class AnalysisReport:
    """Complete analysis report across all phases + visualization."""
    paper_id: int
    status: str = "pending"  # pending | running | completed | error
    phases: dict[str, PhaseResult] = field(default_factory=dict)
    viz_output: Optional[VizRouterOutput] = None
    mermaid_outputs: list[MermaidOutput] = field(default_factory=list)
    paperbanana_paths: list[Optional[str]] = field(default_factory=list)
    total_cost_usd: float = 0.0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        phases_dict = {}
        for phase_name, pr in self.phases.items():
            phases_dict[phase_name] = {
                "status": pr.status,
                "result": pr.result,
                "model_used": pr.usage.model,
                "tokens_in": pr.usage.tokens_in,
                "tokens_out": pr.usage.tokens_out,
                "cost_usd": pr.usage.cost_usd,
                "error_message": pr.error_message,
                "duration_seconds": pr.duration_seconds,
            }

        return {
            "paper_id": self.paper_id,
            "status": self.status,
            "phases": phases_dict,
            "viz_output": self.viz_output.to_dict() if self.viz_output else None,
            "mermaid_outputs": [m.to_dict() for m in self.mermaid_outputs],
            "paperbanana_paths": self.paperbanana_paths,
            "total_cost_usd": self.total_cost_usd,
            "total_tokens_in": self.total_tokens_in,
            "total_tokens_out": self.total_tokens_out,
        }


# Progress callback type
ProgressCallback = Callable[[str, float, str], Coroutine[Any, Any, None]]
# Signature: async callback(phase_name: str, progress_pct: float, message: str)


# ---------------------------------------------------------------------------
# Cost Constants (per 1M tokens)
# ---------------------------------------------------------------------------

_COST_TABLE = {
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    "gemini-3-pro-preview": {"input": 2.00, "output": 12.00},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
}


def _calc_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Calculate USD cost for a given model and token counts."""
    rates = _COST_TABLE.get(model, {"input": 0.0, "output": 0.0})
    cost = (tokens_in / 1_000_000) * rates["input"] + (tokens_out / 1_000_000) * rates["output"]
    return round(cost, 6)


# ---------------------------------------------------------------------------
# AnalysisPipeline
# ---------------------------------------------------------------------------

class AnalysisPipeline:
    """
    Orchestrates the 4-phase analysis pipeline for a single paper.

    Constructor dependencies:
        gemini_client: GeminiClient for Gemini Flash/Pro calls.
        claude_client: ClaudeClient for Sonnet 4.5 Mermaid generation.
        base_agent: BaseAgent (e.g., AgentPhoton) that provides domain-specific
                     system prompts for each phase.
        section_splitter: SectionSplitter instance for extracting sections from
                          full text (used if pre-split sections are not provided).
    """

    def __init__(
        self,
        gemini_client: Any,
        claude_client: Any,
        base_agent: Any,
        section_splitter: Any,
    ):
        self._gemini = gemini_client
        self._claude = claude_client
        self._agent = base_agent
        self._splitter = section_splitter

        # Build sub-components
        self._viz_router = VizRouter(gemini_client=gemini_client)
        self._mermaid_gen = MermaidGenerator(claude_client=claude_client)
        self._pb_bridge = PaperBananaBridge()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run_full_analysis(
        self,
        paper_id: int,
        parsed_paper: Any,
        sections: dict[str, str],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> AnalysisReport:
        """
        Run the complete 4-phase analysis pipeline.

        Args:
            paper_id: Database ID of the paper.
            parsed_paper: ParsedPaper object from PdfParser.
            sections: Dict of section name -> text (e.g., from SectionSplitter).
            progress_callback: Optional async callback for progress updates.

        Returns:
            AnalysisReport with all phase results and visualization outputs.
        """
        report = AnalysisReport(paper_id=paper_id, status="running")
        report.started_at = time.time()

        # Resolve paper directory
        paper_dir = self._resolve_paper_dir(parsed_paper)

        # Update paper status to analyzing
        await self._update_paper_status(paper_id, "analyzing")

        # If sections are empty, try splitting from parsed paper
        if not sections and parsed_paper and hasattr(parsed_paper, "full_text"):
            try:
                sections = self._splitter.split(parsed_paper.full_text)
            except Exception as exc:
                logger.warning("Section splitting failed: %s", exc)
                sections = {"full_text": parsed_paper.full_text}

        # Helper for progress reporting
        async def _emit(phase: str, pct: float, msg: str) -> None:
            if progress_callback:
                try:
                    await progress_callback(phase, pct, msg)
                except Exception:
                    pass  # Never let callback errors break the pipeline

        # ----- Phase 1: Screening -----
        await _emit("screening", 0.0, "Starting Phase 1: Screening...")
        report.phases["screening"] = await self._run_phase_screening(
            paper_id=paper_id,
            sections=sections,
            parsed_paper=parsed_paper,
        )
        await _emit("screening", 25.0, "Phase 1 complete.")

        # ----- Phase 2: Visual Verification -----
        await _emit("visual", 25.0, "Starting Phase 2: Visual Verification...")
        report.phases["visual"] = await self._run_phase_visual(
            paper_id=paper_id,
            parsed_paper=parsed_paper,
        )
        await _emit("visual", 50.0, "Phase 2 complete.")

        # ----- Phase 3: Recipe Extraction -----
        await _emit("recipe", 50.0, "Starting Phase 3: Recipe Extraction...")
        report.phases["recipe"] = await self._run_phase_recipe(
            paper_id=paper_id,
            sections=sections,
            parsed_paper=parsed_paper,
        )
        await _emit("recipe", 75.0, "Phase 3 complete.")

        # ----- Phase 4: Deep Dive -----
        await _emit("deep_dive", 75.0, "Starting Phase 4: Deep Dive...")
        report.phases["deep_dive"] = await self._run_phase_deep_dive(
            paper_id=paper_id,
            sections=sections,
            parsed_paper=parsed_paper,
        )
        await _emit("deep_dive", 90.0, "Phase 4 complete.")

        # ----- Visualization Routing + Generation -----
        await _emit("visualization", 90.0, "Running Visualization Router...")
        await self._run_visualization(report=report, paper_dir=paper_dir)
        await _emit("visualization", 100.0, "Visualization complete.")

        # ----- Finalize -----
        report.completed_at = time.time()

        # Accumulate totals
        for pr in report.phases.values():
            report.total_tokens_in += pr.usage.tokens_in
            report.total_tokens_out += pr.usage.tokens_out
            report.total_cost_usd += pr.usage.cost_usd

        # Determine overall status
        error_phases = [p for p in report.phases.values() if p.status == "error"]
        if len(error_phases) == len(report.phases):
            report.status = "error"
        elif error_phases:
            report.status = "completed"  # partial success
        else:
            report.status = "completed"

        # Update paper status
        final_status = "completed" if report.status == "completed" else "error"
        await self._update_paper_status(paper_id, final_status)

        return report

    # ------------------------------------------------------------------
    # Phase 1: Screening
    # ------------------------------------------------------------------

    async def _run_phase_screening(
        self,
        paper_id: int,
        sections: dict[str, str],
        parsed_paper: Any,
    ) -> PhaseResult:
        """
        Phase 1: Screening analysis.
        Input: Abstract + Conclusion
        Model: Gemini 3.0 Flash (minimal thinking)
        """
        phase_result = PhaseResult(phase=AnalysisPhase.SCREENING, status="running")
        phase_result.started_at = time.time()
        model = "gemini-3-flash-preview"

        try:
            # Build input text from relevant sections
            input_parts: list[str] = []
            for key in ("abstract", "conclusion", "conclusions", "summary"):
                if key in sections and sections[key]:
                    input_parts.append(f"=== {key.title()} ===\n{sections[key]}")

            # Fallback: use first/last portions of full text
            if not input_parts:
                full_text = sections.get("full_text", "")
                if not full_text and parsed_paper:
                    full_text = getattr(parsed_paper, "full_text", "")
                if full_text:
                    # Use first 2000 and last 2000 chars as proxy
                    input_parts.append(
                        "=== Beginning (Abstract area) ===\n" + full_text[:2000]
                    )
                    if len(full_text) > 4000:
                        input_parts.append(
                            "=== End (Conclusion area) ===\n" + full_text[-2000:]
                        )

            input_text = "\n\n".join(input_parts)

            # Get agent system prompt for this phase
            system_prompt = self._agent.get_system_prompt("screening")

            # Call Gemini Flash with minimal thinking
            response = await self._gemini.generate(
                prompt=input_text,
                model=model,
                system_prompt=system_prompt,
                temperature=0.3,
                thinking_level="minimal",
                response_mime_type="application/json",
            )

            result_data = self._parse_json_response(response)

            # Extract token usage
            usage = self._extract_usage(response, model)

            phase_result.result = result_data
            phase_result.usage = usage
            phase_result.status = "completed"

            # Check relevance and log
            relevance = result_data.get("relevance_score", result_data.get("relevance", ""))
            if isinstance(relevance, str) and relevance.lower() == "low":
                logger.info(
                    "Paper %d: Low relevance detected in screening. "
                    "Continuing analysis (user can choose to skip).",
                    paper_id,
                )

        except Exception as exc:
            logger.error("Phase 1 (Screening) failed for paper %d: %s", paper_id, exc)
            phase_result.status = "error"
            phase_result.error_message = str(exc)

        phase_result.completed_at = time.time()

        # Persist to DB
        await self._store_phase_result(paper_id, phase_result)

        return phase_result

    # ------------------------------------------------------------------
    # Phase 2: Visual Verification
    # ------------------------------------------------------------------

    async def _run_phase_visual(
        self,
        paper_id: int,
        parsed_paper: Any,
    ) -> PhaseResult:
        """
        Phase 2: Visual verification.
        Input: Extracted figures + captions
        Model: Gemini 3.0 Flash (medium thinking, multimodal)
        """
        phase_result = PhaseResult(phase=AnalysisPhase.VISUAL, status="running")
        phase_result.started_at = time.time()
        model = "gemini-3-flash-preview"

        try:
            # Build figure descriptions
            figure_descriptions: list[str] = []
            figure_paths: list[str] = []

            if parsed_paper and hasattr(parsed_paper, "figures"):
                for fig in parsed_paper.figures:
                    desc = f"Figure: {fig.figure_id} (Page {fig.page_number})"
                    if fig.caption:
                        desc += f"\nCaption: {fig.caption}"
                    figure_descriptions.append(desc)
                    if fig.image_path and Path(fig.image_path).exists():
                        figure_paths.append(str(fig.image_path))

            # Build table descriptions
            if parsed_paper and hasattr(parsed_paper, "tables"):
                for tbl in parsed_paper.tables:
                    desc = f"Table: {tbl.table_id} (Page {tbl.page_number})"
                    if tbl.caption:
                        desc += f"\nCaption: {tbl.caption}"
                    if tbl.data:
                        # Include first few rows
                        preview_rows = tbl.data[:4]
                        desc += f"\nData preview: {json.dumps(preview_rows, ensure_ascii=False)}"
                    figure_descriptions.append(desc)

            input_text = "\n\n".join(figure_descriptions)
            if not input_text:
                input_text = "No figures or tables were extracted from this paper."

            system_prompt = self._agent.get_system_prompt("visual")

            # Call Gemini Flash with medium thinking (multimodal if images available)
            if figure_paths:
                response = await self._gemini.generate_multimodal(
                    prompt=input_text,
                    image_paths=figure_paths[:10],  # Limit to 10 figures
                    model=model,
                    system_prompt=system_prompt,
                    temperature=0.4,
                    thinking_level="medium",
                    response_mime_type="application/json",
                )
            else:
                response = await self._gemini.generate(
                    prompt=input_text,
                    model=model,
                    system_prompt=system_prompt,
                    temperature=0.4,
                    thinking_level="medium",
                    response_mime_type="application/json",
                )

            result_data = self._parse_json_response(response)
            usage = self._extract_usage(response, model)

            phase_result.result = result_data
            phase_result.usage = usage
            phase_result.status = "completed"

            # Store figure analysis results to DB
            await self._store_figure_analyses(paper_id, result_data, parsed_paper)

        except Exception as exc:
            logger.error("Phase 2 (Visual) failed for paper %d: %s", paper_id, exc)
            phase_result.status = "error"
            phase_result.error_message = str(exc)

        phase_result.completed_at = time.time()
        await self._store_phase_result(paper_id, phase_result)

        return phase_result

    # ------------------------------------------------------------------
    # Phase 3: Recipe Extraction
    # ------------------------------------------------------------------

    async def _run_phase_recipe(
        self,
        paper_id: int,
        sections: dict[str, str],
        parsed_paper: Any,
    ) -> PhaseResult:
        """
        Phase 3: Recipe extraction.
        Input: Method / Experimental section
        Model: Gemini 3.0 Pro (high thinking)
        """
        phase_result = PhaseResult(phase=AnalysisPhase.RECIPE, status="running")
        phase_result.started_at = time.time()
        model = "gemini-3-pro-preview"

        try:
            # Build input from method-related sections
            input_parts: list[str] = []
            method_keys = [
                "method", "methods", "experimental", "materials and methods",
                "materials_and_methods", "procedure", "fabrication",
            ]
            for key in method_keys:
                if key in sections and sections[key]:
                    input_parts.append(f"=== {key.title()} ===\n{sections[key]}")

            if not input_parts:
                # Fallback: use middle portion of the paper
                full_text = sections.get("full_text", "")
                if not full_text and parsed_paper:
                    full_text = getattr(parsed_paper, "full_text", "")
                if full_text:
                    mid = len(full_text) // 2
                    start = max(0, mid - 3000)
                    end = min(len(full_text), mid + 3000)
                    input_parts.append(
                        "=== Method/Experimental (estimated) ===\n" + full_text[start:end]
                    )

            input_text = "\n\n".join(input_parts)
            system_prompt = self._agent.get_system_prompt("recipe")

            response = await self._gemini.generate(
                prompt=input_text,
                model=model,
                system_prompt=system_prompt,
                temperature=0.2,
                thinking_level="high",
                response_mime_type="application/json",
            )

            result_data = self._parse_json_response(response)
            usage = self._extract_usage(response, model)

            phase_result.result = result_data
            phase_result.usage = usage
            phase_result.status = "completed"

        except Exception as exc:
            logger.error("Phase 3 (Recipe) failed for paper %d: %s", paper_id, exc)
            phase_result.status = "error"
            phase_result.error_message = str(exc)

        phase_result.completed_at = time.time()
        await self._store_phase_result(paper_id, phase_result)

        return phase_result

    # ------------------------------------------------------------------
    # Phase 4: Deep Dive
    # ------------------------------------------------------------------

    async def _run_phase_deep_dive(
        self,
        paper_id: int,
        sections: dict[str, str],
        parsed_paper: Any,
    ) -> PhaseResult:
        """
        Phase 4: Deep dive critical analysis.
        Input: Introduction + Results & Discussion
        Model: Gemini 3.0 Pro (high thinking)
        """
        phase_result = PhaseResult(phase=AnalysisPhase.DEEP_DIVE, status="running")
        phase_result.started_at = time.time()
        model = "gemini-3-pro-preview"

        try:
            input_parts: list[str] = []
            deep_keys = [
                "introduction", "results", "results and discussion",
                "results_and_discussion", "discussion",
            ]
            for key in deep_keys:
                if key in sections and sections[key]:
                    input_parts.append(f"=== {key.title()} ===\n{sections[key]}")

            if not input_parts:
                full_text = sections.get("full_text", "")
                if not full_text and parsed_paper:
                    full_text = getattr(parsed_paper, "full_text", "")
                if full_text:
                    # Use first 3000 chars (intro) and latter half (results)
                    input_parts.append(
                        "=== Introduction (estimated) ===\n" + full_text[:3000]
                    )
                    if len(full_text) > 6000:
                        input_parts.append(
                            "=== Results & Discussion (estimated) ===\n"
                            + full_text[len(full_text)//2:]
                        )

            input_text = "\n\n".join(input_parts)
            system_prompt = self._agent.get_system_prompt("deep_dive")

            response = await self._gemini.generate(
                prompt=input_text,
                model=model,
                system_prompt=system_prompt,
                temperature=0.3,
                thinking_level="high",
                response_mime_type="application/json",
            )

            result_data = self._parse_json_response(response)
            usage = self._extract_usage(response, model)

            phase_result.result = result_data
            phase_result.usage = usage
            phase_result.status = "completed"

        except Exception as exc:
            logger.error("Phase 4 (Deep Dive) failed for paper %d: %s", paper_id, exc)
            phase_result.status = "error"
            phase_result.error_message = str(exc)

        phase_result.completed_at = time.time()
        await self._store_phase_result(paper_id, phase_result)

        return phase_result

    # ------------------------------------------------------------------
    # Visualization (post Phase 3-4)
    # ------------------------------------------------------------------

    async def _run_visualization(
        self,
        report: AnalysisReport,
        paper_dir: Optional[str],
    ) -> None:
        """
        Run Visualization Router on Phase 3-4 results, then generate
        Mermaid diagrams and PaperBanana illustrations in parallel.
        """
        recipe_result = None
        deep_dive_result = None
        screening_result = None
        visual_result = None

        if "recipe" in report.phases and report.phases["recipe"].result:
            recipe_result = report.phases["recipe"].result
        if "deep_dive" in report.phases and report.phases["deep_dive"].result:
            deep_dive_result = report.phases["deep_dive"].result
        if "screening" in report.phases and report.phases["screening"].result:
            screening_result = report.phases["screening"].result
        if "visual" in report.phases and report.phases["visual"].result:
            visual_result = report.phases["visual"].result

        # If neither Phase 3 nor 4 produced results, skip visualization
        if recipe_result is None and deep_dive_result is None:
            logger.info(
                "Paper %d: No Phase 3-4 results for visualization routing.",
                report.paper_id,
            )
            return

        try:
            # Run Viz Router
            viz_output = await self._viz_router.route(
                paper_id=report.paper_id,
                recipe_result=recipe_result,
                deep_dive_result=deep_dive_result,
                screening_result=screening_result,
                visual_result=visual_result,
            )
            report.viz_output = viz_output

            # Separate targets by render type
            mermaid_targets = [d.to_dict() for d in viz_output.mermaid_targets]
            pb_targets = [d.to_dict() for d in viz_output.paperbanana_targets]

            # Generate Mermaid and PaperBanana in parallel
            mermaid_task = self._mermaid_gen.generate_batch(
                mermaid_targets, paper_dir=paper_dir
            )
            pb_task = self._pb_bridge.generate_batch(
                pb_targets, paper_dir=paper_dir or ""
            )

            mermaid_results, pb_results = await asyncio.gather(
                mermaid_task,
                pb_task,
                return_exceptions=True,
            )

            # Handle mermaid results
            if isinstance(mermaid_results, list):
                report.mermaid_outputs = mermaid_results
            elif isinstance(mermaid_results, Exception):
                logger.error("Mermaid generation failed: %s", mermaid_results)

            # Handle PaperBanana results
            if isinstance(pb_results, list):
                report.paperbanana_paths = pb_results
            elif isinstance(pb_results, Exception):
                logger.error("PaperBanana generation failed: %s", pb_results)

            # Store viz results to DB
            await self._store_viz_results(report.paper_id, viz_output, report)

        except Exception as exc:
            logger.error(
                "Visualization pipeline failed for paper %d: %s",
                report.paper_id, exc,
            )

    # ------------------------------------------------------------------
    # DB persistence
    # ------------------------------------------------------------------

    async def _store_phase_result(self, paper_id: int, phase: PhaseResult) -> None:
        """Store a single phase result to the analysis_results table."""
        try:
            result_json = json.dumps(
                phase.result if phase.result else {"error": phase.error_message},
                ensure_ascii=False,
            )
            await execute_insert(
                """
                INSERT INTO analysis_results
                    (paper_id, phase, result, model_used, tokens_in, tokens_out, cost_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    phase.phase.value,
                    result_json,
                    phase.usage.model,
                    phase.usage.tokens_in,
                    phase.usage.tokens_out,
                    phase.usage.cost_usd,
                ),
            )
        except Exception as exc:
            logger.error(
                "Failed to store phase result for paper %d phase %s: %s",
                paper_id, phase.phase.value, exc,
            )

    async def _store_figure_analyses(
        self, paper_id: int, visual_result: dict, parsed_paper: Any
    ) -> None:
        """Store per-figure AI analysis results to the figures table."""
        try:
            figure_analyses = visual_result.get("figures", visual_result.get("figure_analyses", []))
            if not isinstance(figure_analyses, list):
                return

            for fig_data in figure_analyses:
                figure_num = fig_data.get("figure_num", fig_data.get("figure_id", ""))
                caption = fig_data.get("caption", "")
                ai_analysis = fig_data.get("ai_analysis", fig_data.get("interpretation", ""))
                quality = fig_data.get("quality", fig_data.get("data_quality", ""))
                file_path = fig_data.get("file_path", "")

                # Try to find actual file path from parsed paper
                if not file_path and parsed_paper and hasattr(parsed_paper, "figures"):
                    for pf in parsed_paper.figures:
                        if pf.figure_id == figure_num or pf.figure_id == fig_data.get("figure_id", ""):
                            file_path = str(pf.image_path) if pf.image_path else ""
                            break

                await execute_insert(
                    """
                    INSERT INTO figures
                        (paper_id, figure_num, caption, file_path, ai_analysis, quality)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (paper_id, str(figure_num), caption, file_path, ai_analysis, quality),
                )
        except Exception as exc:
            logger.error("Failed to store figure analyses for paper %d: %s", paper_id, exc)

    async def _store_viz_results(
        self,
        paper_id: int,
        viz_output: VizRouterOutput,
        report: AnalysisReport,
    ) -> None:
        """Store visualization results as a special analysis_results entry."""
        try:
            viz_data = {
                "viz_router": viz_output.to_dict(),
                "mermaid_diagrams": [m.to_dict() for m in report.mermaid_outputs],
                "paperbanana_images": [p for p in report.paperbanana_paths if p],
            }
            await execute_insert(
                """
                INSERT INTO analysis_results
                    (paper_id, phase, result, model_used, tokens_in, tokens_out, cost_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    "visualization",
                    json.dumps(viz_data, ensure_ascii=False),
                    "mixed",
                    0,
                    0,
                    0.0,
                ),
            )
        except Exception as exc:
            logger.error("Failed to store viz results for paper %d: %s", paper_id, exc)

    async def _update_paper_status(self, paper_id: int, status: str) -> None:
        """Update the paper's status and analyzed_at timestamp."""
        try:
            if status == "completed":
                await execute_update(
                    "UPDATE papers SET status = ?, analyzed_at = ? WHERE id = ?",
                    (status, datetime.now().isoformat(), paper_id),
                )
            else:
                await execute_update(
                    "UPDATE papers SET status = ? WHERE id = ?",
                    (status, paper_id),
                )
        except Exception as exc:
            logger.error("Failed to update paper status for %d: %s", paper_id, exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_paper_dir(self, parsed_paper: Any) -> Optional[str]:
        """Get the paper's storage directory path."""
        if parsed_paper and hasattr(parsed_paper, "base_path") and parsed_paper.base_path:
            return str(parsed_paper.base_path)
        return None

    def _parse_json_response(self, response: Any) -> dict:
        """Parse an LLM response into a dict, handling various response types."""
        # Direct dict
        if isinstance(response, dict):
            return response

        # String
        text = None
        if isinstance(response, str):
            text = response
        else:
            # Try common response object attributes
            text = getattr(response, "text", None)
            if text is None:
                content = getattr(response, "content", None)
                if content:
                    if isinstance(content, list) and content:
                        text = getattr(content[0], "text", str(content[0]))
                    elif isinstance(content, str):
                        text = content

        if text is None:
            text = str(response)

        # Strip markdown JSON fences
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON response, returning raw text.")
            return {"raw_response": text}

    def _extract_usage(self, response: Any, model: str) -> TokenUsage:
        """Extract token usage info from an LLM response object."""
        tokens_in = 0
        tokens_out = 0

        # Try common patterns for usage metadata
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            usage = getattr(response, "usage", None)

        if usage:
            tokens_in = getattr(usage, "prompt_token_count", 0) or \
                         getattr(usage, "input_tokens", 0) or 0
            tokens_out = getattr(usage, "candidates_token_count", 0) or \
                          getattr(usage, "output_tokens", 0) or 0

        cost = _calc_cost(model, tokens_in, tokens_out)

        return TokenUsage(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            model=model,
        )
