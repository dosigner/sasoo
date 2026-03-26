"""
Section Splitter for dividing research papers into logical sections.

This service implements intelligent section detection using multiple heuristics
and provides phase-specific section extraction for the 4-phase analysis strategy.
"""
import re
from typing import Optional
from enum import Enum


class SectionType(str, Enum):
    """Standard research paper sections."""
    ABSTRACT = "abstract"
    INTRODUCTION = "introduction"
    BACKGROUND = "background"
    RELATED_WORK = "related_work"
    METHOD = "method"
    EXPERIMENTAL = "experimental"
    MATERIALS_METHODS = "materials_methods"
    RESULTS = "results"
    DISCUSSION = "discussion"
    RESULTS_DISCUSSION = "results_discussion"  # Combined section
    CONCLUSION = "conclusion"
    REFERENCES = "references"
    ACKNOWLEDGMENTS = "acknowledgments"
    APPENDIX = "appendix"
    SUPPLEMENTARY = "supplementary"


class SectionSplitter:
    """
    Intelligent section splitter for research papers.

    Uses multiple heuristics to detect section boundaries:
    - Numbered headings (1., 2., 1.1, etc.)
    - Roman numerals (I., II., III.)
    - ALL CAPS headings
    - Pattern matching for standard section names

    Handles common variations and edge cases in academic writing.
    """

    # Section name patterns with variations
    SECTION_PATTERNS = {
        SectionType.ABSTRACT: [
            r'\bABSTRACT\b',
            r'\bSummary\b',
        ],
        SectionType.INTRODUCTION: [
            r'\bINTRODUCTION\b',
            r'\bBackground\s+and\s+Introduction\b',
        ],
        SectionType.BACKGROUND: [
            r'\bBACKGROUND\b',
            r'\bRelated\s+Work\b',
            r'\bLiterature\s+Review\b',
        ],
        SectionType.METHOD: [
            r'\bMETHOD(S)?\b',
            r'\bMETHODOLOGY\b',
            r'\bEXPERIMENTAL\s+SECTION\b',
            r'\bEXPERIMENTAL\s+PROCEDURE(S)?\b',
            r'\bMATERIALS?\s+AND\s+METHODS?\b',
            r'\bEXPERIMENTAL\s+METHODS?\b',
            r'\bPROCEDURE(S)?\b',
        ],
        SectionType.RESULTS: [
            r'\bRESULTS?\b',
            r'\bFINDINGS?\b',
            r'\bOBSERVATIONS?\b',
        ],
        SectionType.DISCUSSION: [
            r'\bDISCUSSION\b',
            r'\bANALYSIS\b',
        ],
        SectionType.RESULTS_DISCUSSION: [
            r'\bRESULTS?\s+AND\s+DISCUSSION\b',
            r'\bDISCUSSION\s+OF\s+RESULTS?\b',
        ],
        SectionType.CONCLUSION: [
            r'\bCONCLUSION(S)?\b',
            r'\bSUMMARY\s+AND\s+CONCLUSION(S)?\b',
            r'\bFINAL\s+REMARKS?\b',
        ],
        SectionType.REFERENCES: [
            r'\bREFERENCES?\b',
            r'\bBIBLIOGRAPHY\b',
            r'\bCITATIONS?\b',
        ],
        SectionType.ACKNOWLEDGMENTS: [
            r'\bACKNOWLEDGMENTS?\b',
            r'\bACKNOWLEDGEMENTS?\b',
        ],
    }

    # Heading patterns for numbered sections
    HEADING_PATTERNS = [
        # Arabic numerals: "1.", "2.", "1.1", "2.3.4"
        r'^(\d+(?:\.\d+)*)\.\s+(.+)$',
        # Roman numerals: "I.", "II.", "III."
        r'^([IVX]+)\.\s+(.+)$',
        # Letters: "A.", "B."
        r'^([A-Z])\.\s+(.+)$',
        # Just number in parentheses: "(1)", "(2)"
        r'^\((\d+)\)\s+(.+)$',
    ]

    _PAGE_MARKER_PATTERN = re.compile(r'\n?\s*---\s*Page\s+\d+\s*---\s*\n?', re.IGNORECASE)
    _REFERENCE_START_PATTERN = re.compile(r'^\s*(?:\[(\d+)\]|(\d+)\.)\s+(.*)$')
    _REFERENCE_TERMINATOR_PATTERN = re.compile(
        r'^\s*(supplementary(?:\s+materials?)?|appendix|acknowledg(?:e)?ments?)\b',
        re.IGNORECASE,
    )
    _REFERENCE_SIGNAL_PATTERN = re.compile(
        r'(?:\b(?:19|20)\d{2}\b|doi\s*:|https?://|et\s+al\.|'
        r'\b(?:Opt(?:ics)?\.?\s*(?:Express|Letters|Eng)|Nature|Science|Photonics|'
        r'J\.\s*[A-Z]|Proc\.\s*SPIE|Astron\.\s*Astrophys\.|Biomed\.\s*Opt\.\s*Express)\b)',
        re.IGNORECASE,
    )

    def __init__(self):
        """Initialize section splitter."""
        pass

    def split(self, full_text: str) -> dict[str, str]:
        """
        Split paper text into logical sections.

        Args:
            full_text: Complete paper text

        Returns:
            Dictionary mapping section names to their text content.
            If sections cannot be detected, returns {"full_text": full_text}
        """
        # Try pattern-based section detection first
        sections = self._detect_sections_by_patterns(full_text)

        if sections and len(sections) > 1:
            return sections

        # Fallback: try heading-based detection
        sections = self._detect_sections_by_headings(full_text)

        if sections and len(sections) > 1:
            return sections

        # Final fallback: return full text
        return {"full_text": full_text}

    def _detect_sections_by_patterns(self, text: str) -> dict[str, str]:
        """
        Detect sections using pattern matching for section names.

        Args:
            text: Full paper text

        Returns:
            Dictionary of section_name -> section_text
        """
        sections = {}
        section_positions = []

        # Find all potential section headers
        for section_type, patterns in self.SECTION_PATTERNS.items():
            for pattern in patterns:
                # Look for pattern at start of line
                regex = re.compile(rf'^.*{pattern}.*$', re.MULTILINE | re.IGNORECASE)

                for match in regex.finditer(text):
                    line = match.group(0).strip()
                    # Skip if it's part of a longer sentence (not a header)
                    if len(line) > 100:
                        continue

                    section_positions.append({
                        'type': section_type.value,
                        'start': match.start(),
                        'header': line
                    })

        # Sort by position
        section_positions.sort(key=lambda x: x['start'])

        # Extract text between section headers
        for i, section in enumerate(section_positions):
            start = section['start']

            # Find end position (start of next section or end of text)
            if i + 1 < len(section_positions):
                end = section_positions[i + 1]['start']
            else:
                end = len(text)

            section_text = text[start:end].strip()

            # Remove the header line from content
            lines = section_text.split('\n', 1)
            if len(lines) > 1:
                section_text = lines[1].strip()

            # Store section (merge if duplicate)
            section_type = section['type']
            if section_type in sections:
                sections[section_type] += "\n\n" + section_text
            else:
                sections[section_type] = section_text

        return sections

    def _detect_sections_by_headings(self, text: str) -> dict[str, str]:
        """
        Detect sections using numbered/lettered headings.

        Args:
            text: Full paper text

        Returns:
            Dictionary of section_name -> section_text
        """
        sections = {}
        lines = text.split('\n')
        current_section = None
        current_content = []

        for i, line in enumerate(lines):
            line_stripped = line.strip()

            # Check if line matches any heading pattern
            is_heading = False
            heading_text = None

            for pattern in self.HEADING_PATTERNS:
                match = re.match(pattern, line_stripped)
                if match:
                    is_heading = True
                    # Extract heading text (last group)
                    heading_text = match.group(len(match.groups()))
                    break

            # Also check for ALL CAPS headings (common in papers)
            if (not is_heading and
                line_stripped and
                len(line_stripped) > 3 and
                len(line_stripped) < 60 and
                line_stripped.isupper()):
                is_heading = True
                heading_text = line_stripped

            if is_heading and heading_text:
                # Save previous section
                if current_section:
                    sections[current_section] = '\n'.join(current_content).strip()

                # Start new section
                current_section = self._normalize_section_name(heading_text)
                current_content = []
            else:
                # Add line to current section
                if current_section:
                    current_content.append(line)

        # Save last section
        if current_section and current_content:
            sections[current_section] = '\n'.join(current_content).strip()

        return sections

    def _normalize_section_name(self, heading: str) -> str:
        """
        Normalize heading text to standard section name.

        Args:
            heading: Raw heading text

        Returns:
            Normalized section name
        """
        heading_upper = heading.upper().strip()

        # Try to match to known section types
        for section_type, patterns in self.SECTION_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, heading_upper):
                    return section_type.value

        # If no match, return cleaned heading
        # Remove numbering
        cleaned = re.sub(r'^[\dIVX]+\.?\s*', '', heading)
        cleaned = re.sub(r'^\([^)]+\)\s*', '', cleaned)
        # Convert to snake_case
        cleaned = cleaned.lower().strip()
        cleaned = re.sub(r'[^\w\s-]', '', cleaned)
        cleaned = re.sub(r'[-\s]+', '_', cleaned)

        return cleaned

    def get_screening_input(self, sections: dict[str, str]) -> str:
        """
        Get sections for Phase 1 (Screening).

        Phase 1 needs: Abstract + Conclusion
        This provides quick overview for relevance assessment.

        Args:
            sections: Dictionary of section_name -> text

        Returns:
            Combined text for screening phase
        """
        parts = []

        # Abstract
        abstract = self._get_section(
            sections,
            [SectionType.ABSTRACT.value]
        )
        if abstract:
            parts.append("=== ABSTRACT ===\n" + abstract)

        # Conclusion
        conclusion = self._get_section(
            sections,
            [SectionType.CONCLUSION.value]
        )
        if conclusion:
            parts.append("=== CONCLUSION ===\n" + conclusion)

        # Fallback: if no abstract/conclusion, use first and last 500 words
        if not parts:
            full_text = sections.get("full_text", "")
            words = full_text.split()
            if len(words) > 1000:
                first_part = " ".join(words[:500])
                last_part = " ".join(words[-500:])
                return f"=== BEGINNING ===\n{first_part}\n\n=== END ===\n{last_part}"
            return full_text

        return "\n\n".join(parts)

    def get_visual_input(self, sections: dict[str, str]) -> list[str]:
        """
        Get sections for Phase 2 (Visual Analysis).

        Phase 2 analyzes figures and tables from the entire paper.
        This returns section names that typically contain figure references.

        Args:
            sections: Dictionary of section_name -> text

        Returns:
            List of section names to analyze for figures
        """
        # Visual elements appear throughout, but especially in:
        # - Results
        # - Methods (experimental setups, procedures)
        # - Discussion (analysis charts)

        relevant_sections = [
            SectionType.RESULTS.value,
            SectionType.RESULTS_DISCUSSION.value,
            SectionType.METHOD.value,
            SectionType.EXPERIMENTAL.value,
            SectionType.MATERIALS_METHODS.value,
            SectionType.DISCUSSION.value,
        ]

        # Return sections that exist
        available = []
        for section_name in relevant_sections:
            if section_name in sections and sections[section_name].strip():
                available.append(section_name)

        # If no specific sections, return all (will analyze full text)
        if not available:
            return list(sections.keys())

        return available

    def get_recipe_input(self, sections: dict[str, str]) -> str:
        """
        Get sections for Phase 3 (Recipe Extraction).

        Phase 3 needs: Method/Experimental section
        This provides detailed procedures and experimental conditions.

        Args:
            sections: Dictionary of section_name -> text

        Returns:
            Combined text of methodology sections
        """
        # Method-related sections in priority order
        method_sections = [
            SectionType.METHOD.value,
            SectionType.EXPERIMENTAL.value,
            SectionType.MATERIALS_METHODS.value,
            SectionType.BACKGROUND.value,  # Sometimes contains methodology
        ]

        text = self._get_section(sections, method_sections)

        # Fallback: search for method keywords in all sections
        if not text:
            for section_name, section_text in sections.items():
                if any(keyword in section_name.lower()
                       for keyword in ['method', 'experimental', 'procedure', 'material']):
                    text = section_text
                    break

        # Final fallback
        if not text:
            text = sections.get("full_text", "")

        return text

    def get_deepdive_input(self, sections: dict[str, str]) -> str:
        """
        Get sections for Phase 4 (Deep Dive).

        Phase 4 needs: Introduction + Results & Discussion
        This provides context, findings, and analysis.

        Args:
            sections: Dictionary of section_name -> text

        Returns:
            Combined text for deep analysis
        """
        parts = []

        # Introduction
        intro = self._get_section(
            sections,
            [SectionType.INTRODUCTION.value, SectionType.BACKGROUND.value]
        )
        if intro:
            parts.append("=== INTRODUCTION ===\n" + intro)

        # Results
        results = self._get_section(
            sections,
            [
                SectionType.RESULTS_DISCUSSION.value,
                SectionType.RESULTS.value,
                SectionType.DISCUSSION.value,
            ]
        )
        if results:
            parts.append("=== RESULTS & DISCUSSION ===\n" + results)

        # If no specific sections found, return full text
        if not parts:
            return sections.get("full_text", "")

        return "\n\n".join(parts)

    def _get_section(
        self,
        sections: dict[str, str],
        section_names: list[str]
    ) -> str:
        """
        Get first available section from a list of candidates.

        Args:
            sections: Dictionary of section_name -> text
            section_names: List of section names in priority order

        Returns:
            Text of first found section, or empty string
        """
        for name in section_names:
            if name in sections and sections[name].strip():
                return sections[name]
        return ""

    def get_references_text(self, sections: dict[str, str]) -> str:
        """
        Get References section text for citation parsing.

        Args:
            sections: Dictionary of section_name -> text

        Returns:
            References section text, or empty string if not found
        """
        candidates = self._extract_reference_entries(self._compose_reference_source_text(sections))
        if len(candidates) >= 3:
            return "\n".join(f"{num}. {entry}" for num, entry in candidates)

        return self._get_section(sections, [SectionType.REFERENCES.value])

    def get_body_text_without_references(self, sections: dict[str, str]) -> str:
        """
        Get all body text excluding the References section.

        Args:
            sections: Dictionary of section_name -> text

        Returns:
            Combined body text without references
        """
        parts = []
        for section_name, text in sections.items():
            if section_name != SectionType.REFERENCES.value and section_name != "full_text":
                parts.append(text)

        if not parts:
            # Fallback: use full_text and try to cut before references
            full = sections.get("full_text", "")
            if full:
                lower = full.lower()
                for marker in ["references", "bibliography", "citations"]:
                    idx = lower.rfind(marker)
                    if idx > len(full) * 0.5:  # Only if in latter half
                        return full[:idx]
            return self._trim_reference_tail(full)

        return self._trim_reference_tail("\n\n".join(parts))

    def _compose_reference_source_text(self, sections: dict[str, str]) -> str:
        parts: list[str] = []
        for section_name, text in sections.items():
            if section_name == "full_text" or not text.strip():
                continue
            parts.append(text)

        if parts:
            return "\n\n".join(parts)
        return sections.get("full_text", "")

    def _extract_reference_entries(self, text: str) -> list[tuple[int, str]]:
        cleaned = self._PAGE_MARKER_PATTERN.sub("\n", text or "")
        if not cleaned.strip():
            return []

        entries: list[tuple[int, str]] = []
        seen: set[int] = set()
        current_num: Optional[int] = None
        current_lines: list[str] = []

        def flush() -> None:
            nonlocal current_num, current_lines
            if current_num is None:
                current_lines = []
                return

            merged = re.sub(r"\s+", " ", " ".join(current_lines)).strip()
            if merged and self._looks_like_reference_entry(merged) and current_num not in seen:
                entries.append((current_num, merged))
                seen.add(current_num)

            current_num = None
            current_lines = []

        for raw_line in cleaned.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if self._REFERENCE_TERMINATOR_PATTERN.match(line):
                if len(entries) >= 3:
                    flush()
                    break
                flush()
                continue

            match = self._REFERENCE_START_PATTERN.match(line)
            if match:
                flush()
                current_num = int(match.group(1) or match.group(2))
                current_lines = [match.group(3).strip()]
                continue

            if current_num is not None:
                current_lines.append(line)

        flush()
        entries.sort(key=lambda item: item[0])
        return entries

    def _looks_like_reference_entry(self, text: str) -> bool:
        normalized = re.sub(r"\s+", " ", text).strip()
        if len(normalized) < 30:
            return False

        if not self._REFERENCE_SIGNAL_PATTERN.search(normalized):
            return False

        heading_like = normalized.lower()
        if heading_like.startswith(("introduction", "method", "results", "discussion", "conclusion")):
            return False

        return True

    def _trim_reference_tail(self, text: str) -> str:
        if not text:
            return text

        for match in re.finditer(r'(?m)^\s*(?:\[\d+\]|\d+\.)\s+', text):
            if match.start() < len(text) * 0.15:
                continue
            extracted = self._extract_reference_entries(text[match.start():])
            if len(extracted) >= 3:
                return text[:match.start()].rstrip()

        return text

    def get_section_statistics(self, sections: dict[str, str]) -> dict[str, int]:
        """
        Get word count statistics for each section.

        Args:
            sections: Dictionary of section_name -> text

        Returns:
            Dictionary of section_name -> word_count
        """
        stats = {}
        for section_name, text in sections.items():
            word_count = len(text.split())
            stats[section_name] = word_count
        return stats

    def estimate_token_savings(self, sections: dict[str, str]) -> dict[str, float]:
        """
        Estimate token savings for each phase vs. full text.

        Assumes ~1.3 tokens per word average.

        Args:
            sections: Dictionary of section_name -> text

        Returns:
            Dictionary with savings percentages for each phase
        """
        full_text = " ".join(sections.values())
        full_tokens = len(full_text.split()) * 1.3

        phases = {
            "screening": self.get_screening_input(sections),
            "recipe": self.get_recipe_input(sections),
            "deepdive": self.get_deepdive_input(sections),
        }

        savings = {}
        for phase_name, phase_text in phases.items():
            phase_tokens = len(phase_text.split()) * 1.3
            savings_pct = ((full_tokens - phase_tokens) / full_tokens * 100)
            savings[phase_name] = round(savings_pct, 1)

        return savings
