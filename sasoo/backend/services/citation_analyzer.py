"""
Sasoo - Citation Analyzer

Parses references from research papers and analyzes citation frequency.
Supports both numbered ([1], [2]) and author-year (Smith et al., 2024) styles.

Core functions:
  1. Parse individual references from the References section
  2. Count in-text citation frequency for each reference
  3. Extract citation context sentences
  4. Sort by citation count (most-cited first)
"""

import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class ParsedReference:
    """A single parsed reference entry."""
    ref_id: str = ""         # e.g., "[1]", "[2]", or "Smith2024"
    ref_num: int = 0         # numeric index (1-based)
    authors: str = ""
    title: str = ""
    journal: str = ""
    year: int | None = None
    raw_text: str = ""       # original text of the reference


@dataclass
class CitationContext:
    """A sentence where a reference is cited."""
    sentence: str = ""
    section: str = ""        # which section this citation appears in


@dataclass
class CitationEntry:
    """Citation analysis for a single reference."""
    ref: ParsedReference = field(default_factory=ParsedReference)
    cite_count: int = 0
    cite_contexts: list[CitationContext] = field(default_factory=list)


@dataclass
class CitationAnalysisResult:
    """Complete citation analysis output."""
    total_references: int = 0
    citation_style: str = "numbered"  # "numbered" or "author_year"
    entries: list[CitationEntry] = field(default_factory=list)
    self_citation_count: int = 0
    self_citation_ratio: float = 0.0
    citation_distribution: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        top_cited = []
        for entry in sorted(self.entries, key=lambda e: e.cite_count, reverse=True):
            top_cited.append({
                "ref_id": entry.ref.ref_id,
                "ref_num": entry.ref.ref_num,
                "authors": entry.ref.authors,
                "title": entry.ref.title,
                "journal": entry.ref.journal,
                "year": entry.ref.year,
                "cite_count": entry.cite_count,
                "cite_contexts": [
                    {"sentence": ctx.sentence, "section": ctx.section}
                    for ctx in entry.cite_contexts[:5]  # Limit contexts per ref
                ],
                "raw_text": entry.ref.raw_text[:300],
            })

        return {
            "total_references": self.total_references,
            "citation_style": self.citation_style,
            "top_cited": top_cited,
            "self_citation_count": self.self_citation_count,
            "self_citation_ratio": self.self_citation_ratio,
            "citation_distribution": self.citation_distribution,
        }


# ---------------------------------------------------------------------------
# Citation Style Detection
# ---------------------------------------------------------------------------

def detect_citation_style(body_text: str) -> str:
    """
    Detect whether the paper uses numbered [1] or author-year (Author, 2024) citations.
    """
    # Count numbered citation patterns: [1], [2,3], [1-5]
    numbered_count = len(re.findall(r'\[\d+(?:[,\s\-\u2013]+\d+)*\]', body_text))

    # Count author-year patterns: (Author et al., 2024), (Author, 2023)
    author_year_count = len(re.findall(
        r'\([A-Z][a-z]+(?:\s+(?:et\s+al\.|and\s+[A-Z][a-z]+))?,?\s*\d{4}\)',
        body_text,
    ))

    if numbered_count >= author_year_count:
        return "numbered"
    return "author_year"


# ---------------------------------------------------------------------------
# Reference Parsing
# ---------------------------------------------------------------------------

def parse_references(references_text: str) -> list[ParsedReference]:
    """
    Parse individual references from the References section text.

    Handles:
    - Numbered: [1] Author... / 1. Author...
    - Unnumbered: each line/paragraph as a reference
    """
    if not references_text or not references_text.strip():
        return []

    refs: list[ParsedReference] = []

    # Try numbered style first: [1], [2], ...
    numbered_pattern = re.compile(
        r'\[(\d+)\]\s*(.+?)(?=\[\d+\]|\Z)',
        re.DOTALL,
    )
    matches = numbered_pattern.findall(references_text)

    if len(matches) >= 3:
        for num_str, text in matches:
            ref = _parse_single_reference(text.strip(), int(num_str))
            ref.ref_id = f"[{num_str}]"
            refs.append(ref)
        return refs

    # Try "1." style numbering
    dot_pattern = re.compile(
        r'(?:^|\n)\s*(\d+)\.\s+(.+?)(?=\n\s*\d+\.|\Z)',
        re.DOTALL,
    )
    matches = dot_pattern.findall(references_text)

    if len(matches) >= 3:
        for num_str, text in matches:
            ref = _parse_single_reference(text.strip(), int(num_str))
            ref.ref_id = f"[{num_str}]"
            refs.append(ref)
        return refs

    # Fallback: split by double newlines or single newlines (each = one ref)
    lines = re.split(r'\n{2,}', references_text.strip())
    if len(lines) < 3:
        lines = references_text.strip().split('\n')

    for i, line in enumerate(lines, 1):
        line = line.strip()
        if len(line) < 10:
            continue
        ref = _parse_single_reference(line, i)
        ref.ref_id = f"[{i}]"
        refs.append(ref)

    return refs


def _parse_single_reference(text: str, num: int) -> ParsedReference:
    """
    Extract metadata from a single reference string.
    Best-effort extraction of authors, title, journal, year.
    """
    ref = ParsedReference(ref_num=num, raw_text=text)

    # Clean up
    text = re.sub(r'\s+', ' ', text).strip()

    # Extract year (4-digit number, typically 19xx or 20xx)
    year_match = re.search(r'\b((?:19|20)\d{2})\b', text)
    if year_match:
        ref.year = int(year_match.group(1))

    # Extract authors: typically the beginning before the first period or quote
    # Pattern: "Author A, Author B, ... Title. Journal..."
    # Try to split at first sentence boundary that looks like a title start
    parts = text.split('. ', 1)
    if len(parts) >= 2:
        potential_authors = parts[0].strip()
        # Authors usually contain commas and are shorter
        if len(potential_authors) < 200:
            ref.authors = potential_authors
            remainder = parts[1]
        else:
            remainder = text
    else:
        remainder = text

    # Try to extract title (usually in quotes or the next sentence)
    # Quoted title
    quoted = re.search(r'["\u201c](.+?)["\u201d]', remainder)
    if quoted:
        ref.title = quoted.group(1)
    else:
        # First sentence after authors
        title_parts = remainder.split('. ', 1)
        if title_parts:
            ref.title = title_parts[0].strip()

    # Try to extract journal (usually italic or after title, contains common journal words)
    journal_match = re.search(
        r'(?:Nature|Science|Cell|Phys\.\s*Rev|Adv\.\s*Mater|ACS\s+\w+|IEEE|Opt\.\s*Express|'
        r'Nano\s*Lett|J\.\s*\w+|Appl\.\s*\w+|Proc\.\s*\w+|Ann\.\s*\w+|'
        r'Light:\s*\w+|Optica|Photonics|Laser|Chem\.\s*\w+|Angew\.\s*\w+|'
        r'PNAS|PLoS|BMC\s+\w+|Nat\.\s*\w+)[^,;.]*',
        remainder,
        re.IGNORECASE,
    )
    if journal_match:
        ref.journal = journal_match.group(0).strip().rstrip('.,;')

    return ref


# ---------------------------------------------------------------------------
# Citation Counting
# ---------------------------------------------------------------------------

def count_citations_numbered(
    body_text: str,
    refs: list[ParsedReference],
    sections: dict[str, str] | None = None,
) -> list[CitationEntry]:
    """
    Count how many times each numbered reference is cited in the body text.
    Also extract context sentences.
    """
    entries: list[CitationEntry] = []
    max_ref = max((r.ref_num for r in refs), default=0)

    # Build a set of ref numbers for quick lookup
    ref_by_num: dict[int, ParsedReference] = {r.ref_num: r for r in refs}

    # Count occurrences for each reference number
    cite_counts: dict[int, int] = {r.ref_num: 0 for r in refs}
    cite_contexts: dict[int, list[CitationContext]] = {r.ref_num: [] for r in refs}

    # Split body text into sentences for context extraction
    sentences = _split_sentences(body_text)

    # Determine which section each sentence belongs to (approximate)
    section_map = _build_section_map(body_text, sections) if sections else {}

    for sentence in sentences:
        # Find all citation numbers in this sentence
        cited_nums = _extract_citation_numbers(sentence, max_ref)
        for num in cited_nums:
            if num in cite_counts:
                cite_counts[num] += 1
                # Find approximate section
                sec = _find_sentence_section(sentence, section_map)
                cite_contexts[num].append(CitationContext(
                    sentence=sentence.strip()[:300],
                    section=sec,
                ))

    # Build entries
    for ref in refs:
        entry = CitationEntry(
            ref=ref,
            cite_count=cite_counts.get(ref.ref_num, 0),
            cite_contexts=cite_contexts.get(ref.ref_num, []),
        )
        entries.append(entry)

    return entries


def count_citations_author_year(
    body_text: str,
    refs: list[ParsedReference],
    sections: dict[str, str] | None = None,
) -> list[CitationEntry]:
    """
    Count author-year style citations: (Author et al., 2024), (Author, 2023).
    """
    entries: list[CitationEntry] = []
    sentences = _split_sentences(body_text)
    section_map = _build_section_map(body_text, sections) if sections else {}

    for ref in refs:
        cite_count = 0
        contexts: list[CitationContext] = []

        if not ref.authors:
            entries.append(CitationEntry(ref=ref, cite_count=0))
            continue

        # Extract first author surname for matching
        first_author = _extract_first_surname(ref.authors)
        if not first_author:
            entries.append(CitationEntry(ref=ref, cite_count=0))
            continue

        year_str = str(ref.year) if ref.year else ""

        for sentence in sentences:
            # Check if this author (+year) is mentioned
            if first_author.lower() in sentence.lower():
                if not year_str or year_str in sentence:
                    cite_count += 1
                    sec = _find_sentence_section(sentence, section_map)
                    contexts.append(CitationContext(
                        sentence=sentence.strip()[:300],
                        section=sec,
                    ))

        entries.append(CitationEntry(
            ref=ref,
            cite_count=cite_count,
            cite_contexts=contexts,
        ))

    return entries


def _extract_citation_numbers(sentence: str, max_ref: int) -> set[int]:
    """
    Extract all cited reference numbers from a sentence.
    Handles: [1], [1,2,3], [1-5], [1, 3, 5-8]
    """
    nums: set[int] = set()

    # Find all bracket citation groups
    for match in re.finditer(r'\[([\d,\s\-\u2013]+)\]', sentence):
        group = match.group(1)
        # Split by comma
        parts = re.split(r'[,\s]+', group)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # Check for range: "1-5" or "1\u20135"
            range_match = re.match(r'(\d+)[\-\u2013](\d+)', part)
            if range_match:
                start = int(range_match.group(1))
                end = int(range_match.group(2))
                for n in range(start, min(end + 1, max_ref + 1)):
                    nums.add(n)
            elif part.isdigit():
                n = int(part)
                if 1 <= n <= max_ref:
                    nums.add(n)

    # Also check superscript-style: just bare numbers after text
    # e.g., "method1,2" — less reliable, skip for now

    return nums


def _extract_first_surname(authors_str: str) -> str:
    """Extract the first author's surname from an author string."""
    # "Smith A, Jones B" -> "Smith"
    # "Smith, A. and Jones, B." -> "Smith"
    # "A. Smith et al." -> "Smith"
    authors_str = authors_str.strip()

    # Handle "et al." suffix
    authors_str = re.sub(r'\s*et\s+al\.?\s*$', '', authors_str, flags=re.IGNORECASE)

    # Try "Surname, Initial" format
    match = re.match(r'([A-Z][a-z\u00C0-\u024F]+)', authors_str)
    if match:
        return match.group(1)

    return ""


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences (approximate)."""
    # Split on period/question/exclamation followed by space and uppercase
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z\[\(])', text)
    return [s for s in sentences if len(s) > 10]


def _build_section_map(body_text: str, sections: dict[str, str] | None) -> dict[str, str]:
    """
    Build a mapping from text snippets to section names.
    Returns {first_50_chars: section_name} for quick lookup.
    """
    if not sections:
        return {}
    result = {}
    for sec_name, sec_text in sections.items():
        if sec_text and sec_name not in ("full_text", "references"):
            # Store first 100 chars as key
            key = sec_text[:100].strip()
            if key:
                result[key] = sec_name
    return result


def _find_sentence_section(sentence: str, section_map: dict[str, str]) -> str:
    """Find which section a sentence belongs to (best guess)."""
    if not section_map:
        return ""
    sentence_lower = sentence.lower()[:50]
    for key, sec_name in section_map.items():
        if sentence_lower in key.lower():
            return sec_name
    return ""


# ---------------------------------------------------------------------------
# Citation Distribution
# ---------------------------------------------------------------------------

def compute_citation_distribution(
    entries: list[CitationEntry],
) -> dict[str, int]:
    """
    Compute how citations are distributed across paper sections.
    """
    distribution: dict[str, int] = {}
    for entry in entries:
        for ctx in entry.cite_contexts:
            sec = ctx.section or "unknown"
            distribution[sec] = distribution.get(sec, 0) + 1
    return distribution


# ---------------------------------------------------------------------------
# Self-Citation Detection
# ---------------------------------------------------------------------------

def count_self_citations(
    entries: list[CitationEntry],
    paper_authors: str,
) -> tuple[int, float]:
    """
    Count how many references are self-citations (share authors with the paper).

    Returns:
        (self_citation_count, self_citation_ratio)
    """
    if not paper_authors:
        return 0, 0.0

    # Extract author surnames from the paper
    paper_surnames = set()
    for name in re.split(r'[,;&]+', paper_authors):
        name = name.strip()
        surname = _extract_first_surname(name)
        if surname and len(surname) > 2:
            paper_surnames.add(surname.lower())

    if not paper_surnames:
        return 0, 0.0

    self_count = 0
    for entry in entries:
        ref_authors = entry.ref.authors.lower()
        for surname in paper_surnames:
            if surname in ref_authors:
                self_count += 1
                break

    total = len(entries)
    ratio = self_count / total if total > 0 else 0.0

    return self_count, round(ratio, 3)


# ---------------------------------------------------------------------------
# Main Analysis Function
# ---------------------------------------------------------------------------

def analyze_citations(
    references_text: str,
    body_text: str,
    sections: dict[str, str] | None = None,
    paper_authors: str = "",
) -> CitationAnalysisResult:
    """
    Run full citation analysis.

    Args:
        references_text: The References section text.
        body_text: Full body text (excluding references).
        sections: Optional section dict for distribution analysis.
        paper_authors: Authors of the paper (for self-citation detection).

    Returns:
        CitationAnalysisResult with all analysis data.
    """
    result = CitationAnalysisResult()

    if not references_text:
        logger.warning("No references text provided for citation analysis.")
        return result

    # 1. Parse references
    refs = parse_references(references_text)
    result.total_references = len(refs)

    if not refs:
        logger.warning("No references could be parsed.")
        return result

    # 2. Detect citation style
    style = detect_citation_style(body_text)
    result.citation_style = style

    # 3. Count citations
    if style == "numbered":
        entries = count_citations_numbered(body_text, refs, sections)
    else:
        entries = count_citations_author_year(body_text, refs, sections)

    # Sort by citation count (descending)
    entries.sort(key=lambda e: e.cite_count, reverse=True)
    result.entries = entries

    # 4. Citation distribution
    result.citation_distribution = compute_citation_distribution(entries)

    # 5. Self-citation detection
    self_count, self_ratio = count_self_citations(entries, paper_authors)
    result.self_citation_count = self_count
    result.self_citation_ratio = self_ratio

    logger.info(
        "Citation analysis: %d refs, style=%s, top_cited=%s (count=%d)",
        result.total_references,
        style,
        entries[0].ref.ref_id if entries else "N/A",
        entries[0].cite_count if entries else 0,
    )

    return result
