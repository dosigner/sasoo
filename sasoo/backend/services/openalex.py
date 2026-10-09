"""OpenAlex 분야 조회.

업로드한 논문의 DOI로 OpenAlex `primary_topic`의 소분야를 찾는다. 범위는
Physical Sciences와 Life Sciences의 15개 대분야이며, 그 소분야 표는 번들
`agents/openalex_subfields.json`(CC0)에 있다. DOI가 없거나, 범위 밖이거나,
호출이 실패하면 None을 돌려주고 호출부는 키워드 분류로 폴백한다.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Optional
from urllib.parse import quote

import httpx

from services.agents.md_loader import _get_bundled_agents_directory

logger = logging.getLogger(__name__)

OPENALEX_WORKS_URL = "https://api.openalex.org/works/doi:"
LOOKUP_TIMEOUT_S = 3.0
_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "doi:")


@lru_cache(maxsize=1)
def subfields() -> dict[int, dict]:
    """소분야 ID → {name, field_id, field}. 15개 대분야만 담는다."""
    raw = json.loads((_get_bundled_agents_directory() / "openalex_subfields.json").read_text("utf-8"))
    return {int(key): value for key, value in raw["subfields"].items()}


def field_name(subfield_id: Optional[int]) -> Optional[str]:
    """소분야의 영문 대분야명(예: "Materials Science"). 표에 없으면 None."""
    entry = subfields().get(subfield_id) if subfield_id is not None else None
    return entry["field"] if entry else None


def _normalize_doi(doi: str) -> str:
    value = doi.strip()
    for prefix in _DOI_PREFIXES:
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
    return value


async def lookup_subfield(doi: Optional[str]) -> Optional[int]:
    """DOI의 primary_topic 소분야 ID. 키 없이 호출한다(단건 조회는 무료)."""
    if not doi or not doi.strip():
        return None
    url = OPENALEX_WORKS_URL + quote(_normalize_doi(doi), safe="/")
    try:
        async with httpx.AsyncClient(timeout=LOOKUP_TIMEOUT_S) as client:
            response = await client.get(url, params={"select": "primary_topic"})
        response.raise_for_status()
        topic = response.json().get("primary_topic") or {}
    except (httpx.HTTPError, ValueError) as exc:
        # 401/429/타임아웃/오프라인이 쌓이면 설정에 API 키 칸을 더할지 판단한다.
        logger.warning("OpenAlex lookup failed for %s: %s", doi, exc)
        return None

    subfield = topic.get("subfield") or {}
    try:
        subfield_id = int(str(subfield.get("id", "")).rsplit("/", 1)[-1])
    except ValueError:
        return None
    logger.info(
        "OpenAlex %s -> subfield %s %r (score %s)",
        doi, subfield_id, subfield.get("display_name"), topic.get("score"),
    )
    return subfield_id if subfield_id in subfields() else None
