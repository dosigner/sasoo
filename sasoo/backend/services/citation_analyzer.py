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

import bisect
import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_JOURNAL_PATTERN = re.compile(
    r'\b(?:Nature|Science|Cell|Phys\.\s*Rev(?:\s+\w+)?|Adv\.\s*Mater|ACS\s+\w+|'
    r'IEEE(?:\s+\w+)?|Opt\.\s*Express|Biomed\.\s*Opt\.\s*Express|'
    r'Biomedical\s+optics\s+express|Opt\.\s*Eng\.?|Astron\.\s*Astrophys\.?|'
    r'J\.\s*Biophotonics|J\.\s*Opt\.\s*Soc\.\s*Am\.\s*[AB]?|'
    r'J\.\s*Astron\.\s*Telesc\.\s*Instrum\.\s*Syst\.?|Appl\.\s*\w+|'
    r'Proc\.\s*SPIE|Ann\.\s*\w+|Light:\s*\w+|Optica|Photonics|Laser|'
    r'Chem\.\s*\w+|Angew\.\s*\w+|PNAS|PLoS|BMC\s+\w+|Nat\.\s*\w+)\b[^,;.]*',
    re.IGNORECASE,
)


_BRACKET_CITE = re.compile(r'\[\d+(?:[,\s\-\u2013]+\d+)*\]')

# 저자 이름 토큰 판정. `A`, `S.`는 이니셜이고 성이 아니다.
_INITIAL_TOKEN = re.compile(r"^[A-Z]\.?$")
_NAME_TOKEN = re.compile(r"^[A-Za-z\u00C0-\u024F][A-Za-z\u00C0-\u024F'\u2019\-]+$")

# Nature/Scientific Reports 계열은 본문 인용이 위첨자 숫자다. PDF 텍스트 추출에서
# 위첨자라는 정보가 사라져 `reciprocity23`처럼 단어 끝에 숫자가 붙은 채로 떨어진다.
# 앞 단어를 3글자 이상으로 제한하는 것이 오탐 방지의 핵심이다 — 이것만으로 변수와
# 수식(`w0`, `r0`, `Cn2`, `m3`, `a15\u00d7`, `10\u22123`)이 전부 걸러진다.
# 뒤쪽은 소수점만 막는다(`version1.2`). 마침표 전부를 막으면 문장 끝의 `interval26.`을
# 함께 놓친다.
_SUPERSCRIPT_CITE = re.compile(
    r"(?<![\d.])([A-Za-z]{3,})(\d{1,3}(?:[,\u2013\-]\d{1,3})*)(?!\d)(?!\.\d)"
)

# 3글자 제한을 통과하지만 인용이 아닌 참조어. `Table1`, `Fig2`, `Eq3` 같은 것들이다.
_NOT_A_CITATION_WORD = re.compile(
    r"^(?:table|fig|figs|figure|eq|eqs|equation|section|sec|ref|refs|chapter|appendix|"
    r"algorithm|step|phase|level|type|class|group|case|mode|model|method|sample|test|"
    r"exp|part|panel|note|line|row|col|column|item|task|stage|round|run|set|version)$",
    re.IGNORECASE,
)

# 본문의 대괄호 인용이 이보다 적으면 위첨자 폴백을 켠다. 실측(14편): 위첨자를 쓰는
# 논문은 0개이고, 대괄호를 쓰는 논문은 23~586개라 사이가 넓게 비어 있다.
_SUPERSCRIPT_BRACKET_MAX = 5

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
                # 5개로 자른 cite_contexts와 달리 전체 맥락의 섹션 집계. LLM 후보 필터가
                # "본문에서도 인용됐는가"를 판단할 때 쓴다(앞 5개는 대개 introduction이라 못 믿는다).
                "section_counts": _count_by_section(entry.cite_contexts),
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


def _count_by_section(contexts: list[CitationContext]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ctx in contexts:
        counts[ctx.section or ""] = counts.get(ctx.section or "", 0) + 1
    return counts


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

    # Numbered styles: "[1] ..." and "1. ...". 둘 다 파싱해 ref_num 중복이 적은 쪽을 쓴다.
    # get_references_text가 본문까지 끌고 오면(2017_COMST 261KB) 본문 인용 마커 "[85]"가
    # 대괄호 갈래의 구분자로 오인돼 같은 번호가 여러 번 나온다(2014 논문 72% 중복). 그런
    # 논문은 "1." 갈래가 깨끗하다. 동률이면 대괄호 우선(중복 0%였던 9편 동작 보존).
    numbered_pattern = re.compile(
        r'\[(\d+)\]\s*(.+?)(?=\[\d+\]|\Z)',
        re.DOTALL,
    )
    dot_pattern = re.compile(
        r'(?:^|\n)\s*(\d+)\.\s+(.+?)(?=\n\s*\d+\.|\Z)',
        re.DOTALL,
    )
    candidates = [
        m for m in (numbered_pattern.findall(references_text), dot_pattern.findall(references_text))
        if len(m) >= 3
    ]
    if candidates:
        matches = min(candidates, key=_ref_num_duplicate_ratio)  # min은 첫 최소값 → 동률이면 대괄호
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


def _ref_num_duplicate_ratio(matches: list[tuple[str, str]]) -> float:
    """(num_str, text) 매치 목록에서 같은 번호가 반복된 비율. 0.0이면 전부 고유."""
    nums = [int(n) for n, _ in matches]
    return 1.0 - len(set(nums)) / len(nums)


def _parse_single_reference(text: str, num: int) -> ParsedReference:
    """
    Extract metadata from a single reference string.
    Best-effort extraction of authors, title, journal, year.
    """
    ref = ParsedReference(ref_num=num, raw_text=text)

    # Clean up
    text = re.sub(r'\s+', ' ', text).strip()

    journal_match = _JOURNAL_PATTERN.search(text)

    # Extract year (4-digit number, typically 19xx or 20xx)
    year_match = re.search(r'\b((?:19|20)\d{2})\b', text)
    if year_match:
        ref.year = int(year_match.group(1))

    prefix_end = len(text)
    if journal_match:
        prefix_end = journal_match.start()
    elif year_match:
        prefix_end = year_match.start()

    authors, title = _split_reference_prefix(text[:prefix_end].strip(" ,.;"))
    if authors:
        ref.authors = authors
    if title:
        ref.title = title

    if not ref.title:
        quoted = re.search(r'["\u201c](.+?)["\u201d]', text)
        if quoted:
            ref.title = quoted.group(1)

    # Try to extract journal (usually italic or after title, contains common journal words)
    if journal_match:
        ref.journal = journal_match.group(0).strip().rstrip('.,;')

    return ref


def _split_reference_prefix(prefix: str) -> tuple[str, str]:
    prefix = prefix.strip(" ,.;")
    if not prefix:
        return "", ""

    quoted = re.search(r'["\u201c](.+?)["\u201d]', prefix)
    if quoted:
        authors = prefix[:quoted.start()].strip(" ,.;")
        title = quoted.group(1).strip(" ,.;")
        return authors, title

    comma_idx = prefix.find(",")
    if comma_idx > 0:
        candidate_authors = prefix[:comma_idx].strip()
        candidate_title = prefix[comma_idx + 1:].strip(" ,.;")
        if _looks_like_author_prefix(candidate_authors) and len(candidate_title.split()) >= 3:
            return candidate_authors, candidate_title

    sentence_boundaries = list(re.finditer(r'\.\s+(?=[A-Z][a-z]{2,})', prefix))
    for boundary in reversed(sentence_boundaries):
        candidate_authors = prefix[: boundary.start() + 1].strip(" ,.;")
        candidate_title = prefix[boundary.end() :].strip(" ,.;")
        if _looks_like_author_prefix(candidate_authors) and len(candidate_title.split()) >= 3:
            return candidate_authors, candidate_title

    parts = prefix.split('. ', 1)
    if len(parts) == 2 and _looks_like_author_prefix(parts[0]):
        return parts[0].strip(" ,.;"), parts[1].strip(" ,.;")

    return "", prefix


def _looks_like_author_prefix(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    if normalized.lower().startswith(("introduction", "method", "results", "discussion", "conclusion")):
        return False
    return bool(
        re.search(r'\b[A-Z]\.', normalized)
        or re.search(r'\bet\s+al\b', normalized, re.IGNORECASE)
        or "&" in normalized
        or " and " in normalized.lower()
        or normalized.count(",") >= 2
    )


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

    # 문장과 그 문장이 속한 섹션을 함께 훑는다.
    sentences = _iter_sentences_with_section(body_text, sections)

    # 위첨자 인용을 쓰는 논문인지는 문서 전체를 봐야 안다. 대괄호 인용이 거의 없는데
    # 참고문헌은 있는 논문이 그 경우다(Nature, Scientific Reports 계열).
    use_superscript = len(_BRACKET_CITE.findall(body_text)) < _SUPERSCRIPT_BRACKET_MAX
    if use_superscript:
        logger.info(
            "Citation: 대괄호 인용이 %d개뿐이라 위첨자 인용 추출을 켠다 (refs=%d).",
            len(_BRACKET_CITE.findall(body_text)), max_ref,
        )

    for sentence, sec in sentences:
        # Find all citation numbers in this sentence
        cited_nums = _extract_citation_numbers(sentence, max_ref, superscript=use_superscript)
        for num in cited_nums:
            if num in cite_counts:
                cite_counts[num] += 1
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
    sentences = list(_iter_sentences_with_section(body_text, sections))

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

        for sentence, sec in sentences:
            # Check if this author (+year) is mentioned
            if first_author.lower() in sentence.lower():
                if not year_str or year_str in sentence:
                    cite_count += 1
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


def _extract_citation_numbers(sentence: str, max_ref: int, *, superscript: bool = False) -> set[int]:
    """
    Extract all cited reference numbers from a sentence.
    Handles: [1], [1,2,3], [1-5], [1, 3, 5-8]

    superscript=True이면 `reciprocity23`처럼 단어 끝에 붙은 숫자도 인용으로 인정한다.
    켜는 판단은 문서 단위이므로 호출자(`count_citations_numbered`)가 한다.
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

    # 위첨자 인용(Nature/Scientific Reports 계열). 이 갈래를 켤지는 호출자가 문서 전체를
    # 보고 정한다 — 문장 단위로는 대괄호를 쓰는 논문인지 알 수 없기 때문이다.
    if superscript:
        for word, digits in _SUPERSCRIPT_CITE.findall(sentence):
            if _NOT_A_CITATION_WORD.match(word):
                continue
            for part in re.split(r'[,\u2013\-]', digits):
                if part.isdigit() and 1 <= int(part) <= max_ref:
                    nums.add(int(part))

    return nums


def _extract_first_surname(authors_str: str) -> str:
    """첫 저자의 성을 뽑는다.

    옛 구현은 맨 앞의 대문자 단어를 성으로 봤다. 성이 먼저 오는 형식(`Smith, A.`)에서만
    맞고, arXiv에서 표준인 이름 먼저 형식(`Niket Agarwal`)에서는 이름을 돌려준다. 본문은
    `Agarwal et al.`로 인용하므로 `count_citations_author_year`의 매칭이 통째로 0이 됐다
    (실측 2026-09-01: GR00T N1은 참고문헌 102개에 인용 3회, 0회 비율 98%).
    이니셜로 시작하는 `A. Smith et al.`은 정규식이 아예 안 맞아 빈 문자열이었다 —
    옛 docstring이 스스로 들었던 세 번째 예시가 그것이다.

    규칙: `et al.` 꼬리를 떼고, 첫 저자 블록만 남기고, 이니셜을 걸러낸 뒤 마지막 토큰.
    쉼표는 저자 구분자(`Niket Agarwal, Arslan Ali`)이거나 성과 이니셜의 구분자
    (`Agarwal, N.`)인데, 어느 쪽이든 쉼표 앞이 첫 저자다.
    """
    text = re.sub(r'\s*et\s+al\.?\s*$', '', (authors_str or '').strip(), flags=re.IGNORECASE)
    if not text:
        return ""

    first_author = re.split(r'\s+and\s+|\s*&\s*|\s*;\s*', text, maxsplit=1)[0]
    first_author = first_author.split(',')[0]

    tokens = [
        token for token in first_author.split()
        if not _INITIAL_TOKEN.match(token) and _NAME_TOKEN.match(token)
    ]
    return tokens[-1] if tokens else ""


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences (approximate)."""
    # Split on period/question/exclamation followed by space and uppercase
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z\[\(])', text)
    return [s for s in sentences if len(s) > 10]


def _build_section_spans(body_text: str, sections: dict[str, str] | None) -> list[tuple[int, str]]:
    """body_text 안에서 각 섹션이 시작하는 위치를 (오프셋, 섹션명)으로 낸다.

    `SectionSplitter.get_body_text_without_references`가 섹션 본문을 문서 순서대로
    이어붙이므로, 섹션 앞부분을 찾으면 그 섹션의 시작 위치가 나온다. 끝 경계는 다음
    섹션의 시작이라 따로 기록하지 않는다.
    """
    if not sections:
        return []

    spans: list[tuple[int, str]] = []
    cursor = 0
    for sec_name, sec_text in sections.items():
        if sec_name in ("full_text", "references") or not sec_text.strip():
            continue
        probe = sec_text[:200].strip()
        if not probe:
            continue
        # 앞선 섹션 뒤에서 먼저 찾는다. 못 찾으면(순서가 어긋나면) 전체에서 다시 찾는다.
        offset = body_text.find(probe, cursor)
        if offset < 0:
            offset = body_text.find(probe)
        if offset < 0:
            continue
        spans.append((offset, sec_name))
        cursor = offset + len(probe)

    spans.sort()
    return spans


def _iter_sentences_with_section(body_text: str, sections: dict[str, str] | None):
    """문장과 그 문장이 속한 섹션 이름을 함께 낸다.

    옛 구현은 섹션의 첫 100자를 키로 만들어 두고 문장 앞 50자가 그 안에 들어있는지를
    봤다. 그래서 각 섹션의 **첫 문장에만** 맞고 나머지는 전부 빈 문자열이 됐다
    (실측 2026-09-01: 2017_COMST의 인용 맥락 824건이 모두 빈 값).

    문장 분할과 인용 카운트는 건드리지 않는다 — `body_text`를 그대로 쪼개되 위치만
    회복해 섹션 구간과 대조한다. 섹션별로 따로 쪼개면 `_trim_reference_tail`이 잘라낸
    꼬리에서 문장 집합이 어긋나 카운트 자체가 달라진다.
    """
    spans = _build_section_spans(body_text, sections)
    starts = [start for start, _ in spans]
    names = [name for _, name in spans]

    # `find`를 커서와 함께 쓰면 같은 문장이 두 번 나와도 어긋나지 않고, 전체가 O(n)이다.
    cursor = 0
    for sentence in _split_sentences(body_text):
        offset = body_text.find(sentence, cursor)
        if offset >= 0:
            cursor = offset + len(sentence)

        section = ""
        if starts and offset >= 0:
            index = bisect.bisect_right(starts, offset) - 1
            if index >= 0:
                section = names[index]
        yield sentence, section


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
