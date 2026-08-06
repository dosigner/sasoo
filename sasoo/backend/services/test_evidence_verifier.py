"""services.evidence_verifier 테스트.

가장 중요한 것은 "위조 인용 false-verify = 0"이다. 설계 스파이크 실측에서 숫자 한 자리를
바꾼 위조본이 부분일치 임계 0.6에서 81.1%, 0.8에서도 52.0% 통과했고, 정규화 완전일치는
0.0%만 통과했다. 그 0을 회귀 게이트로 고정한다.
"""

import unittest

from services import evidence_verifier as ev


class NormalizerV1Tests(unittest.TestCase):
    def test_collapses_whitespace_and_casefolds(self):
        self.assertEqual(ev.normalize_text("The   SAMPLES\n were\tannealed "), "the samples were annealed")

    def test_joins_line_break_hyphen(self):
        text = "We used a wave-\nlength of 1550 nm"
        self.assertEqual(ev.normalize_text(text), "we used a wavelength of 1550 nm")

    def test_removes_soft_hyphen_and_zero_width(self):
        self.assertEqual(ev.normalize_text("wave­length​ test"), "wavelength test")

    def test_nfkc_expands_ligature_and_fullwidth(self):
        self.assertEqual(ev.normalize_text("ﬁber"), "fiber")
        self.assertEqual(ev.normalize_text("１５５０ ｎｍ"), "1550 nm")

    def test_unifies_dashes_and_smart_quotes(self):
        self.assertEqual(ev.normalize_text("1550–1560"), "1550-1560")
        self.assertEqual(ev.normalize_text("“quoted” ‘x’"), '"quoted" \'x\'')

    def test_does_not_alter_digits_or_scientific_symbols(self):
        # μ와 u, ×와 x를 서로 바꾸지 않는다 — 바꾸면 수치 의미가 사라진다
        normalized = ev.normalize_text("3.2 μm × 10")
        self.assertIn("μm", normalized)
        self.assertIn("×", normalized)
        self.assertNotIn("um", normalized)

    def test_source_map_recovers_original_span(self):
        raw = "We used a wave-\nlength of 1550 nm in the setup."
        normalized, source_map = ev.normalize_with_map(raw)
        needle = ev.normalize_text("a wavelength of 1550 nm")
        start = normalized.find(needle)
        self.assertGreaterEqual(start, 0)
        raw_start = source_map[start]
        raw_end = source_map[start + len(needle) - 1] + 1
        self.assertEqual(raw[raw_start:raw_end], "a wave-\nlength of 1550 nm")

    def test_map_length_matches_normalized_length(self):
        normalized, source_map = ev.normalize_with_map("  A­ B-\ncd  ")
        self.assertEqual(len(normalized), len(source_map))


class ForgedQuoteGateTests(unittest.TestCase):
    """숫자를 변조한 인용은 정규화 완전일치를 통과하지 못한다 (false verify = 0)."""

    CORPUS = (
        "The samples were annealed at 500 °C for 2 h. "
        "A wavelength of 1550 nm was used with 3.2 mW average power. "
        "The beam diameter was 12.5 mm at the aperture."
    )
    HONEST = [
        "The samples were annealed at 500 °C for 2 h.",
        "A wavelength of 1550 nm was used with 3.2 mW average power.",
        "The beam diameter was 12.5 mm at the aperture.",
    ]
    FORGED = [
        "The samples were annealed at 900 °C for 2 h.",
        "A wavelength of 1560 nm was used with 3.2 mW average power.",
        "The beam diameter was 12.8 mm at the aperture.",
    ]

    def test_honest_quotes_all_match_normalized(self):
        corpus = ev.normalize_text(self.CORPUS)
        for quote in self.HONEST:
            self.assertIn(ev.normalize_text(quote), corpus, quote)

    def test_forged_quotes_never_match_normalized(self):
        corpus = ev.normalize_text(self.CORPUS)
        for quote in self.FORGED:
            self.assertNotIn(ev.normalize_text(quote), corpus, quote)


class TargetKeyTests(unittest.TestCase):
    def test_target_key_is_index_prefixed_slug(self):
        self.assertEqual(ev.build_target_key(0, "Annealing Temperature"), "p000:annealing-temperature")
        self.assertEqual(ev.build_target_key(12, "laser_power (mW)"), "p012:laser-power-mw")

    def test_slug_keeps_hangul_and_falls_back_when_empty(self):
        self.assertEqual(ev.slugify_target("파장"), "파장")
        self.assertEqual(ev.slugify_target("  ***  "), "unnamed")

    def test_slug_is_truncated_to_48_chars(self):
        self.assertEqual(len(ev.slugify_target("a" * 200)), 48)


class DisplayStatusTests(unittest.TestCase):
    def test_verified_requires_all_three_fields(self):
        self.assertEqual(ev.derive_display_status("verified_exact", "match", "value_in_quote"), "VERIFIED")
        self.assertEqual(ev.derive_display_status("verified_normalized", "derived", "value_in_quote"), "VERIFIED")

    def test_page_mismatch_is_not_verified(self):
        self.assertEqual(
            ev.derive_display_status("verified_exact", "mismatch", "value_in_quote"),
            "UNVERIFIED_PAGE_MISMATCH",
        )

    def test_value_missing_is_not_verified(self):
        self.assertEqual(
            ev.derive_display_status("verified_exact", "match", "value_missing"),
            "UNVERIFIED_VALUE_MISMATCH",
        )

    def test_inferred_is_never_verified(self):
        self.assertEqual(
            ev.derive_display_status("verified_exact", "match", "inferred"), "UNVERIFIED_INFERRED"
        )

    def test_partial_match_is_never_verified(self):
        self.assertEqual(
            ev.derive_display_status("partial_match", "match", "value_in_quote"), "UNVERIFIED_PARTIAL"
        )

    def test_every_quote_status_maps_to_a_known_display_status(self):
        allowed = {
            "VERIFIED", "UNVERIFIED_PAGE_MISMATCH", "UNVERIFIED_VALUE_MISMATCH",
            "UNVERIFIED_INFERRED", "UNVERIFIED_PARTIAL", "UNVERIFIED_AMBIGUOUS",
            "UNVERIFIED_NOT_FOUND", "UNVERIFIED_NO_QUOTE", "UNVERIFIED_NO_TEXT_LAYER",
            "UNVERIFIED_STALE_SOURCE", "UNVERIFIED_ERROR",
        }
        for quote_status in ev.QUOTE_STATUSES:
            for page_status in ev.PAGE_STATUSES:
                for value_status in ev.VALUE_STATUSES:
                    self.assertIn(
                        ev.derive_display_status(quote_status, page_status, value_status), allowed
                    )

    def test_unknown_quote_status_never_promotes(self):
        self.assertEqual(ev.derive_display_status("who_knows", "match", "value_in_quote"), "UNVERIFIED_ERROR")


class ValueGuardTests(unittest.TestCase):
    def test_numeric_value_must_appear_in_quote(self):
        self.assertEqual(
            ev.check_value_in_quote("500", "explicit", "annealed at 500 °C for 2 h")[0],
            "value_in_quote",
        )
        status, detail = ev.check_value_in_quote("900", "explicit", "annealed at 500 °C for 2 h")
        self.assertEqual(status, "value_missing")
        self.assertIsNotNone(detail)

    def test_non_numeric_value_falls_back_to_literal(self):
        self.assertEqual(
            ev.check_value_in_quote("nitrogen", "explicit", "under a Nitrogen atmosphere")[0],
            "value_in_quote",
        )
        self.assertEqual(
            ev.check_value_in_quote("argon", "explicit", "under a Nitrogen atmosphere")[0],
            "value_missing",
        )

    def test_inferred_is_structurally_unverifiable(self):
        self.assertEqual(ev.check_value_in_quote("500", "inferred", "annealed at 500 °C")[0], "inferred")

    def test_empty_value_is_not_applicable(self):
        self.assertEqual(ev.check_value_in_quote("", "explicit", "any text")[0], "not_applicable")

    def test_missing_match_means_value_missing(self):
        self.assertEqual(ev.check_value_in_quote("500", "explicit", None)[0], "value_missing")

    def test_multi_number_value_requires_every_number(self):
        self.assertEqual(
            ev.check_value_in_quote("1550-1560", "explicit", "from 1550 to 1560 nm")[0], "value_in_quote"
        )
        self.assertEqual(
            ev.check_value_in_quote("1550-1570", "explicit", "from 1550 to 1560 nm")[0], "value_missing"
        )


if __name__ == "__main__":
    unittest.main()
