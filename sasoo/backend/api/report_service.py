"""
Sasoo - Report service.
Handles report generation, _format_phase_data helper, and generate_paperbanana endpoint.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

from models.database import (
    fetch_all,
    fetch_one,
    get_paperbanana_dir,
)
from models.schemas import (
    PaperBananaRequest,
    PaperBananaResponse,
    ReportResponse,
)

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _format_phase_data(phase: str, data: dict) -> str:
    """Format phase result data as readable markdown."""
    parts: list[str] = []

    if phase == "screening":
        parts.append(f"**Domain:** {data.get('domain', 'N/A')}")
        parts.append(f"**Relevance Score:** {data.get('relevance_score', 'N/A')}")
        parts.append(f"**Methodology:** {data.get('methodology_type', 'N/A')}")
        parts.append(f"**Complexity:** {data.get('estimated_complexity', 'N/A')}")
        parts.append(f"\n**Summary:** {data.get('summary', 'N/A')}")
        topics = data.get("key_topics", [])
        if topics:
            parts.append("\n**Key Topics:**")
            for t in topics:
                parts.append(f"- {t}")

    elif phase == "visual":
        parts.append(f"**Figures:** {data.get('figure_count', 0)}")
        parts.append(f"**Tables:** {data.get('tables_found', 0)}")
        parts.append(f"**Equations:** {data.get('equations_found', 0)}")
        parts.append(f"\n**Quality:** {data.get('quality_summary', 'N/A')}")
        types = data.get("diagram_types", [])
        if types:
            parts.append(f"**Diagram Types:** {', '.join(types)}")
        findings = data.get("key_findings_from_visuals", [])
        if findings:
            parts.append("\n**Key Findings from Visuals:**")
            for f in findings:
                parts.append(f"- {f}")

    elif phase == "recipe":
        parts.append(f"**Title:** {data.get('title', 'N/A')}")
        parts.append(f"**Objective:** {data.get('objective', 'N/A')}")
        parts.append(f"**Confidence:** {data.get('confidence', 'N/A')}")
        parts.append(f"**Reproducibility:** {data.get('reproducibility_score', 'N/A')}")

        materials = data.get("materials", [])
        if materials:
            parts.append("\n**Materials:**")
            for m in materials:
                parts.append(f"- {m}")

        steps = data.get("steps", [])
        if steps:
            parts.append("\n**Steps:**")
            for i, s in enumerate(steps, 1):
                parts.append(f"{i}. {s}")

        params = data.get("parameters", [])
        if params:
            parts.append("\n**Parameters:**")
            for p in params:
                if isinstance(p, dict):
                    parts.append(f"- **{p.get('name', '?')}:** {p.get('value', '?')} {p.get('unit', '')}")
                else:
                    parts.append(f"- {p}")

    elif phase == "deep_dive":
        parts.append(f"\n{data.get('detailed_analysis', '')}\n")
        parts.append(f"**Novelty:** {data.get('novelty_assessment', 'N/A')}")

        for key, label in [
            ("strengths", "Strengths"),
            ("weaknesses", "Weaknesses"),
            ("suggested_improvements", "Suggested Improvements"),
            ("practical_applications", "Practical Applications"),
            ("follow_up_questions", "Follow-up Questions"),
        ]:
            items = data.get(key, [])
            if items:
                parts.append(f"\n**{label}:**")
                for item in items:
                    parts.append(f"- {item}")

    else:
        # Generic formatting
        parts.append(json.dumps(data, indent=2, ensure_ascii=False))

    return "\n".join(parts)


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    """Simple word-wrap implementation."""
    words = text.split()
    lines: list[str] = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip()
        # Estimate width: ~8px per character as rough fallback
        try:
            bbox = font.getbbox(test_line)
            line_width = bbox[2] - bbox[0]
        except (AttributeError, Exception):
            line_width = len(test_line) * 8

        if line_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines if lines else [text]


async def _generate_paperbanana_image(
    paper: dict,
    analysis_data: dict,
    output_dir: Path,
    style: str = "default",
    language: str = "ko",
    include_recipe: bool = True,
) -> str:
    """
    Render the report's visual summary card with PIL.

    Not to be confused with services/viz/figure_gen.py, which generates the
    actual in-paper diagrams. This one only draws the report cover.
    """
    output_path = output_dir / f"summary_{paper['id']}.png"

    from PIL import Image, ImageDraw, ImageFont

    # Canvas dimensions
    width = 1200
    height = 1600
    bg_color = (255, 255, 255)
    text_color = (33, 33, 33)
    accent_color = (59, 130, 246)  # Blue accent
    light_gray = (245, 245, 245)

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # Try to load a font, fall back to default
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except (OSError, IOError):
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()

    y_offset = 40

    # Header bar
    draw.rectangle([(0, 0), (width, 80)], fill=accent_color)
    draw.text((30, 25), "SASOO - Paper Summary", fill=(255, 255, 255), font=font_large)
    y_offset = 100

    # Title
    title = paper.get("title", "Untitled")
    # Word wrap title
    title_lines = _wrap_text(title, font_large, width - 60)
    for line in title_lines:
        draw.text((30, y_offset), line, fill=text_color, font=font_large)
        y_offset += 36
    y_offset += 10

    # Metadata
    meta_items = [
        f"Authors: {paper.get('authors', 'N/A')}",
        f"Year: {paper.get('year', 'N/A')} | Journal: {paper.get('journal', 'N/A')}",
        f"Domain: {paper.get('domain', 'N/A')} | Agent: {paper.get('agent_used', 'N/A')}",
    ]
    for item in meta_items:
        draw.text((30, y_offset), item, fill=(100, 100, 100), font=font_small)
        y_offset += 24
    y_offset += 20

    # Screening summary
    screening = analysis_data.get("screening", {})
    if screening:
        draw.rectangle([(20, y_offset - 5), (width - 20, y_offset + 25)], fill=light_gray)
        draw.text((30, y_offset), "Screening Summary", fill=accent_color, font=font_medium)
        y_offset += 35
        summary = screening.get("summary", "N/A")
        summary_lines = _wrap_text(summary, font_small, width - 60)
        for line in summary_lines[:6]:
            draw.text((30, y_offset), line, fill=text_color, font=font_small)
            y_offset += 22
        y_offset += 15

    # Recipe (if available and requested)
    recipe = analysis_data.get("recipe", {})
    if include_recipe and recipe:
        draw.rectangle([(20, y_offset - 5), (width - 20, y_offset + 25)], fill=light_gray)
        draw.text((30, y_offset), "Recipe Card", fill=accent_color, font=font_medium)
        y_offset += 35

        if recipe.get("objective"):
            obj_lines = _wrap_text(f"Objective: {recipe['objective']}", font_small, width - 60)
            for line in obj_lines[:3]:
                draw.text((30, y_offset), line, fill=text_color, font=font_small)
                y_offset += 22

        steps = recipe.get("steps", [])
        if steps:
            y_offset += 5
            draw.text((30, y_offset), "Steps:", fill=text_color, font=font_medium)
            y_offset += 28
            for i, step in enumerate(steps[:8], 1):
                step_lines = _wrap_text(f"{i}. {step}", font_small, width - 80)
                for line in step_lines[:2]:
                    draw.text((50, y_offset), line, fill=text_color, font=font_small)
                    y_offset += 20
                y_offset += 4
        y_offset += 15

    # Deep dive highlights
    deep_dive = analysis_data.get("deep_dive", {})
    if deep_dive:
        draw.rectangle([(20, y_offset - 5), (width - 20, y_offset + 25)], fill=light_gray)
        draw.text((30, y_offset), "Key Insights", fill=accent_color, font=font_medium)
        y_offset += 35

        for section, label in [("strengths", "+"), ("weaknesses", "-")]:
            items = deep_dive.get(section, [])
            for item in items[:3]:
                item_lines = _wrap_text(f"  {label} {item}", font_small, width - 80)
                for line in item_lines[:2]:
                    draw.text((30, y_offset), line, fill=text_color, font=font_small)
                    y_offset += 20
                y_offset += 4

    # Footer
    draw.rectangle([(0, height - 40), (width, height)], fill=accent_color)
    draw.text(
        (30, height - 32),
        f"Generated by Sasoo AI Co-Scientist",
        fill=(255, 255, 255),
        font=font_small,
    )

    img.save(str(output_path), "PNG")
    return str(output_path)
