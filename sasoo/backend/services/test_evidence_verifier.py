"""services.evidence_verifier 테스트.

가장 중요한 것은 "위조 인용 false-verify = 0"이다. 설계 스파이크 실측에서 숫자 한 자리를
바꾼 위조본이 부분일치 임계 0.6에서 81.1%, 0.8에서도 52.0% 통과했고, 정규화 완전일치는
0.0%만 통과했다. 그 0을 회귀 게이트로 고정한다.
"""

import json
import os
import tempfile
import unicodedata
import unittest

import fitz

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

    def test_nfc_and_nfd_forms_normalize_identically(self):
        # 리뷰 지적: 문자 단위 NFKC는 결합 문자 시퀀스(NFD)를 재합성하지 못해, 같은
        # 실제 텍스트가 유니코드 표현 형태만 달라도 정규화 결과가 갈린다(false negative).
        nfc = unicodedata.normalize("NFC", "café résumé naïve")
        nfd = unicodedata.normalize("NFD", "café résumé naïve")
        self.assertNotEqual(nfc, nfd, "sanity: 입력 자체가 코드포인트 단위로 달라야 한다")
        self.assertEqual(ev.normalize_text(nfc), ev.normalize_text(nfd))


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

    def test_value_mismatch_wins_over_page_mismatch(self):
        # 리뷰 지적 I-1: quote는 축자 존재해도 값이 그 안에 없고 페이지도 틀렸으면,
        # "다른 페이지에서 확인"(경고)이 아니라 "이 인용은 이 값을 뒷받침하지 않는다"
        # (위험)가 진실이어야 한다. 값 가드가 페이지 검사를 이겨야 한다.
        self.assertEqual(
            ev.derive_display_status("verified_exact", "mismatch", "value_missing"),
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

    def test_short_number_is_not_matched_as_substring_of_longer_number(self):
        # 리뷰 지적(Critical #1, 실증): "50"이 "1550"의 부분문자열이라는 이유만으로
        # value_in_quote가 나오면 안 된다 — false verify.
        status, detail = ev.check_value_in_quote(
            "50", "explicit", "A wavelength of 1550 nm was used."
        )
        self.assertEqual(status, "value_missing")
        self.assertIsNotNone(detail)

    def test_negative_value_requires_sign_present_in_quote(self):
        # 리뷰 지적(Critical #2, 실증): "-40"의 부호가 추출 단계에서 소실되면 안 된다.
        # quote에 부호 없는 "40"만 있으면 값이 다른 것이므로 value_missing이어야 한다.
        status, detail = ev.check_value_in_quote(
            "-40", "explicit", "The device was tested at 40 degrees."
        )
        self.assertEqual(status, "value_missing")
        self.assertIsNotNone(detail)

    def test_negative_value_matches_when_sign_present_in_quote(self):
        # 위 회귀의 반대 방향 확인: 부호가 quote에도 실제로 있으면 정상적으로 일치해야 한다.
        self.assertEqual(
            ev.check_value_in_quote("-40", "explicit", "The device was tested at -40 degrees.")[0],
            "value_in_quote",
        )


class NormalizerDashConsistencyTests(unittest.TestCase):
    """위첨자 마이너스와 일반 마이너스가 같은 글자로 접혀야 한다.

    NFKC는 U+207B(위첨자 -)를 U+2212(minus sign)로 펼치는데, 대시 폴딩이 그보다 먼저
    끝나서 "10⁻³"는 U+2212로, "10−3"은 ASCII "-"로 갈렸다. 같은 뜻이 두 글자로 남으면
    값 가드뿐 아니라 정규화 인용 매칭도 어긋난다.
    """

    def test_superscript_and_plain_minus_normalize_alike(self):
        forms = ["4.5 × 10⁻³", "4.5 × 10−3", "4.5 × 10-3"]
        normalized = {ev.normalize_text(form) for form in forms}
        self.assertEqual(len(normalized), 1, normalized)
        self.assertNotIn("\u2212", normalized.pop())

    def test_offset_map_stays_aligned_after_dash_folding(self):
        # 대시 폴딩은 1:1 치환이라 오프셋 맵 길이가 흔들리면 안 된다 — 흔들리면 bbox가 밀린다.
        text = "a BER of 4.5 × 10⁻³ here"
        normalized, mapping = ev.normalize_with_map(text)
        self.assertEqual(len(normalized), len(mapping))
        self.assertTrue(all(0 <= index < len(text) for index in mapping))


class ScientificNotationValueGuardTests(unittest.TestCase):
    """값 가드는 표기가 아니라 수를 본다. 단, 허용 범위는 정확히 같은 수뿐이다."""

    def test_decimal_value_matches_scientific_notation_in_quote(self):
        # 첫 실측에서 나온 실제 사례: pre_fec_ber_threshold=0.0045인데 원문은
        # "FEC-correctable BER of 4.5 × 10⁻³"라 인용·페이지가 맞는데도 미검증이 됐다.
        self.assertEqual(
            ev.check_value_in_quote("0.0045", "explicit", "a FEC-correctable BER of 4.5 × 10⁻³")[0],
            "value_in_quote",
        )

    def test_scientific_value_matches_decimal_quote(self):
        self.assertEqual(
            ev.check_value_in_quote("4.5e-3", "explicit", "a BER of 0.0045 was measured")[0],
            "value_in_quote",
        )

    def test_notation_variants_all_match(self):
        for quote in [
            "the BER of 4.5 × 10⁻³ was",
            "the BER of 4.5 x 10^-3 was",
            "the BER of 4.5·10⁻³ was",
            "the BER of 4.5e-3 was",
            "the BER of 4.5E-3 was",
        ]:
            with self.subTest(quote=quote):
                self.assertEqual(
                    ev.check_value_in_quote("0.0045", "explicit", quote)[0], "value_in_quote"
                )

    def test_digit_forgery_still_fails_across_notations(self):
        # 표기 동치를 허용해도 수가 다르면 통과하면 안 된다. 오차 허용은 없다.
        for value in ["0.0046", "4.6e-3", "0.045", "4.5e-4"]:
            with self.subTest(value=value):
                status, detail = ev.check_value_in_quote(value, "explicit", "a BER of 4.5 × 10⁻³")
                self.assertEqual(status, "value_missing")
                self.assertIsNotNone(detail)

    def test_exponent_parts_are_not_matchable_on_their_own(self):
        # "4.5 × 10⁻³"의 10과 3은 독립된 수가 아니다. 값 "10"이 여기 걸리면 원문이
        # 뒷받침하지 않는 파라미터가 검증으로 올라간다.
        for value in ["10", "3", "-3"]:
            with self.subTest(value=value):
                self.assertEqual(
                    ev.check_value_in_quote(value, "explicit", "a BER of 4.5 × 10⁻³")[0],
                    "value_missing",
                )

    def test_trailing_zero_is_the_same_number(self):
        self.assertEqual(
            ev.check_value_in_quote("500", "explicit", "annealed at 500.0 °C")[0], "value_in_quote"
        )

    def test_unsigned_value_does_not_match_negative_quote(self):
        # 옛 경계 검사는 "-40" 안의 "40"에 걸려 통과했다. 부호가 다르면 다른 값이다.
        status, detail = ev.check_value_in_quote("40", "explicit", "tested at -40 degrees")
        self.assertEqual(status, "value_missing")
        self.assertIsNotNone(detail)

    def test_grouped_thousands_are_one_number(self):
        self.assertEqual(
            ev.check_value_in_quote("1000", "explicit", "a pulse energy of 1,000 nJ")[0],
            "value_in_quote",
        )
        # 자릿수 구분 쉼표를 모르면 "1,000"에서 "1"만 떼어 매치된다 — false verify다.
        self.assertEqual(
            ev.check_value_in_quote("1", "explicit", "a pulse energy of 1,000 nJ")[0],
            "value_missing",
        )

    def test_figure_and_section_numbers_are_not_decimals(self):
        # "fig.5"의 ".5"를 소수로 읽으면 원문이 뒷받침하지 않는 값이 VERIFIED로 올라간다.
        # 앞자리 숫자 없는 소수 대안을 두면 논문에 흔한 fig./p./sec. 표기가 전부 수가 된다.
        for value, quote in [
            ("0.5", "as shown in fig.5 the device works"),
            ("0.45", "see p.45 for the full derivation"),
            ("0.12", "the sample was placed in the chamber.12"),
            ("0.3", "described in sec.3 of the supplement"),
        ]:
            with self.subTest(quote=quote):
                status, detail = ev.check_value_in_quote(value, "explicit", quote)
                self.assertEqual(status, "value_missing")
                self.assertIsNotNone(detail)

    def test_flattened_superscript_offers_no_number_at_all(self):
        # NFKC가 "10⁻³"를 "10-3"으로 납작하게 만들면 지수인지 범위인지 구분할 수 없다.
        # 뜻을 정할 수 없으면 근거로 내놓지 않는다 — 10과 3을 독립 수로 흘리면 원문이
        # 말하지 않은 값이 검증으로 올라간다.
        for value in ["10", "3", "-3", "0.001"]:
            for quote in ["a BER below 10⁻³ at all times", "a BER below 10-3 at all times"]:
                with self.subTest(value=value, quote=quote):
                    self.assertEqual(
                        ev.check_value_in_quote(value, "explicit", quote)[0], "value_missing"
                    )

    def test_spaced_exponent_is_discarded_not_leaked(self):
        # "4.5 × 10 -3"처럼 지수 앞이 벌어진 표기는 지수로 읽지 않는다. 대신 10과 -3을
        # 남기지도 않는다(fail closed).
        quote = "a BER of 4.5 × 10 -3 was measured"
        for value in ["10", "-3"]:
            with self.subTest(value=value):
                self.assertEqual(ev.check_value_in_quote(value, "explicit", quote)[0], "value_missing")

    def test_multiplier_does_not_swallow_separate_numbers(self):
        # "10 x 10 5"는 배열 치수지 지수가 아니다. 지수 마커가 공백 너머까지 삼키면
        # 진짜 수가 사라지고(5) 있지도 않은 수가 생긴다(1e6).
        quote = "an array of 10 x 10 5 mm cells"
        self.assertEqual(ev.check_value_in_quote("5", "explicit", quote)[0], "value_in_quote")
        self.assertEqual(ev.check_value_in_quote("1000000", "explicit", quote)[0], "value_missing")

    def test_e_marker_requires_no_spacing(self):
        # "1 e 2"는 100이 아니다.
        self.assertEqual(
            ev.check_value_in_quote("100", "explicit", "case 1 e 2 of the table")[0], "value_missing"
        )

    def test_hyphen_range_starting_with_ten_falls_back_to_literal(self):
        # "10-20"은 범위지만 납작해진 "10⁻²⁰"과 글자가 같다. 수로는 읽지 않되,
        # 인용이 같은 표기를 그대로 담고 있으면 리터럴 대조가 받아준다.
        self.assertEqual(
            ev.check_value_in_quote("10-20", "explicit", "a range of 10-20 nm was swept")[0],
            "value_in_quote",
        )
        # 인용이 표기를 바꿔 쓰면 못 잡는다 — 애매한 입력에서는 놓치는 쪽을 택한다.
        self.assertEqual(
            ev.check_value_in_quote("10-20", "explicit", "swept from 10 to 20 nm")[0],
            "value_missing",
        )

    def test_bare_power_of_ten_is_left_alone(self):
        # 가수 없는 "10⁻³"은 범위·식별자와 구분이 안 되므로 지수로 읽지 않는다.
        # 지금은 의도적으로 못 잡는 경계다(실측에서 사례가 나오면 재검토).
        self.assertEqual(
            ev.check_value_in_quote("0.001", "explicit", "a BER below 10⁻³")[0], "value_missing"
        )


class _PdfFixture:
    """검증기 테스트용 합성 PDF. 실제 라이브러리 논문 없이 CI에서 돌아야 한다.

    p1: 축자 인용 1건 + 줄바꿈 하이픈으로 끊긴 인용 1건 + 양 페이지 중복 문장
    p2: 긴 문장(부분일치용) + 값 가드용 문장 + 양 페이지 중복 문장
    """

    P1_EXACT = "The samples were annealed at 500 °C for 2 h."
    P1_HYPHEN_RAW = "We used a wave-\nlength of 1550 nm in the setup."
    P1_HYPHEN_QUOTE = "We used a wavelength of 1550 nm in the setup."
    DUPLICATE = "This sentence appears on both pages of the document."
    P2_LONG = (
        "In this experiment the beam diameter was measured as 12.5 mm "
        "at the output aperture of the telescope."
    )
    P2_PARTIAL_QUOTE = (
        "In this experiment the beam diameter was measured as 12.5 mm "
        "at the entrance aperture of the telescope."
    )
    P2_NITROGEN = "The annealing was performed under a nitrogen atmosphere."

    @classmethod
    def write(cls, path: str) -> None:
        doc = fitz.open()
        page1 = doc.new_page()
        page1.insert_text((50, 100), cls.P1_EXACT, fontsize=10, fontname="helv")
        page1.insert_textbox(fitz.Rect(50, 120, 200, 200), cls.P1_HYPHEN_RAW, fontsize=10, fontname="helv")
        page1.insert_text((50, 220), cls.DUPLICATE, fontsize=10, fontname="helv")
        page2 = doc.new_page()
        page2.insert_text((50, 100), cls.P2_LONG, fontsize=8, fontname="helv")
        page2.insert_text((50, 130), cls.P2_NITROGEN, fontsize=10, fontname="helv")
        page2.insert_text((50, 160), cls.DUPLICATE, fontsize=10, fontname="helv")
        doc.save(path)
        doc.close()

    @staticmethod
    def write_blank(path: str) -> None:
        doc = fitz.open()
        doc.new_page()
        doc.save(path)
        doc.close()


class PdfIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        handle.close()
        cls.pdf_path = handle.name
        _PdfFixture.write(cls.pdf_path)
        cls.index = ev.build_pdf_index(cls.pdf_path)

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.pdf_path)

    def test_index_has_two_pages_with_text(self):
        self.assertEqual(self.index.page_count, 2)
        self.assertTrue(self.index.has_text_layer)
        self.assertIn("annealed at 500", self.index.pages[0].normalized)

    def test_exact_hit_on_claimed_page(self):
        match = ev.find_quote(self.index, _PdfFixture.P1_EXACT, 1)
        self.assertEqual(match.quote_status, "verified_exact")
        self.assertEqual(match.page_status, "match")
        self.assertEqual(match.matched_page, 1)
        self.assertEqual(match.match_method, "exact")

    def test_line_break_hyphen_needs_normalized_match(self):
        match = ev.find_quote(self.index, _PdfFixture.P1_HYPHEN_QUOTE, 1)
        self.assertEqual(match.quote_status, "verified_normalized")
        self.assertEqual(match.page_status, "match")
        self.assertEqual(match.matched_quote, _PdfFixture.P1_HYPHEN_RAW)

    def test_wrong_claimed_page_is_mismatch_not_silent_fix(self):
        match = ev.find_quote(self.index, _PdfFixture.P2_LONG, 1)
        self.assertEqual(match.quote_status, "verified_exact")
        self.assertEqual(match.page_status, "mismatch")
        self.assertEqual(match.matched_page, 2)

    def test_missing_claimed_page_is_derived(self):
        match = ev.find_quote(self.index, _PdfFixture.P2_LONG, None)
        self.assertEqual(match.page_status, "derived")
        self.assertEqual(match.matched_page, 2)

    def test_out_of_range_claimed_page(self):
        match = ev.find_quote(self.index, _PdfFixture.P2_LONG, 99)
        self.assertEqual(match.quote_status, "verified_exact")
        self.assertEqual(match.page_status, "invalid_page")

    def test_duplicate_quote_is_ambiguous(self):
        match = ev.find_quote(self.index, _PdfFixture.DUPLICATE, None)
        self.assertEqual(match.quote_status, "ambiguous")
        self.assertIsNotNone(match.failure_detail)

    def test_empty_quote_is_no_quote(self):
        self.assertEqual(ev.find_quote(self.index, "", 1).quote_status, "no_quote")
        self.assertEqual(ev.find_quote(self.index, "   ", None).quote_status, "no_quote")

    def test_forged_number_is_not_found_not_partial(self):
        match = ev.find_quote(self.index, "The samples were annealed at 900 °C for 2 h.", 1)
        self.assertEqual(match.quote_status, "not_found")

    def test_partial_match_is_reported_but_never_verified(self):
        match = ev.find_quote(self.index, _PdfFixture.P2_PARTIAL_QUOTE, 2)
        self.assertEqual(match.quote_status, "partial_match")
        self.assertGreaterEqual(match.match_ratio or 0.0, 0.6)
        self.assertNotEqual(
            ev.derive_display_status(match.quote_status, match.page_status, "value_in_quote"),
            "VERIFIED",
        )

    def test_bbox_is_lower_left_origin_and_positive_area(self):
        with fitz.open(self.pdf_path) as doc:
            bbox = ev.locate_bbox(doc[0], _PdfFixture.P1_EXACT)
            height = doc[0].rect.height
        self.assertIsNotNone(bbox)
        assert bbox is not None
        self.assertEqual(len(bbox), 4)
        self.assertLess(bbox[0], bbox[2])
        self.assertLess(bbox[1], bbox[3])
        self.assertGreater(bbox[1], height / 2)  # 페이지 상단 텍스트 → 좌하단 원점에서 y가 크다

    def test_bbox_of_unknown_text_is_none(self):
        with fitz.open(self.pdf_path) as doc:
            self.assertIsNone(ev.locate_bbox(doc[0], "no such text in this document at all"))

    def test_bbox_of_wrapped_normalized_match_unions_all_lines(self):
        # P1_HYPHEN_RAW는 좁은 textbox에 들어가 최소 2줄로 줄바꿈된다 — search_for가 줄마다
        # 별도 rect를 반환하므로, 첫 rect(첫 줄)만 쓰면 인용 뒷부분이 bbox 밖으로 잘린다.
        with fitz.open(self.pdf_path) as doc:
            page = doc[0]
            line_rects = page.search_for(_PdfFixture.P1_HYPHEN_RAW)
            bbox = ev.locate_bbox(page, _PdfFixture.P1_HYPHEN_RAW)
        self.assertGreaterEqual(len(line_rects), 2)  # sanity: 실제로 여러 줄로 나뉘었는가
        self.assertIsNotNone(bbox)
        assert bbox is not None
        first_line_height = line_rects[0].y1 - line_rects[0].y0
        self.assertGreater(bbox[3] - bbox[1], first_line_height)  # 첫 줄보다 커야 union이 적용된 것

    def test_bbox_falls_back_to_first_rect_when_union_is_oversized(self):
        # 다단 조판 등에서 같은 검색어가 페이지의 서로 먼 두 지점에 우연히 걸리는 경우를
        # 흉내낸다 — union하면 페이지 절반을 넘는 과대 박스가 되므로 첫 rect로 폴백해야 한다.
        doc = fitz.open()
        page = doc.new_page()
        needle = "Shared column heading text"
        page.insert_text((50, 50), needle, fontsize=10, fontname="helv")
        page.insert_text((50, 750), needle, fontsize=10, fontname="helv")
        rects = page.search_for(needle)
        self.assertEqual(len(rects), 2)
        bbox = ev.locate_bbox(page, needle)
        doc.close()
        self.assertIsNotNone(bbox)
        assert bbox is not None
        first_rect_height = rects[0].y1 - rects[0].y0
        self.assertAlmostEqual(bbox[3] - bbox[1], first_rect_height, delta=0.5)


class RecipeParameterIterationTests(unittest.TestCase):
    def test_index_alignment_matches_frontend_parser_rules(self):
        recipe = {
            "parameters": [
                {"name": "a", "value": "1"},
                "Temperature: 500 C",
                42,                       # 프론트가 건너뛰는 타입 — 백엔드도 건너뛴다
                {"parameter": "b", "val": "2"},
                None,                     # 프론트의 p !== null 가드와 동일
            ]
        }
        parsed = ev.iter_recipe_parameters(recipe)
        self.assertEqual([index for index, _ in parsed], [0, 1, 2])
        self.assertEqual([param["name"] for _, param in parsed], ["a", "Temperature", "b"])
        self.assertEqual(parsed[1][1]["value"], "500 C")
        self.assertEqual(ev.count_recipe_parameters(recipe), 3)

    def test_no_parameters_returns_empty(self):
        self.assertEqual(ev.iter_recipe_parameters({}), [])
        self.assertEqual(ev.iter_recipe_parameters({"parameters": "nope"}), [])


class VerifyRecipeParametersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        handle.close()
        cls.pdf_path = handle.name
        _PdfFixture.write(cls.pdf_path)

        blank = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        blank.close()
        cls.blank_path = blank.name
        _PdfFixture.write_blank(cls.blank_path)

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.pdf_path)
        os.unlink(cls.blank_path)

    def _drafts(self, parameters):
        return ev.verify_recipe_parameters({"parameters": parameters}, self.pdf_path)

    def test_happy_path_is_verified_with_bbox(self):
        drafts = self._drafts([
            {"name": "annealing_temperature", "value": "500", "unit": "°C",
             "source_tag": "explicit", "evidence_quote": _PdfFixture.P1_EXACT, "evidence_page": 1},
        ])
        draft = drafts[0]
        self.assertEqual(draft.display_status, "VERIFIED")
        self.assertEqual(draft.quote_status, "verified_exact")
        self.assertEqual(draft.value_status, "value_in_quote")
        self.assertEqual(draft.target_key, "p000:annealing-temperature")
        self.assertEqual(draft.target_label, "annealing_temperature")
        self.assertEqual(draft.corpus, "pdf_text")
        self.assertIsNotNone(draft.bbox_json)
        self.assertEqual(len(json.loads(draft.bbox_json)), 4)

    def test_value_not_in_quote_blocks_verification(self):
        drafts = self._drafts([
            {"name": "annealing_temperature", "value": "900", "unit": "°C",
             "source_tag": "explicit", "evidence_quote": _PdfFixture.P1_EXACT, "evidence_page": 1},
        ])
        self.assertEqual(drafts[0].quote_status, "verified_exact")
        self.assertEqual(drafts[0].value_status, "value_missing")
        self.assertEqual(drafts[0].display_status, "UNVERIFIED_VALUE_MISMATCH")

    def test_inferred_parameter_is_never_verified(self):
        drafts = self._drafts([
            {"name": "power_density", "value": "500", "source_tag": "inferred",
             "evidence_quote": _PdfFixture.P1_EXACT, "evidence_page": 1},
        ])
        self.assertEqual(drafts[0].display_status, "UNVERIFIED_INFERRED")
        self.assertEqual(drafts[0].matched_page, 1)  # 계산 근거 위치는 그래도 제공한다

    def test_missing_quote_is_no_quote(self):
        drafts = self._drafts([{"name": "x", "value": "1", "source_tag": "explicit"}])
        self.assertEqual(drafts[0].display_status, "UNVERIFIED_NO_QUOTE")

    def test_forged_quotes_produce_zero_false_verify(self):
        # value는 forged 인용에 맞춘 임의 상수("1" 등)가 아니라 원본의 실제 값을 유지한다
        # — 값 가드가 quote 레이어의 false-verify를 가리면 이 게이트가 공허하게 통과한다
        # (리뷰 지적 I-5). 판정도 display_status가 아니라 quote_status로 본다 — 스펙 §C의
        # 불변식은 quote 레이어다.
        forged = [
            ("500", "The samples were annealed at 900 °C for 2 h."),
            ("1550", "We used a wavelength of 1560 nm in the setup."),
            (
                "12.5",
                "In this experiment the beam diameter was measured as 12.8 mm "
                "at the output aperture of the telescope.",
            ),
        ]
        drafts = self._drafts([
            {"name": f"p{i}", "value": value, "source_tag": "explicit", "evidence_quote": quote,
             "evidence_page": 1}
            for i, (value, quote) in enumerate(forged)
        ])
        self.assertEqual(
            [d.quote_status for d in drafts if d.quote_status in {"verified_exact", "verified_normalized"}],
            [],
        )

    def test_scanned_pdf_without_text_layer(self):
        drafts = ev.verify_recipe_parameters(
            {"parameters": [{"name": "x", "value": "1", "source_tag": "explicit",
                             "evidence_quote": "anything", "evidence_page": 1}]},
            self.blank_path,
        )
        self.assertEqual(drafts[0].quote_status, "no_text_layer")
        self.assertEqual(drafts[0].display_status, "UNVERIFIED_NO_TEXT_LAYER")

    def test_missing_pdf_still_produces_one_draft_per_parameter(self):
        drafts = ev.verify_recipe_parameters(
            {"parameters": [{"name": "x", "value": "1"}, {"name": "y", "value": "2"}]},
            "/tmp/definitely-not-a-real-file-8f2a.pdf",
        )
        self.assertEqual(len(drafts), 2)
        self.assertEqual({d.failure_detail for d in drafts}, {"pdf_missing"})
        self.assertEqual({d.display_status for d in drafts}, {"UNVERIFIED_NO_TEXT_LAYER"})

    def test_every_parameter_gets_exactly_one_draft(self):
        parameters = [
            {"name": "a", "value": "500", "source_tag": "explicit",
             "evidence_quote": _PdfFixture.P1_EXACT, "evidence_page": 1},
            "Temperature: 500 C",
            {"name": "c", "value": "1", "source_tag": "explicit",
             "evidence_quote": "x", "evidence_page": "not-a-number"},
        ]
        drafts = self._drafts(parameters)
        self.assertEqual(len(drafts), 3)
        self.assertEqual([d.target_index for d in drafts], [0, 1, 2])
        self.assertTrue(all(d.verifier_version == ev.EVIDENCE_VERIFIER_VERSION for d in drafts))
        self.assertTrue(all(d.quote_status in ev.QUOTE_STATUSES for d in drafts))


if __name__ == "__main__":
    unittest.main()
