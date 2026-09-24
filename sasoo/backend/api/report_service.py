"""Format report Markdown and render the report's visual summary card."""

import json
import logging
from pathlib import Path

from services.summary_contract import validate_summary_extensions

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _format_phase_data(phase: str, data: dict) -> str:
    """Format phase result data as readable markdown."""
    parts: list[str] = []
    if phase in {"visual", "recipe", "deep_dive"}:
        coverage = data.get("_input_coverage")
        match coverage:
            case {"mode": "pdf", "status": "provided_pdf", "missing": list(missing), "pdf_sha256": str(digest)} if len(digest) == 64 and all(char in "0123456789abcdefABCDEF" for char in digest) and all(isinstance(item, str) and item.strip() for item in missing):
                parts.append("**입력 범위:** 원본 PDF 제공. 모든 내용을 정확히 판독했다는 뜻은 아닙니다.")
                parts.extend(f"- {item}" for item in missing)
            case {"mode": str(mode), "status": "partial", "missing": list(missing), "pdf_sha256": digest} if mode in {"text", "pdf"} and all(isinstance(item, str) and item.strip() for item in missing) and ((mode == "text" and digest is None) or (mode == "pdf" and isinstance(digest, str) and len(digest) == 64 and all(char in "0123456789abcdefABCDEF" for char in digest))):
                parts.append("**부분 분석:** 제공된 입력 범위에 한정한 분석입니다.")
                parts.extend(f"- {item}" for item in missing)
                if not missing:
                    parts.append("누락 범위를 확인하지 못했습니다.")
            case _:
                parts.append("**입력 범위 미확인:** 이 결과에는 확인 가능한 원문 제공 기록이 없습니다.")

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
        # 신 스키마(구조화 필드)를 라벨과 함께 렌더한다. 빈 문자열은 건너뛴다.
        for key, label in [
            ("problem_definition", "Problem"),
            ("as_is", "As-Is"),
            ("to_be", "To-Be"),
            ("solution", "Solution"),
            ("method_summary", "Method"),
            ("key_results", "Results"),
        ]:
            if data.get(key):
                parts.append(f"\n**{label}:** {data[key]}")
        # 구 캐시(detailed_analysis 단일 서술) 폴백.
        if data.get("detailed_analysis"):
            parts.append(f"\n{data['detailed_analysis']}\n")
        parts.append(f"**Novelty:** {data.get('novelty_assessment', 'N/A')}")
        if data.get("comparison_to_prior_work"):
            parts.append(f"\n**Comparison to Prior Work:** {data['comparison_to_prior_work']}")
        if data.get("comparison_scope") == "in_paper_only":
            parts.append("_(논문이 제시한 비교 범위 안의 평가로, 외부 문헌 검증은 하지 않았습니다)_")

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

        try:
            has_extensions = validate_summary_extensions(data)
        except ValueError:
            parts.append("\n새 요약 항목의 구조를 확인하지 못했습니다. 기존 분석 본문은 위에 보존했습니다.")
        else:
            if has_extensions:
                answers = data["section_answers"]
                checks = data["transfer_checks"]
                if answers:
                    parts.append("\n### 섹션별 핵심 답변\n")
                for answer in answers:
                    parts.append(f"\n#### {answer['section_title']}\n")
                    parts.append(f"**질문:** {answer['question']}\n")
                    parts.append(f"**짧은 답:**\n\n{answer['answer']}\n")
                    if answer["explanation"]:
                        parts.append(f"**설명:**\n\n{answer['explanation']}\n")
                    parts.append(f"**근거:** {', '.join(answer['source_refs'])}\n")
                if checks:
                    parts.append("\n### 옮겨 쓸 때 확인할 조건\n")
                    parts.append("아래 적용 전 확인 제안은 저자가 검증한 사실이나 적용 가능 판정이 아닙니다.\n")
                basis_labels = {
                    "reported": "원문에 명시",
                    "inferred": "원문에서 추론",
                    "not_reported": "제공 자료에서 확인 못함",
                }
                for check in checks:
                    parts.append(f"\n#### {check['item']}\n")
                    parts.append(f"**근거 성격:** {basis_labels[check['condition_basis']]}\n")
                    parts.append(f"**원문 조건:**\n\n{check['paper_condition']}\n")
                    parts.append(f"**적용 전 확인 제안:**\n\n{check['check_before_transfer']}\n")
                    if check["source_refs"]:
                        parts.append(f"**근거:** {', '.join(check['source_refs'])}\n")
                if not answers and not checks:
                    parts.append("\n이번 분석에서 작성된 항목이 없어요.")

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
