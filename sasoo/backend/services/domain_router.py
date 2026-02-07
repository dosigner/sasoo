"""
Sasoo - Domain Router
Classifies academic papers into domains for agent routing.

Classification pipeline:
  Step 1: Keyword matching (fast, no API call)
  Step 2: If confidence < 0.7, fall back to Gemini Flash semantic classification
  Step 3: If still uncertain, flag needs_confirmation=True for user review

Supported domains (Phase 1 priority order):
  1. optics   - Optics, Photonics, Lasers
  2. bio      - Biology, Biochemistry, Molecular Biology
  3. ai_ml    - Artificial Intelligence, Machine Learning
  4. ee       - Electrical Engineering, Semiconductors
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from services.llm.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain definitions with keyword sets
# ---------------------------------------------------------------------------

@dataclass
class DomainSpec:
    """Definition of a scientific domain with its classification keywords."""
    name: str
    display_name: str
    display_name_ko: str
    agent_name: str
    keywords: list[str]
    # Weighted keywords get 2x score contribution
    weighted_keywords: list[str] = field(default_factory=list)


DOMAINS: dict[str, DomainSpec] = {
    "optics": DomainSpec(
        name="optics",
        display_name="Optics & Photonics",
        display_name_ko="광학/포토닉스",
        agent_name="photon",
        keywords=[
            "wavelength", "laser", "optical", "photon", "lens",
            "aperture", "fso", "turbulence", "diffraction", "refractive",
            "beam", "spectroscopy", "fiber", "coherence", "polarization",
        ],
        weighted_keywords=[
            "free-space optical", "adaptive optics", "beam propagation",
            "wavefront", "interferometer", "spectrometer",
            "photonic crystal", "optical fiber", "laser diode",
            "focal length", "numerical aperture", "fresnel",
            "scintillation", "beam quality", "m-squared",
            "mode-locked", "femtosecond", "photoluminescence",
        ],
    ),
    "bio": DomainSpec(
        name="bio",
        display_name="Biology & Biochemistry",
        display_name_ko="생물/생화학",
        agent_name="cell",
        keywords=[
            "cell", "protein", "gene", "dna", "rna",
            "enzyme", "tissue", "antibody", "metabolite", "sequencing",
        ],
        weighted_keywords=[
            "crispr", "western blot", "pcr", "immunofluorescence",
            "cell culture", "gene expression", "protein folding",
            "genome", "transcriptome", "proteome", "metabolome",
            "in vivo", "in vitro", "apoptosis", "proliferation",
            "plasmid", "transfection", "knock-out",
        ],
    ),
    "ai_ml": DomainSpec(
        name="ai_ml",
        display_name="AI & Machine Learning",
        display_name_ko="인공지능/머신러닝",
        agent_name="neural",
        keywords=[
            "neural network", "deep learning", "transformer", "attention",
            "gradient", "backpropagation", "loss function", "dataset",
            "training",
        ],
        weighted_keywords=[
            "convolutional neural network", "recurrent neural network",
            "generative adversarial", "reinforcement learning",
            "fine-tuning", "pre-training", "language model",
            "batch normalization", "dropout", "embedding",
            "cross-entropy", "softmax", "bert", "gpt",
            "diffusion model", "variational autoencoder",
        ],
    ),
    "ee": DomainSpec(
        name="ee",
        display_name="Electrical Engineering",
        display_name_ko="전기/전자공학",
        agent_name="circuit",
        keywords=[
            "semiconductor", "transistor", "cmos", "voltage", "current",
            "circuit", "impedance", "power",
        ],
        weighted_keywords=[
            "mosfet", "finfet", "gate oxide", "doping",
            "integrated circuit", "vlsi", "analog circuit",
            "digital circuit", "signal processing", "amplifier",
            "oscillator", "power converter", "pcb",
            "electromigration", "threshold voltage", "leakage current",
        ],
    ),
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class DomainResult:
    """Result of domain classification."""
    domain: str                       # Primary domain key
    display_name: str                 # Human-readable domain name
    display_name_ko: str              # Korean domain name
    agent_name: str                   # Corresponding agent identifier
    confidence: float                 # 0.0 - 1.0
    method: str                       # "keyword" | "semantic" | "manual"
    needs_confirmation: bool          # True if user should verify
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

    Usage:
        router = DomainRouter()
        result = await router.classify("Paper Title", "Paper abstract text...")

        # Manual override
        result = router.override("optics")
    """

    CONFIDENCE_THRESHOLD = 0.7
    """Minimum keyword confidence to skip semantic fallback."""

    AMBIGUITY_GAP = 0.15
    """Minimum gap between top-1 and top-2 scores to be considered unambiguous."""

    def __init__(self, gemini_client: Optional[GeminiClient] = None) -> None:
        self._gemini = gemini_client
        # Pre-compile keyword patterns for each domain
        self._patterns: dict[str, list[re.Pattern]] = {}
        self._weighted_patterns: dict[str, list[re.Pattern]] = {}
        for domain_key, spec in DOMAINS.items():
            self._patterns[domain_key] = [
                re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
                for kw in spec.keywords
            ]
            self._weighted_patterns[domain_key] = [
                re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
                for kw in spec.weighted_keywords
            ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def classify(
        self,
        title: str,
        abstract: str,
    ) -> DomainResult:
        """
        Classify a paper into a domain.

        Step 1: Fast keyword matching.
        Step 2: If confidence < threshold, semantic classification via Gemini.
        Step 3: If still uncertain, return needs_confirmation=True.

        Args:
            title: Paper title.
            abstract: Paper abstract.

        Returns:
            DomainResult with domain, confidence, and method used.
        """
        # Step 1: Keyword matching
        keyword_result = self._keyword_classify(title, abstract)
        logger.info(
            "Keyword classification: domain=%s confidence=%.3f matches=%s",
            keyword_result.domain,
            keyword_result.confidence,
            keyword_result.keyword_matches,
        )

        if keyword_result.confidence >= self.CONFIDENCE_THRESHOLD:
            # Check ambiguity: is there a close second?
            scores = keyword_result.all_scores
            sorted_scores = sorted(scores.values(), reverse=True)
            if len(sorted_scores) >= 2:
                gap = sorted_scores[0] - sorted_scores[1]
                if gap < self.AMBIGUITY_GAP:
                    logger.info(
                        "Keyword match is ambiguous (gap=%.3f < %.3f), "
                        "falling through to semantic classification.",
                        gap,
                        self.AMBIGUITY_GAP,
                    )
                    # Fall through to semantic even though confidence is high
                    return await self._semantic_classify(
                        title, abstract, keyword_result
                    )
            return keyword_result

        # Step 2: Semantic classification via Gemini
        return await self._semantic_classify(title, abstract, keyword_result)

    def override(self, domain: str) -> DomainResult:
        """
        Manually override domain classification.

        Args:
            domain: Domain key (optics, bio, ai_ml, ee).

        Returns:
            DomainResult with method="manual" and confidence=1.0.

        Raises:
            ValueError: If domain is not recognized.
        """
        if domain not in DOMAINS:
            valid = ", ".join(DOMAINS.keys())
            raise ValueError(
                f"Unknown domain: {domain!r}. Valid domains: {valid}"
            )

        spec = DOMAINS[domain]
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

    def _keyword_classify(
        self,
        title: str,
        abstract: str,
    ) -> DomainResult:
        """
        Fast keyword-based classification.
        Scores each domain by counting keyword matches in title + abstract.

        Title matches get 3x weight.
        Weighted (multi-word) keyword matches get 2x weight.
        Scores are normalized to 0.0 - 1.0.
        """
        combined_text = f"{title}\n{abstract}"
        title_lower = title.lower()

        scores: dict[str, float] = {}
        matches_map: dict[str, list[str]] = {}

        for domain_key in DOMAINS:
            score = 0.0
            matched: list[str] = []

            # Standard keywords
            for pattern in self._patterns[domain_key]:
                body_hits = len(pattern.findall(combined_text))
                title_hits = len(pattern.findall(title_lower))
                if body_hits > 0:
                    score += body_hits
                    matched.append(pattern.pattern.replace(r"\b", ""))
                if title_hits > 0:
                    # Title bonus: 3x multiplier (on top of body count)
                    score += title_hits * 2  # 2 extra (total 3x)

            # Weighted keywords (multi-word, domain-specific)
            for pattern in self._weighted_patterns[domain_key]:
                body_hits = len(pattern.findall(combined_text))
                title_hits = len(pattern.findall(title_lower))
                if body_hits > 0:
                    score += body_hits * 2  # 2x weight
                    matched.append(pattern.pattern.replace(r"\b", ""))
                if title_hits > 0:
                    score += title_hits * 4  # 2x weight * 3x title = 6x total, +4 extra

            scores[domain_key] = score
            matches_map[domain_key] = matched

        # Normalize scores
        max_score = max(scores.values()) if scores else 0.0
        if max_score > 0:
            normalized = {k: v / max_score for k, v in scores.items()}
        else:
            normalized = {k: 0.0 for k in scores}

        # Find best domain
        best_domain = max(normalized, key=lambda k: normalized[k])
        best_confidence = normalized[best_domain]

        # Apply diminishing returns: if too few total matches, cap confidence
        total_matches = len(matches_map.get(best_domain, []))
        if total_matches <= 1:
            best_confidence = min(best_confidence, 0.4)
        elif total_matches <= 2:
            best_confidence = min(best_confidence, 0.6)

        # Handle zero-match case
        if max_score == 0:
            return DomainResult(
                domain="unknown",
                display_name="Unknown",
                display_name_ko="미분류",
                agent_name="",
                confidence=0.0,
                method="keyword",
                needs_confirmation=True,
                keyword_matches=[],
                all_scores=normalized,
                reasoning="No domain keywords matched.",
            )

        spec = DOMAINS[best_domain]
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
    # Step 2: Semantic classification via Gemini
    # ------------------------------------------------------------------

    async def _semantic_classify(
        self,
        title: str,
        abstract: str,
        keyword_result: DomainResult,
    ) -> DomainResult:
        """
        Use Gemini Flash for semantic domain classification.
        Falls back to keyword result if Gemini is unavailable.
        """
        if self._gemini is None:
            logger.warning(
                "GeminiClient not available for semantic classification. "
                "Returning keyword result with needs_confirmation=True."
            )
            keyword_result.needs_confirmation = True
            keyword_result.reasoning += " (Semantic fallback unavailable.)"
            return keyword_result

        try:
            semantic = await self._gemini.classify_domain(title, abstract)
        except Exception as exc:
            logger.error("Semantic classification failed: %s", exc)
            keyword_result.needs_confirmation = True
            keyword_result.reasoning += f" (Semantic fallback failed: {exc})"
            return keyword_result

        semantic_domain = semantic.get("domain", "unknown")
        semantic_confidence = float(semantic.get("confidence", 0.0))
        semantic_reasoning = semantic.get("reasoning", "")

        logger.info(
            "Semantic classification: domain=%s confidence=%.3f reasoning=%s",
            semantic_domain,
            semantic_confidence,
            semantic_reasoning,
        )

        # Step 3: Determine final result
        # If semantic agrees with keyword, boost confidence
        if semantic_domain == keyword_result.domain:
            combined_confidence = min(
                1.0,
                (keyword_result.confidence + semantic_confidence) / 2 + 0.15,
            )
            spec = DOMAINS.get(semantic_domain)
            if spec is None:
                return self._make_unknown_result(
                    keyword_result, semantic_reasoning
                )
            return DomainResult(
                domain=semantic_domain,
                display_name=spec.display_name,
                display_name_ko=spec.display_name_ko,
                agent_name=spec.agent_name,
                confidence=round(combined_confidence, 3),
                method="semantic",
                needs_confirmation=False,
                keyword_matches=keyword_result.keyword_matches,
                all_scores=keyword_result.all_scores,
                reasoning=(
                    f"Keyword and semantic agree on '{semantic_domain}'. "
                    f"Semantic reasoning: {semantic_reasoning}"
                ),
            )

        # If semantic disagrees, use the one with higher confidence
        if semantic_confidence > keyword_result.confidence and semantic_domain in DOMAINS:
            spec = DOMAINS[semantic_domain]
            # Lower confidence when methods disagree
            adjusted = semantic_confidence * 0.85
            needs_confirm = adjusted < self.CONFIDENCE_THRESHOLD
            return DomainResult(
                domain=semantic_domain,
                display_name=spec.display_name,
                display_name_ko=spec.display_name_ko,
                agent_name=spec.agent_name,
                confidence=round(adjusted, 3),
                method="semantic",
                needs_confirmation=needs_confirm,
                keyword_matches=keyword_result.keyword_matches,
                all_scores=keyword_result.all_scores,
                reasoning=(
                    f"Semantic ({semantic_domain}, {semantic_confidence:.2f}) "
                    f"overrides keyword ({keyword_result.domain}, "
                    f"{keyword_result.confidence:.2f}). "
                    f"Semantic reasoning: {semantic_reasoning}"
                ),
            )

        # Neither method is confident enough
        if keyword_result.domain != "unknown" and keyword_result.confidence > 0:
            keyword_result.needs_confirmation = True
            keyword_result.reasoning = (
                f"Methods disagree: keyword={keyword_result.domain} "
                f"({keyword_result.confidence:.2f}), "
                f"semantic={semantic_domain} ({semantic_confidence:.2f}). "
                f"Semantic reasoning: {semantic_reasoning}. "
                "User confirmation recommended."
            )
            return keyword_result

        return self._make_unknown_result(keyword_result, semantic_reasoning)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_unknown_result(
        self,
        keyword_result: DomainResult,
        semantic_reasoning: str,
    ) -> DomainResult:
        """Create an unknown/unconfirmed result."""
        return DomainResult(
            domain="unknown",
            display_name="Unknown",
            display_name_ko="미분류",
            agent_name="",
            confidence=0.0,
            method="semantic",
            needs_confirmation=True,
            keyword_matches=keyword_result.keyword_matches,
            all_scores=keyword_result.all_scores,
            reasoning=f"Could not determine domain. {semantic_reasoning}",
        )

    @staticmethod
    def get_available_domains() -> list[dict]:
        """Return list of all available domains with metadata."""
        return [
            {
                "key": spec.name,
                "display_name": spec.display_name,
                "display_name_ko": spec.display_name_ko,
                "agent_name": spec.agent_name,
                "keyword_count": len(spec.keywords) + len(spec.weighted_keywords),
            }
            for spec in DOMAINS.values()
        ]

    @staticmethod
    def get_agent_for_domain(domain: str) -> Optional[str]:
        """Return agent name for a given domain, or None if unknown."""
        spec = DOMAINS.get(domain)
        return spec.agent_name if spec else None
