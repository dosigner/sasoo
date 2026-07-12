from __future__ import annotations

import unittest

from services.agents.md_loader import AgentProfile
from services.domain_router import DomainRouter


def _make_router() -> DomainRouter:
    router = DomainRouter()
    router.load_from_agents([
        AgentProfile(
            agent_name="optics_agent",
            display_name="Optics",
            display_name_ko="광학",
            domain="optics",
            domain_display="Optics",
            domain_display_ko="광학",
            keywords=["metasurface", "photonics"],
            weighted_keywords=["diffractive optical element"],
        ),
        AgentProfile(
            agent_name="bio_agent",
            display_name="Biology",
            display_name_ko="생물학",
            domain="biology",
            domain_display="Biology",
            domain_display_ko="생물학",
            keywords=["cell", "protein"],
            weighted_keywords=["crispr"],
        ),
    ])
    return router


class DomainRouterConstructorTests(unittest.TestCase):
    def test_constructor_takes_no_gemini_client_argument(self) -> None:
        # Confirmed decision: gemini_client param removed entirely.
        router = DomainRouter()
        self.assertEqual(router.get_available_domains(), [])
        with self.assertRaises(TypeError):
            DomainRouter(gemini_client=object())  # type: ignore[call-arg]


class DomainRouterKeywordClassifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_high_confidence_unambiguous_match_skips_semantic_path(self) -> None:
        router = _make_router()
        result = await router.classify(
            title="A metasurface-based diffractive optical element for photonics",
            abstract="We study metasurface photonics using a diffractive optical element design.",
        )
        self.assertEqual(result.domain, "optics")
        self.assertEqual(result.method, "keyword")
        self.assertFalse(result.needs_confirmation)


class DomainRouterSemanticFallbackRemovedTests(unittest.IsolatedAsyncioTestCase):
    async def test_low_confidence_keyword_match_always_needs_confirmation(self) -> None:
        router = _make_router()
        # Only weak signal, no strong keyword hits -> low confidence path.
        result = await router.classify(
            title="A general research paper",
            abstract="This paper touches on cell biology only in passing.",
        )
        self.assertTrue(result.needs_confirmation)
        self.assertIn("No semantic fallback", result.reasoning)

    async def test_ambiguous_top_two_scores_always_needs_confirmation(self) -> None:
        router = _make_router()
        # Both domains score a tied 1.0 (gap=0 < AMBIGUITY_GAP), so despite
        # confidence >= CONFIDENCE_THRESHOLD, classify() routes through the
        # (now fallback-free) _semantic_classify path.
        result = await router.classify(
            title="metasurface photonics diffractive optical element cell protein crispr",
            abstract=(
                "metasurface photonics diffractive optical element "
                "cell protein crispr"
            ),
        )
        self.assertEqual(result.all_scores.get("optics"), result.all_scores.get("biology"))
        self.assertTrue(result.needs_confirmation)
        self.assertIn("No semantic fallback", result.reasoning)

    async def test_no_domains_loaded_needs_confirmation_without_gemini(self) -> None:
        router = DomainRouter()
        result = await router.classify(title="Anything", abstract="Anything")
        self.assertEqual(result.domain, "unknown")
        self.assertTrue(result.needs_confirmation)

    async def test_semantic_classify_never_calls_out_and_always_confirms(self) -> None:
        router = _make_router()
        keyword_result = router._keyword_classify(
            title="ambiguous text with no strong domain signal",
            abstract="ambiguous text with no strong domain signal",
        )
        result = await router._semantic_classify(
            "ambiguous text with no strong domain signal",
            "ambiguous text with no strong domain signal",
            keyword_result,
        )
        self.assertTrue(result.needs_confirmation)
        self.assertIs(result, keyword_result)


class DomainRouterOverrideTests(unittest.TestCase):
    def test_override_returns_manual_result(self) -> None:
        router = _make_router()
        result = router.override("biology")
        self.assertEqual(result.domain, "biology")
        self.assertEqual(result.method, "manual")
        self.assertFalse(result.needs_confirmation)

    def test_override_unknown_domain_raises(self) -> None:
        router = _make_router()
        with self.assertRaises(ValueError):
            router.override("nonexistent")


if __name__ == "__main__":
    unittest.main()
