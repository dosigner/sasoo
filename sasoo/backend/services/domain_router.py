"""
Sasoo - Domain Router
Classifies academic papers into domains for agent routing.

Classification pipeline:
  Step 1: Keyword matching (fast, no API call)
  Step 2: If confidence < 0.7 (or the top two scores are ambiguously close),
          flag needs_confirmation=True for user review. There is no semantic
          LLM fallback — the screening phase re-detects the domain from the
          PDF body right after upload, and the upload UI offers a manual
          domain dropdown, so a second classification pass here would be
          redundant.
  Step 3: needs_confirmation=True routes to user review.

Domains are loaded dynamically from .md agent profiles.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain definitions
# ---------------------------------------------------------------------------

@dataclass
class DomainSpec:
    """Definition of a scientific domain with its classification keywords."""
    name: str
    display_name: str
    display_name_ko: str
    agent_name: str
    keywords: list[str]
    weighted_keywords: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class DomainResult:
    """Result of domain classification."""
    domain: str
    display_name: str
    display_name_ko: str
    agent_name: str
    confidence: float
    method: str  # "keyword" | "semantic" | "manual"
    needs_confirmation: bool
    keyword_matches: list[str] = field(default_factory=list)
    all_scores: dict[str, float] = field(default_factory=dict)
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "display_name": self.display_name,
            "display_name_ko": self.display_name_ko,
            "agent_name": self.agent_name,
            "confidence": round(self.confidence, 3),
            "method": self.method,
            "needs_confirmation": self.needs_confirmation,
            "keyword_matches": self.keyword_matches,
            "all_scores": {k: round(v, 3) for k, v in self.all_scores.items()},
            "reasoning": self.reasoning,
        }


# ---------------------------------------------------------------------------
# DomainRouter
# ---------------------------------------------------------------------------

class DomainRouter:
    """
    Multi-step domain classifier for academic papers.
    Domains are loaded dynamically from agent .md profiles.

    Usage:
        router = DomainRouter()
        router.load_from_agents(agent_profiles)
        result = await router.classify("Paper Title", "Paper abstract...")
    """

    CONFIDENCE_THRESHOLD = 0.7
    AMBIGUITY_GAP = 0.15

    def __init__(self) -> None:
        self._domains: dict[str, DomainSpec] = {}
        self._patterns: dict[str, list[re.Pattern]] = {}
        self._weighted_patterns: dict[str, list[re.Pattern]] = {}

    def load_from_agents(self, agents) -> None:
        """
        Build domain specs dynamically from agent profiles.

        Args:
            agents: list of AgentProfile objects (from md_loader.list_all_agents)
        """
        self._domains.clear()
        self._patterns.clear()
        self._weighted_patterns.clear()

        for profile in agents:
            if not profile.enabled:
                continue
            if not profile.domain:
                continue

            spec = DomainSpec(
                name=profile.domain,
                display_name=profile.domain_display or profile.display_name,
                display_name_ko=profile.domain_display_ko or profile.display_name_ko,
                agent_name=profile.agent_name,
                keywords=profile.keywords or [],
                weighted_keywords=profile.weighted_keywords or [],
            )
            self._domains[spec.name] = spec
            self._patterns[spec.name] = [
                re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
                for kw in spec.keywords
            ]
            self._weighted_patterns[spec.name] = [
                re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
                for kw in spec.weighted_keywords
            ]

        logger.info("DomainRouter loaded %d domains from agents", len(self._domains))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def classify(self, title: str, abstract: str) -> DomainResult:
        """Classify a paper into a domain."""
        if not self._domains:
            return DomainResult(
                domain="unknown", display_name="Unknown",
                display_name_ko="미분류", agent_name="",
                confidence=0.0, method="keyword",
                needs_confirmation=True,
                reasoning="No domains loaded.",
            )

        keyword_result = self._keyword_classify(title, abstract)
        logger.info(
            "Keyword classification: domain=%s confidence=%.3f matches=%s",
            keyword_result.domain, keyword_result.confidence,
            keyword_result.keyword_matches,
        )

        if keyword_result.confidence >= self.CONFIDENCE_THRESHOLD:
            scores = keyword_result.all_scores
            sorted_scores = sorted(scores.values(), reverse=True)
            if len(sorted_scores) >= 2:
                gap = sorted_scores[0] - sorted_scores[1]
                if gap < self.AMBIGUITY_GAP:
                    return await self._semantic_classify(
                        title, abstract, keyword_result
                    )
            return keyword_result

        return await self._semantic_classify(title, abstract, keyword_result)

    def override(self, domain: str) -> DomainResult:
        """Manually override domain classification."""
        if domain not in self._domains:
            valid = ", ".join(self._domains.keys())
            raise ValueError(f"Unknown domain: {domain!r}. Valid domains: {valid}")

        spec = self._domains[domain]
        return DomainResult(
            domain=domain,
            display_name=spec.display_name,
            display_name_ko=spec.display_name_ko,
            agent_name=spec.agent_name,
            confidence=1.0,
            method="manual",
            needs_confirmation=False,
            reasoning="User manual override.",
        )

    # ------------------------------------------------------------------
    # Step 1: Keyword matching
    # ------------------------------------------------------------------

    def _keyword_classify(self, title: str, abstract: str) -> DomainResult:
        combined_text = f"{title}\n{abstract}"
        title_lower = title.lower()

        scores: dict[str, float] = {}
        matches_map: dict[str, list[str]] = {}

        for domain_key in self._domains:
            score = 0.0
            matched: list[str] = []

            for pattern in self._patterns.get(domain_key, []):
                body_hits = len(pattern.findall(combined_text))
                title_hits = len(pattern.findall(title_lower))
                if body_hits > 0:
                    score += body_hits
                    matched.append(pattern.pattern.replace(r"\b", ""))
                if title_hits > 0:
                    score += title_hits * 2

            for pattern in self._weighted_patterns.get(domain_key, []):
                body_hits = len(pattern.findall(combined_text))
                title_hits = len(pattern.findall(title_lower))
                if body_hits > 0:
                    score += body_hits * 2
                    matched.append(pattern.pattern.replace(r"\b", ""))
                if title_hits > 0:
                    score += title_hits * 4

            scores[domain_key] = score
            matches_map[domain_key] = matched

        max_score = max(scores.values()) if scores else 0.0
        if max_score > 0:
            normalized = {k: v / max_score for k, v in scores.items()}
        else:
            normalized = {k: 0.0 for k in scores}

        best_domain = max(normalized, key=lambda k: normalized[k])
        best_confidence = normalized[best_domain]

        total_matches = len(matches_map.get(best_domain, []))
        if total_matches <= 1:
            best_confidence = min(best_confidence, 0.4)
        elif total_matches <= 2:
            best_confidence = min(best_confidence, 0.6)

        if max_score == 0:
            return DomainResult(
                domain="unknown", display_name="Unknown",
                display_name_ko="미분류", agent_name="",
                confidence=0.0, method="keyword",
                needs_confirmation=True, keyword_matches=[],
                all_scores=normalized,
                reasoning="No domain keywords matched.",
            )

        spec = self._domains[best_domain]
        return DomainResult(
            domain=best_domain,
            display_name=spec.display_name,
            display_name_ko=spec.display_name_ko,
            agent_name=spec.agent_name,
            confidence=round(best_confidence, 3),
            method="keyword",
            needs_confirmation=False,
            keyword_matches=matches_map.get(best_domain, []),
            all_scores=normalized,
            reasoning=f"Matched {total_matches} keywords in domain '{best_domain}'.",
        )

    # ------------------------------------------------------------------
    # Step 2: Semantic classification fallback (removed)
    # ------------------------------------------------------------------

    async def _semantic_classify(
        self, title: str, abstract: str, keyword_result: DomainResult,
    ) -> DomainResult:
        """No semantic LLM fallback — always defer to user confirmation.

        The screening phase re-detects the domain from the PDF body right
        after upload and can correct a low-confidence/ambiguous keyword
        guess, and the upload UI offers a manual domain dropdown. A second
        LLM classification pass here would be redundant, so keyword-only
        results that don't clear the confidence/ambiguity bar are simply
        flagged for confirmation instead.
        """
        keyword_result.needs_confirmation = True
        keyword_result.reasoning += " (No semantic fallback; user confirmation required.)"
        return keyword_result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_available_domains(self) -> list[dict]:
        """Return list of all available domains with metadata."""
        return [
            {
                "key": spec.name,
                "display_name": spec.display_name,
                "display_name_ko": spec.display_name_ko,
                "agent_name": spec.agent_name,
                "keyword_count": len(spec.keywords) + len(spec.weighted_keywords),
            }
            for spec in self._domains.values()
        ]

    def get_agent_for_domain(self, domain: str) -> Optional[str]:
        """Return agent name for a given domain, or None if unknown."""
        spec = self._domains.get(domain)
        return spec.agent_name if spec else None
