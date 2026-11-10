"""Resolve a PDF selection on physical pages without fuzzy or global search."""

import re
from pathlib import Path

import fitz

SELECTION_LIMIT = 2000
NEIGHBOR_CHARS = 800
EXCERPT_LIMIT = 5000


def validate_selection(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("선택 위치 형식이 올바르지 않습니다.")
    text = value.get("text")
    page = value.get("page")
    end_page = value.get("end_page", page)
    if (not isinstance(text, str) or not text.strip() or len(text) > SELECTION_LIMIT
            or type(page) is not int or type(end_page) is not int
            or page < 1 or end_page < page):
        raise ValueError("선택 구절과 PDF 페이지를 확인해 주세요 (최대 2,000자).")
    return {"text": text, "page": page, "end_page": end_page}


def _normalized(text: str, *, dehyphenate: bool, selection: bool = False) -> tuple[str, list[int]]:
    # Keep source offsets. Normalized text is used only for matching.
    skipped = set()
    if dehyphenate:
        separator = r"[-\u00ad]\s+" if selection else r"(?:-\s*\n\s*|\u00ad\s*)"
        for match in re.finditer(r"(?<=[A-Za-z]{2})" + separator + r"(?=[A-Za-z]{2})", text):
            skipped.update(range(match.start(), match.end()))
    chars, offsets = [], []
    for index, char in enumerate(text):
        if index in skipped:
            continue
        if char.isspace():
            if not chars or chars[-1] == " ":
                continue
            char = " "
        chars.append(char)
        offsets.append(index)
    return "".join(chars), offsets


def match_selection(pages: list[str], selection: dict) -> dict:
    result = {"selection": selection, "status": "unverified", "reason": "주변 문맥을 확인하지 못했습니다."}
    if not pages or len(pages) != selection["end_page"] - selection["page"] + 1:
        return result
    source = "\n".join(pages)
    matches = set()
    for dehyphenate in (False, True):
        haystack, offsets = _normalized(source, dehyphenate=dehyphenate)
        needle, _ = _normalized(selection["text"], dehyphenate=dehyphenate, selection=True)
        needle = needle.strip()
        if len(needle.replace(" ", "")) < 4:
            return result
        cursor = 0
        while (at := haystack.find(needle, cursor)) >= 0:
            start, end = offsets[at], offsets[at + len(needle) - 1] + 1
            original_needle, _ = _normalized(selection["text"], dehyphenate=False)
            if needle != original_needle.strip() and not re.search(r"-\s*\n|\u00ad", source[start:end]):
                cursor = at + 1
                continue
            # A cross-page selection must actually cover both supplied pages.
            if len(pages) == 1 or start < len(pages[0]) < end:
                matches.add((start, end))
            cursor = at + 1
    if len(matches) != 1:
        result["reason"] = "같은 구절이 여러 번 있어 위치를 확정하지 못했습니다." if matches else result["reason"]
        return result
    start, end = matches.pop()
    if end - start > EXCERPT_LIMIT:
        return result
    left, right = max(0, start - NEIGHBOR_CHARS), min(len(source), end + NEIGHBOR_CHARS)
    # Prefer paragraph boundaries inside the fixed window.
    boundary = source.rfind("\n\n", left, start)
    if boundary >= 0:
        left = boundary + 2
    boundary = source.find("\n\n", end, right)
    if boundary >= 0:
        right = boundary
    if right - left > EXCERPT_LIMIT:
        left, right = start, end
    return {**result, "status": "matched", "reason": "PDF 원문에서 유일하게 일치한 위치입니다.",
            "source": "PDF text extraction (physical page, 1-based)",
            "match_start": start, "match_end": end,
            "excerpt": source[left:right], "excerpt_start": left,
            "partial_before": left > 0, "partial_after": right < len(source)}


def build_selection_context(paper_dir: Path, selection: dict) -> dict:
    fallback = {"selection": selection, "status": "unverified", "reason": "주변 문맥을 확인하지 못했습니다. 선택 구절만 제공합니다."}
    # Bound extraction to the selected page and at most one adjacent page.
    if selection["end_page"] - selection["page"] > 1:
        return fallback
    try:
        pdfs = sorted(Path(paper_dir).glob("*.pdf"))
        if len(pdfs) != 1:
            return fallback
        with fitz.open(pdfs[0]) as pdf:
            if selection["end_page"] > len(pdf):
                return fallback
            pages = [
                "\n\n".join(block[4] for block in pdf[i].get_text("blocks", sort=False) if block[6] == 0)
                for i in range(selection["page"] - 1, selection["end_page"])
            ]
        return match_selection(pages, selection)
    except (OSError, RuntimeError, ValueError):
        return fallback
