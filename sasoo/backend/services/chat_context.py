"""Build reading context without changing cached analysis inputs."""

from typing import Any


def build_reading_context(document: dict[str, Any]) -> tuple[str, bool]:
    """Reserve space for each overview section so long introductions cannot hide conclusions."""
    sections = document.get("sections") or {}
    budgets = (("abstract", 2000), ("introduction", 2500), ("conclusion", 1800))
    parts = []
    truncated = False
    for name, limit in budgets:
        text = str(sections.get(name) or "").strip()
        if not text:
            continue
        clipped = len(text) > limit
        truncated |= clipped
        excerpt = text[:limit].rstrip() + ("\n[이 절의 나머지 원문은 생략됨]" if clipped else "")
        parts.append(f"=== {name.upper()} ===\n{excerpt}")

    names = [name for name, value in sections.items() if value and name != "full_text"]
    outline = ", ".join(names)[:600]
    if parts:
        missing = [name for name, _ in budgets if not str(sections.get(name) or "").strip()]
        preface = f"원문 일부 발췌. 감지한 절 목록: {outline}. 절 이름은 자동 분류한 이름이야."
        if missing:
            preface += f"\n발췌하지 못한 절: {', '.join(missing)}. 논문에 그 절이 없다고 단정하지 마."
        return preface + "\n\n" + "\n\n".join(parts), truncated

    text = str(document.get("full_text") or sections.get("full_text")
               or document.get("phase_inputs", {}).get("chat") or "").strip()
    if not text:
        return "", False
    # Without section boundaries, label a prefix honestly rather than inventing an abstract.
    clipped = len(text) > 6300
    excerpt = text[:6300].rstrip() + ("\n[이후 원문은 생략됨]" if clipped else "")
    preface = (f"감지한 절 목록: {outline}. 자동 분류한 이름이며 원문의 정확한 제목은 확인하지 못했어. "
               "초록, 서론, 결론을 발췌하지 못해 원문 앞부분을 제공해." if names else
               "절 구분을 확인하지 못해 원문 앞부분을 제공해. 절이 없는지 감지에 실패했는지는 확인하지 못했어.")
    return preface + " 초록이나 결론으로 단정하지 마.\n" + excerpt, clipped
