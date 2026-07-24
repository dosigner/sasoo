"""
Sasoo - Naming Service
Uses Gemini 3.1 Flash Lite (minimal thinking) via the Interactions API to
generate human-readable names for paper folders, figures, and PaperBanana
illustrations.

Fallback: UUID-based naming if Gemini fails.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Optional

from services.llm.interactions_client import call_interaction
from services.models import MODEL_FLASH_LITE

logger = logging.getLogger(__name__)

# call_interaction() defaults to a Korean-forcing system instruction, but
# naming prompts require short ASCII/CamelCase identifiers (filesystem-safe
# names) — override it so existing response language/format is preserved.
_NAMING_SYSTEM_INSTRUCTION = (
    "You generate short, filesystem-safe identifiers for research paper "
    "assets (folder names, figure filenames, illustration filenames). "
    "Follow the formatting rules in the user prompt exactly and respond "
    "only in the exact format requested. Do not add explanations, and do "
    "not translate the identifiers into Korean or any other language."
)

# Moves the JSON array skeleton that generate_figure_names' prompt already
# requests into a response_schema, replacing response_mime_type="application/json".
_FIGURE_NAMES_RESPONSE_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
}


async def generate_folder_name(
    title: str,
    year: Optional[int] = None,
    journal: Optional[str] = None,
    domain: Optional[str] = None,
    abstract: Optional[str] = None,
) -> str:
    """
    Generate a human-readable folder name for a paper.

    Format: {year}_{JournalAbbrev}_{ShortTitle}_{Domain}
    Example: "2024_NatPhoton_MetasurfLens_Optics"

    Falls back to UUID-based name on failure.
    """
    try:
        prompt = (
            "Generate a short, filesystem-safe folder name for this research paper.\n\n"
            f"Title: {title}\n"
            f"Year: {year or 'unknown'}\n"
            f"Journal: {journal or 'unknown'}\n"
            f"Domain: {domain or 'unknown'}\n"
            f"Abstract (first 300 chars): {(abstract or '')[:300]}\n\n"
            "Rules:\n"
            "1. Format: {Year}_{JournalAbbrev}_{ShortTitle}_{Domain}\n"
            "2. Use only ASCII alphanumeric and underscores\n"
            "3. Abbreviate journal name (e.g., Nature Photonics -> NatPhoton)\n"
            "4. ShortTitle should be 1-3 words in CamelCase capturing the main topic\n"
            "5. Keep total length under 60 characters\n"
            "6. If year is unknown, omit it\n"
            "7. If journal is unknown, omit it\n\n"
            "Return ONLY the folder name string, nothing else."
        )

        result = await call_interaction(
            prompt,
            lane="pipeline",
            model=MODEL_FLASH_LITE,
            system_instruction=_NAMING_SYSTEM_INSTRUCTION,
            thinking_level="minimal",
            store=False,
        )
        raw_name = result["text"].strip()

        # Sanitize: remove quotes, backticks, newlines
        raw_name = raw_name.strip('`"\'')
        raw_name = raw_name.split('\n')[0].strip()

        # Validate: only allow safe filesystem characters
        sanitized = re.sub(r'[^\w]', '_', raw_name)
        sanitized = re.sub(r'_+', '_', sanitized).strip('_')

        if sanitized and len(sanitized) >= 5:
            logger.info("Generated folder name: %s", sanitized)
            return sanitized

    except Exception as exc:
        logger.warning("Folder name generation failed, using fallback: %s", exc)

    return _fallback_folder_name(title, year)


async def generate_figure_names(
    captions_and_pages: list[dict],
) -> list[str]:
    """
    Generate human-readable figure filenames from captions.

    Input: [{"figure_num": "p2_img1", "caption": "SEM cross-section...", "page": 2}]
    Output: ["fig1_SEM_cross_section", "fig2_transmission_spectrum"]

    Falls back to original figure_num on failure.
    """
    if not captions_and_pages:
        return []

    try:
        figures_desc = "\n".join(
            f"- Figure '{f.get('figure_num', '?')}': {f.get('caption', 'no caption')}"
            for f in captions_and_pages
        )

        prompt = (
            "Generate short, descriptive filenames for these research paper figures.\n\n"
            f"Figures:\n{figures_desc}\n\n"
            "Rules:\n"
            "1. Format: fig{N}_{short_description}\n"
            "2. Use only ASCII lowercase, digits, and underscores\n"
            "3. Description should be 2-4 words capturing what the figure shows\n"
            "4. Keep each name under 40 characters\n"
            "5. Number figures sequentially (fig1, fig2, ...)\n\n"
            "Return a JSON array of strings, one per figure, in the same order.\n"
            "Example: [\"fig1_sem_cross_section\", \"fig2_transmission_spectrum\"]"
        )

        result = await call_interaction(
            prompt,
            lane="pipeline",
            model=MODEL_FLASH_LITE,
            system_instruction=_NAMING_SYSTEM_INSTRUCTION,
            thinking_level="minimal",
            store=False,
            response_schema=_FIGURE_NAMES_RESPONSE_SCHEMA,
        )
        text = result["text"].strip()

        # Parse JSON array
        names = json.loads(text)
        if isinstance(names, list) and len(names) == len(captions_and_pages):
            # Sanitize each name
            sanitized_names: list[str] = []
            for name in names:
                safe = re.sub(r'[^\w]', '_', str(name).lower())
                safe = re.sub(r'_+', '_', safe).strip('_')
                sanitized_names.append(safe if safe else f"fig{len(sanitized_names)+1}")
            logger.info("Generated %d figure names", len(sanitized_names))
            return sanitized_names

    except Exception as exc:
        logger.warning("Figure name generation failed, using fallback: %s", exc)

    # Fallback: use original figure_num values
    return [f.get("figure_num", f"fig{i+1}") for i, f in enumerate(captions_and_pages)]


async def generate_paperbanana_name(
    title: str,
    description: Optional[str] = None,
) -> str:
    """
    Generate a human-readable filename for a PaperBanana illustration.

    Example: "optical_setup_illustration"

    Falls back to sanitized title on failure.
    """
    try:
        prompt = (
            "Generate a short, descriptive filename for this scientific illustration.\n\n"
            f"Title: {title}\n"
            f"Description: {description or 'N/A'}\n\n"
            "Rules:\n"
            "1. Use only ASCII lowercase, digits, and underscores\n"
            "2. 2-4 words describing what the illustration shows\n"
            "3. Keep under 40 characters\n"
            "4. Do NOT include file extension\n\n"
            "Return ONLY the filename string, nothing else."
        )

        result = await call_interaction(
            prompt,
            lane="pipeline",
            model=MODEL_FLASH_LITE,
            system_instruction=_NAMING_SYSTEM_INSTRUCTION,
            thinking_level="minimal",
            store=False,
        )
        raw = result["text"].strip().strip('`"\'').split('\n')[0]
        sanitized = re.sub(r'[^\w]', '_', raw.lower())
        sanitized = re.sub(r'_+', '_', sanitized).strip('_')

        if sanitized and len(sanitized) >= 3:
            logger.info("Generated PaperBanana name: %s", sanitized)
            return sanitized

    except Exception as exc:
        logger.warning("PaperBanana name generation failed: %s", exc)

    # Fallback
    safe = re.sub(r'[^\w\s-]', '', title).strip()
    safe = re.sub(r'[-\s]+', '_', safe).lower()
    return safe[:40] if safe else "illustration"


def _fallback_folder_name(title: str, year: Optional[int] = None) -> str:
    """Generate a fallback folder name with UUID suffix for uniqueness."""
    suffix = uuid.uuid4().hex[:8]
    safe_title = re.sub(r'[^\w\s-]', '', title).strip()
    safe_title = re.sub(r'[-\s]+', '_', safe_title)[:40]
    if year:
        return f"{year}_{safe_title}_{suffix}"
    return f"{safe_title}_{suffix}"
