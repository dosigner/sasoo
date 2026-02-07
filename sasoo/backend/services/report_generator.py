"""
Sasoo - Report Generator

Generates an integrated Markdown report matching PRD Section F6 format:
  - Header: title, authors, journal, year, DOI, agent used, analysis date
  - Phase 1: Screening (relevance, keywords, summary)
  - Phase 2: Visual Verification (figure gallery, data quality table)
  - Phase 3: Recipe Card (parameter table, missing param warnings, Mermaid)
  - Phase 4: Deep Dive (background, prior work, critical analysis, limitations)
  - PaperBanana illustrations

Also generates a separate recipe_card.md file.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ReportGenerator:
    """
    Generates integrated Markdown reports from analysis pipeline results.

    The report format follows the PRD Section F6 specification exactly,
    producing a self-contained Markdown file readable in Obsidian, Notion,
    VS Code, or any Markdown viewer.
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        paper_id: int,
        paper_meta: dict[str, Any],
        analysis_report: Any,
        paper_dir: str,
    ) -> str:
        """
        Generate the complete analysis Markdown report and save it.

        Args:
            paper_id: Database ID of the paper.
            paper_meta: Paper metadata dict (title, authors, journal, year, doi, etc.).
            analysis_report: AnalysisReport object from the pipeline.
            paper_dir: Path to the paper's directory for saving.

        Returns:
            File path to the generated analysis.md file.
        """
        phases = analysis_report.phases if hasattr(analysis_report, "phases") else {}
        mermaid_outputs = (
            analysis_report.mermaid_outputs
            if hasattr(analysis_report, "mermaid_outputs")
            else []
        )
        pb_paths = (
            analysis_report.paperbanana_paths
            if hasattr(analysis_report, "paperbanana_paths")
            else []
        )

        # Extract phase results
        screening = self._get_phase_result(phases, "screening")
        visual = self._get_phase_result(phases, "visual")
        recipe = self._get_phase_result(phases, "recipe")
        deep_dive = self._get_phase_result(phases, "deep_dive")

        # Build report sections
        sections: list[str] = []
        sections.append(self._build_header(paper_meta))
        sections.append(self._build_phase1_screening(screening))
        sections.append(self._build_phase2_visual(visual, paper_dir))
        sections.append(self._build_phase3_recipe(recipe, mermaid_outputs))
        sections.append(self._build_phase4_deep_dive(deep_dive))
        sections.append(self._build_paperbanana_section(pb_paths, paper_dir))
        sections.append(self._build_cost_summary(analysis_report))

        report_md = "\n\n---\n\n".join([s for s in sections if s])

        # Save analysis.md
        output_path = Path(paper_dir) / "analysis.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report_md, encoding="utf-8")
        logger.info("Report saved to %s", output_path)

        # Also generate separate recipe_card.md
        if recipe:
            recipe_path = await self.generate_recipe_card(
                paper_id=paper_id,
                paper_meta=paper_meta,
                recipe_result=recipe,
                paper_dir=paper_dir,
            )
            logger.info("Recipe card saved to %s", recipe_path)

        return str(output_path)

    async def generate_recipe_card(
        self,
        paper_id: int,
        paper_meta: dict[str, Any],
        recipe_result: dict[str, Any],
        paper_dir: str,
    ) -> str:
        """
        Generate a standalone recipe_card.md file.

        Args:
            paper_id: Database ID.
            paper_meta: Paper metadata.
            recipe_result: Phase 3 recipe result dict.
            paper_dir: Directory to save.

        Returns:
            File path to recipe_card.md.
        """
        title = paper_meta.get("title", "Untitled Paper")
        recipe_card = recipe_result.get("recipe", recipe_result)

        lines: list[str] = []
        lines.append(f"# Recipe Card: {title}")
        lines.append("")
        lines.append(f"> Paper ID: {paper_id}")
        lines.append(f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("")

        # Objective
        objective = recipe_card.get("objective", "")
        if objective:
            lines.append(f"## Objective")
            lines.append(f"{objective}")
            lines.append("")

        # Materials
        materials = recipe_card.get("materials", [])
        if materials:
            lines.append("## Materials")
            for mat in materials:
                lines.append(f"- {mat}")
            lines.append("")

        # Equipment
        equipment = recipe_card.get("equipment", [])
        if equipment:
            lines.append("## Equipment")
            for eq in equipment:
                lines.append(f"- {eq}")
            lines.append("")

        # Parameter Table
        parameters = recipe_card.get("parameters", [])
        if parameters:
            lines.append("## Parameters")
            lines.append("")
            lines.append("| Parameter | Value | Unit | Source | Status |")
            lines.append("|-----------|-------|------|--------|--------|")
            for param in parameters:
                if isinstance(param, dict):
                    name = param.get("name", "")
                    value = param.get("value", "")
                    unit = param.get("unit", "")
                    source = param.get("source", param.get("notes", ""))
                    status = param.get("status", "EXPLICIT")
                    status_icon = self._status_icon(status)
                    lines.append(f"| {name} | {value} | {unit} | {source} | {status_icon} |")
                else:
                    lines.append(f"| {param} | - | - | - | - |")
            lines.append("")

        # Steps
        steps = recipe_card.get("steps", [])
        if steps:
            lines.append("## Procedure")
            for i, step in enumerate(steps, 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        # Critical Notes
        critical_notes = recipe_card.get("critical_notes", [])
        if critical_notes:
            lines.append("## Critical Notes")
            for note in critical_notes:
                lines.append(f"- {note}")
            lines.append("")

        # Missing Info Warnings
        missing = recipe_result.get("missing_info", recipe_card.get("missing_info", []))
        if missing:
            lines.append("## Missing Information Warnings")
            for item in missing:
                lines.append(f"- {item}")
            lines.append("")

        # Expected Results
        expected = recipe_card.get("expected_results", "")
        if expected:
            lines.append("## Expected Results")
            lines.append(expected)
            lines.append("")

        # Safety
        safety = recipe_card.get("safety_notes", "")
        if safety:
            lines.append("## Safety Notes")
            lines.append(safety)
            lines.append("")

        # Confidence scores
        confidence = recipe_result.get("confidence", None)
        reproducibility = recipe_result.get("reproducibility_score", None)
        if confidence is not None or reproducibility is not None:
            lines.append("## Confidence Metrics")
            if confidence is not None:
                lines.append(f"- Extraction Confidence: {confidence:.0%}")
            if reproducibility is not None:
                lines.append(f"- Reproducibility Score: {reproducibility:.0%}")
            lines.append("")

        recipe_md = "\n".join(lines)

        output_path = Path(paper_dir) / "recipe_card.md"
        output_path.write_text(recipe_md, encoding="utf-8")

        return str(output_path)

    # ------------------------------------------------------------------
    # Section Builders
    # ------------------------------------------------------------------

    def _build_header(self, meta: dict[str, Any]) -> str:
        """Build the report header matching PRD F6 format."""
        title = meta.get("title", "Untitled Paper")
        authors = meta.get("authors", "")
        journal = meta.get("journal", "")
        year = meta.get("year", "")
        doi = meta.get("doi", "")
        agent = meta.get("agent_used", "photon")
        domain = meta.get("domain", "optics")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        lines = [
            f"# {title}",
            "",
            f"> Authors: {authors}",
            f"> Journal: {journal} | Year: {year} | DOI: {doi}",
            f"> Analysis Agent: Agent {agent.capitalize()} ({domain.capitalize()})",
            f"> Analysis Date: {now}",
        ]
        return "\n".join(lines)

    def _build_phase1_screening(self, result: Optional[dict]) -> str:
        """Build Phase 1: Screening section."""
        lines = ["## Phase 1: Screening"]
        lines.append("")

        if result is None:
            lines.append("*Phase 1 was not completed.*")
            return "\n".join(lines)

        # Relevance
        relevance = result.get("relevance_score", result.get("relevance", "N/A"))
        if isinstance(relevance, (int, float)):
            if relevance >= 0.7:
                stars = "High"
            elif relevance >= 0.4:
                stars = "Medium"
            else:
                stars = "Low"
            relevance_display = f"{stars} ({relevance:.0%})"
        else:
            relevance_display = str(relevance)
            stars = str(relevance)

        lines.append(f"- **Relevance**: {relevance_display}")

        # Keywords
        keywords = result.get("key_topics", result.get("keywords", []))
        if keywords:
            if isinstance(keywords, list):
                lines.append(f"- **Keywords**: {', '.join(keywords)}")
            else:
                lines.append(f"- **Keywords**: {keywords}")

        # Summary
        summary = result.get("summary", result.get("one_line_summary", ""))
        if summary:
            lines.append(f"- **Summary**: {summary}")

        # Methodology type
        methodology = result.get("methodology_type", "")
        if methodology:
            lines.append(f"- **Methodology**: {methodology}")

        # Complexity
        complexity = result.get("estimated_complexity", "")
        if complexity:
            lines.append(f"- **Estimated Complexity**: {complexity}")

        # Flags
        is_experimental = result.get("is_experimental", None)
        if is_experimental is not None:
            lines.append(f"- **Experimental Paper**: {'Yes' if is_experimental else 'No'}")

        return "\n".join(lines)

    def _build_phase2_visual(self, result: Optional[dict], paper_dir: str) -> str:
        """Build Phase 2: Visual Verification section with figure gallery."""
        lines = ["## Phase 2: Visual Verification"]
        lines.append("")

        if result is None:
            lines.append("*Phase 2 was not completed.*")
            return "\n".join(lines)

        # Figure Gallery
        figures = result.get("figures", result.get("figure_analyses", []))
        if figures and isinstance(figures, list):
            lines.append("### Figure Gallery")
            lines.append("")
            for fig in figures:
                fig_id = fig.get("figure_id", fig.get("figure_num", ""))
                caption = fig.get("caption", "")
                interpretation = fig.get("ai_analysis", fig.get("interpretation", ""))
                quality = fig.get("quality", fig.get("data_quality", ""))
                file_path = fig.get("file_path", "")
                warnings = fig.get("warnings", [])

                # Image reference (relative path)
                if file_path:
                    rel_path = self._relative_path(file_path, paper_dir)
                    lines.append(f"![{fig_id}]({rel_path})")
                lines.append(f"**{fig_id}**: {caption}")
                if interpretation:
                    lines.append(f"> AI Analysis: {interpretation}")
                if warnings:
                    for w in warnings:
                        lines.append(f"> :warning: {w}")
                lines.append("")

        # Data Quality Table
        if figures and isinstance(figures, list):
            lines.append("### Data Quality Assessment")
            lines.append("")
            lines.append("| Figure | Quality | Notes |")
            lines.append("|--------|---------|-------|")
            for fig in figures:
                fig_id = fig.get("figure_id", fig.get("figure_num", "?"))
                quality = fig.get("quality", fig.get("data_quality", "N/A"))
                quality_icon = self._quality_icon(quality)
                notes = fig.get("quality_notes", fig.get("notes", ""))
                lines.append(f"| {fig_id} | {quality_icon} | {notes} |")
            lines.append("")

        # Summary stats
        summary = result.get("quality_summary", "")
        if summary:
            lines.append(f"**Quality Summary**: {summary}")
            lines.append("")

        figure_count = result.get("figure_count", len(figures) if figures else 0)
        tables_found = result.get("tables_found", 0)
        equations_found = result.get("equations_found", 0)
        if any([figure_count, tables_found, equations_found]):
            lines.append(
                f"Figures: {figure_count} | Tables: {tables_found} | "
                f"Equations: {equations_found}"
            )

        return "\n".join(lines)

    def _build_phase3_recipe(
        self,
        result: Optional[dict],
        mermaid_outputs: list,
    ) -> str:
        """Build Phase 3: Recipe Card section with parameter table and Mermaid."""
        lines = ["## Phase 3: Recipe Card"]
        lines.append("")

        if result is None:
            lines.append("*Phase 3 was not completed.*")
            return "\n".join(lines)

        recipe_card = result.get("recipe", result)

        # Objective
        objective = recipe_card.get("objective", "")
        if objective:
            lines.append(f"**Objective**: {objective}")
            lines.append("")

        # Parameter Table
        parameters = recipe_card.get("parameters", [])
        if parameters:
            lines.append("### Experiment Parameters")
            lines.append("")
            lines.append("| Parameter | Value | Unit | Source | Status |")
            lines.append("|-----------|-------|------|--------|--------|")
            for param in parameters:
                if isinstance(param, dict):
                    name = param.get("name", "")
                    value = param.get("value", "")
                    unit = param.get("unit", "")
                    source = param.get("source", param.get("notes", ""))
                    status = param.get("status", "EXPLICIT")
                    status_icon = self._status_icon(status)
                    lines.append(f"| {name} | {value} | {unit} | {source} | {status_icon} |")
            lines.append("")

        # Missing Parameter Warnings
        missing = result.get("missing_info", recipe_card.get("missing_info", []))
        if missing:
            lines.append("### Missing Parameter Warnings")
            lines.append("")
            for item in missing:
                lines.append(f"- :warning: {item}")
            lines.append("")

        # Steps
        steps = recipe_card.get("steps", [])
        if steps:
            lines.append("### Procedure Steps")
            lines.append("")
            for i, step in enumerate(steps, 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        # Critical notes
        critical = recipe_card.get("critical_notes", [])
        if critical:
            lines.append("### Critical Notes")
            lines.append("")
            for note in critical:
                lines.append(f"- {note}")
            lines.append("")

        # Mermaid Diagrams
        if mermaid_outputs:
            lines.append("### Diagrams")
            lines.append("")
            for mermaid in mermaid_outputs:
                m_title = ""
                m_code = ""
                if isinstance(mermaid, dict):
                    m_title = mermaid.get("title", "Diagram")
                    m_code = mermaid.get("mermaid_code", "")
                elif hasattr(mermaid, "title"):
                    m_title = mermaid.title
                    m_code = mermaid.mermaid_code
                else:
                    continue

                if m_code:
                    lines.append(f"#### {m_title}")
                    lines.append("")
                    lines.append("```mermaid")
                    lines.append(m_code)
                    lines.append("```")
                    lines.append("")

        # Confidence metrics
        confidence = result.get("confidence", None)
        reproducibility = result.get("reproducibility_score", None)
        if confidence is not None or reproducibility is not None:
            lines.append("### Confidence Metrics")
            if confidence is not None:
                lines.append(f"- Extraction Confidence: {confidence:.0%}")
            if reproducibility is not None:
                lines.append(f"- Reproducibility Score: {reproducibility:.0%}")
            lines.append("")

        return "\n".join(lines)

    def _build_phase4_deep_dive(self, result: Optional[dict]) -> str:
        """Build Phase 4: Deep Dive section."""
        lines = ["## Phase 4: Deep Dive"]
        lines.append("")

        if result is None:
            lines.append("*Phase 4 was not completed.*")
            return "\n".join(lines)

        # Research Background (Why?)
        analysis = result.get("detailed_analysis", "")
        if analysis:
            lines.append("### Research Background")
            lines.append("")
            lines.append(analysis)
            lines.append("")

        # Prior Work Comparison
        comparison = result.get("comparison_to_prior_work", "")
        if comparison:
            lines.append("### Prior Work Comparison")
            lines.append("")
            lines.append(comparison)
            lines.append("")

        # Strengths
        strengths = result.get("strengths", [])
        if strengths:
            lines.append("### Strengths")
            lines.append("")
            for s in strengths:
                lines.append(f"- {s}")
            lines.append("")

        # Weaknesses
        weaknesses = result.get("weaknesses", [])
        if weaknesses:
            lines.append("### Weaknesses")
            lines.append("")
            for w in weaknesses:
                lines.append(f"- {w}")
            lines.append("")

        # Novelty
        novelty = result.get("novelty_assessment", "")
        if novelty:
            lines.append("### Novelty Assessment")
            lines.append("")
            lines.append(novelty)
            lines.append("")

        # Critical Analysis (Claim vs Evidence)
        # This may be part of detailed_analysis or a separate field
        critical = result.get("critical_analysis", "")
        if critical:
            lines.append("### Critical Analysis")
            lines.append("")
            lines.append(critical)
            lines.append("")

        # Limitations
        limitations = result.get("limitations", [])
        if limitations:
            lines.append("### Limitations")
            lines.append("")
            for lim in limitations:
                lines.append(f"- {lim}")
            lines.append("")

        # Suggested improvements
        improvements = result.get("suggested_improvements", [])
        if improvements:
            lines.append("### Suggested Improvements")
            lines.append("")
            for imp in improvements:
                lines.append(f"- {imp}")
            lines.append("")

        # Follow-up questions
        questions = result.get("follow_up_questions", [])
        if questions:
            lines.append("### Follow-up Questions")
            lines.append("")
            for q in questions:
                lines.append(f"- {q}")
            lines.append("")

        # Practical applications
        applications = result.get("practical_applications", [])
        if applications:
            lines.append("### Practical Applications")
            lines.append("")
            for app in applications:
                lines.append(f"- {app}")
            lines.append("")

        return "\n".join(lines)

    def _build_paperbanana_section(
        self, pb_paths: list[Optional[str]], paper_dir: str
    ) -> str:
        """Build PaperBanana illustrations section."""
        valid_paths = [p for p in pb_paths if p]
        if not valid_paths:
            return ""

        lines = ["## PaperBanana Illustrations"]
        lines.append("")

        for path in valid_paths:
            rel_path = self._relative_path(path, paper_dir)
            filename = Path(path).stem.replace("_", " ").title()
            lines.append(f"![{filename}]({rel_path})")
            lines.append("")

        return "\n".join(lines)

    def _build_cost_summary(self, analysis_report: Any) -> str:
        """Build API cost summary section."""
        total_cost = getattr(analysis_report, "total_cost_usd", 0.0)
        total_in = getattr(analysis_report, "total_tokens_in", 0)
        total_out = getattr(analysis_report, "total_tokens_out", 0)

        if total_cost == 0.0 and total_in == 0 and total_out == 0:
            return ""

        lines = ["## Analysis Cost Summary"]
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total Cost | ${total_cost:.4f} |")
        lines.append(f"| Input Tokens | {total_in:,} |")
        lines.append(f"| Output Tokens | {total_out:,} |")

        # Per-phase breakdown
        phases = getattr(analysis_report, "phases", {})
        if phases:
            lines.append("")
            lines.append("### Per-Phase Breakdown")
            lines.append("")
            lines.append("| Phase | Model | Cost | Duration |")
            lines.append("|-------|-------|------|----------|")
            for phase_name, pr in phases.items():
                model = pr.usage.model if hasattr(pr, "usage") else "N/A"
                cost = pr.usage.cost_usd if hasattr(pr, "usage") else 0.0
                duration = pr.duration_seconds if hasattr(pr, "duration_seconds") else 0.0
                status = pr.status if hasattr(pr, "status") else "?"
                if status == "error":
                    lines.append(f"| {phase_name} | {model} | ERROR | - |")
                else:
                    lines.append(
                        f"| {phase_name} | {model} | ${cost:.4f} | {duration:.1f}s |"
                    )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_phase_result(self, phases: dict, phase_name: str) -> Optional[dict]:
        """Get the result dict for a phase, handling PhaseResult or raw dict."""
        phase = phases.get(phase_name)
        if phase is None:
            return None
        if hasattr(phase, "result"):
            return phase.result
        if isinstance(phase, dict):
            return phase
        return None

    def _status_icon(self, status: str) -> str:
        """Convert status string to icon."""
        s = status.upper().strip("[]")
        if s in ("EXPLICIT", "GREEN", "CONFIRMED"):
            return ":green_circle: EXPLICIT"
        elif s in ("INFERRED", "YELLOW", "ESTIMATED"):
            return ":yellow_circle: INFERRED"
        elif s in ("MISSING", "RED", "ABSENT"):
            return ":red_circle: MISSING"
        return status

    def _quality_icon(self, quality: str) -> str:
        """Convert quality string to icon."""
        q = quality.lower().strip()
        if q in ("high", "good", "excellent"):
            return ":green_circle: Good"
        elif q in ("medium", "caution", "moderate"):
            return ":yellow_circle: Caution"
        elif q in ("low", "poor", "bad", "unreadable"):
            return ":red_circle: Poor"
        return quality

    def _relative_path(self, abs_path: str, paper_dir: str) -> str:
        """Compute a relative path from paper_dir to the given file."""
        try:
            return str(Path(abs_path).relative_to(Path(paper_dir)))
        except (ValueError, TypeError):
            # If not relative, return as-is
            return abs_path
