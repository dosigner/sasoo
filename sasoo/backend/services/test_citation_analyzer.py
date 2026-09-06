import unittest

from services.citation_analyzer import (
    _extract_citation_numbers,
    _extract_first_surname,
    count_citations_numbered,
    parse_references,
)
from services.citation_analyzer import (
    CitationAnalysisResult,
    CitationContext,
    CitationEntry,
    ParsedReference,
)


class CitationAnalyzerParsingTests(unittest.TestCase):
    def test_parse_references_handles_initial_based_author_prefix(self):
        refs = parse_references(
            """
1. R. K. Tyson, Introduction to Adaptive Optics, 2nd ed. (SPIE Press, Bellingham, 2000).
2. M. J. Booth, Adaptive optical microscopy: the ongoing quest for a perfect image, Light: Science & Applications 3, e165 (2014).
3. A. Roorda and D. R. Williams, "The arrangement of the three cone classes in the living human eye," Nature 397, 520-522 (1999).
            """.strip()
        )

        self.assertEqual(refs[0].authors, "R. K. Tyson")
        self.assertIn("Introduction to Adaptive Optics", refs[0].title)
        self.assertEqual(refs[1].authors, "M. J. Booth")
        self.assertIn("Adaptive optical microscopy", refs[1].title)

    def test_parse_references_handles_surname_first_author_lists(self):
        refs = parse_references(
            """
1. Ragazzoni, R., Marchetti, E. & Rigaut, F. Modal tomography for adaptive optics. Astron. Astrophys. 342, L53-L56 (1999).
2. Ragazzoni, R., Marchetti, E. & Valente, G. Adaptive-optics corrections available for the whole sky. Nature 403, 54-56 (2000).
3. Vincent Deo, et al, The CACAO real-time computer for adaptive optics: updates, performance, and development plans, Proc. SPIE 13097 (2024).
            """.strip()
        )

        self.assertIn("Ragazzoni", refs[0].authors)
        self.assertEqual(refs[0].title, "Modal tomography for adaptive optics")
        self.assertIn("Valente", refs[1].authors)
        self.assertIn("Adaptive-optics corrections available for the whole sky", refs[1].title)


class FirstSurnameTests(unittest.TestCase):
    """저자 표기에서 성을 뽑는 규칙.

    옛 구현은 맨 앞 대문자 단어를 성으로 봐서, arXiv에서 표준인 이름 먼저 형식
    (`Niket Agarwal`)에서 이름을 돌려줬다. 본문은 `Agarwal et al.`로 인용하므로
    author-year 카운트가 통째로 0이 됐다(실측: GR00T N1이 참고문헌 102개에 인용 3회).
    """

    def test_surname_is_extracted_from_every_common_author_format(self):
        cases = [
            ("Smith A, Jones B", "Smith"),                              # 성 + 이니셜
            ("Smith, A. and Jones, B.", "Smith"),                       # 성, 이니셜
            ("A. Smith et al.", "Smith"),                               # 이니셜이 먼저
            ("Niket Agarwal, Arslan Ali, Maciej Bala", "Agarwal"),      # 이름이 먼저
            ("Michael S Albergo and Eric Vanden-Eijnden", "Albergo"),   # 중간 이니셜
            ("Dario Amodei, Danny Hernandez", "Amodei"),
            ("", ""),
        ]
        for authors, expected in cases:
            with self.subTest(authors=authors):
                self.assertEqual(_extract_first_surname(authors), expected)

    def test_given_name_is_never_returned_as_the_surname(self):
        """회귀 방지의 핵심 단언 — 이 자리가 깨지면 author-year 논문이 통째로 0회가 된다."""
        self.assertNotEqual(_extract_first_surname("Niket Agarwal"), "Niket")


class SuperscriptCitationTests(unittest.TestCase):
    """위첨자 인용(Nature/Scientific Reports 계열).

    PDF 텍스트 추출에서 위첨자라는 정보가 사라져 `reciprocity23`처럼 단어 끝에 숫자가
    붙는다. 실측: 2022_SciRep은 본문의 대괄호 인용이 0개여서 인용 합계가 0이었다.
    """

    def test_superscript_citations_are_counted_when_enabled(self):
        for sentence, expected in [
            ("Due to atmospheric reciprocity23, the tip/tilt loop", {23}),
            ("performance monitoring interval26.", {26}),          # 문장 끝 마침표
            ("as reported previously22,23 in this work", {22, 23}),  # 묶음 인용
        ]:
            with self.subTest(sentence=sentence):
                self.assertEqual(
                    _extract_citation_numbers(sentence, 40, superscript=True), expected
                )

    def test_variables_and_cross_references_are_not_counted(self):
        """오탐을 막는 것이 이 갈래의 전부다 — 본문에는 숫자가 붙은 토큰이 널려 있다."""
        for sentence in [
            "a beam of waist radius w0 = 1.14 mm",       # 변수
            "expanded by a15 Galilean beam expander",     # 1글자 접두
            "upper bound Cn2 of 5 x 10-14 m-2/3",         # 수식과 단위
            "as shown in Table1 and Fig2",                # 상호참조
            "see version1.2 of the spec",                 # 버전 번호
        ]:
            with self.subTest(sentence=sentence):
                self.assertEqual(
                    _extract_citation_numbers(sentence, 40, superscript=True), set()
                )

    def test_superscript_is_off_by_default(self):
        """기본값이 꺼짐이어야 기존 호출자의 동작이 그대로다."""
        self.assertEqual(_extract_citation_numbers("reciprocity23, the loop", 40), set())

    def test_bracket_citations_still_work_with_superscript_on(self):
        self.assertEqual(
            _extract_citation_numbers("as shown [3,5-7]", 40, superscript=True), {3, 5, 6, 7}
        )


class SuperscriptFallbackGateTests(unittest.TestCase):
    """폴백을 켤지는 문서 전체를 보고 정한다. 문장 단위로는 알 수 없다."""

    REFS = [ParsedReference(ref_num=n, ref_id=f"[{n}]", authors="X Y") for n in (1, 2, 3)]

    def _count(self, body: str) -> dict[int, int]:
        return {e.ref.ref_num: e.cite_count for e in count_citations_numbered(body, self.REFS)}

    def test_superscript_is_used_when_the_paper_has_no_bracket_citations(self):
        body = "We measured the angle-of-arrival error signal by atmospheric reciprocity2. " \
               "The performance monitoring interval3 was fixed throughout the campaign."
        counts = self._count(body)
        self.assertEqual(counts[2], 1)
        self.assertEqual(counts[3], 1)

    def test_superscript_stays_off_for_a_bracket_citation_paper(self):
        """대괄호를 쓰는 논문에서는 켜지면 안 된다 — 켜지면 오탐이 실제 수치를 오염시킨다."""
        body = " ".join(f"This follows earlier work [{n % 3 + 1}] in the field." for n in range(12))
        body += " The waist radius w0 and the parameter Cn2 were held constant."
        counts = self._count(body)
        self.assertEqual(sum(counts.values()), 12, "대괄호 인용 수와 어긋난다 = 위첨자 오탐이 섞였다")


class SectionLabelTests(unittest.TestCase):
    """인용 맥락에 붙는 섹션 라벨.

    옛 구현은 섹션의 첫 100자를 키로 만들고 문장 앞 50자가 그 안에 들어있는지를 봤다.
    그래서 각 섹션의 **첫 문장에만** 맞고 나머지는 전부 빈 문자열이 됐다(실측
    2026-09-01: 2017_COMST의 인용 맥락 824건이 모두 빈 값). 이 라벨은 인용이 Intro에서만
    나오는 배경 인용인지 Method에서 실제로 쓰였는지를 가르는 신호이고, LLM 역할 분류
    프롬프트에도 `[{sec}] {sentence}` 형태로 들어간다.
    """

    REFS = [ParsedReference(ref_num=n, ref_id=f"[{n}]", authors="X Y") for n in (1, 2, 3)]

    SECTIONS = {
        "introduction": (
            "This paper opens with a broad framing of the problem domain. "
            "Earlier surveys covered the same ground [1]. "
            "We restate the motivation once more for clarity. "
        ),
        "method": (
            "Our pipeline is described in this section in full detail. "
            "The estimator follows the formulation of [2] without modification. "
            "Hyperparameters are listed in the appendix. "
        ),
        "results": (
            "Measurements were collected across twelve independent runs. "
            "The baseline of [3] is outperformed on every split. "
        ),
    }

    def _contexts(self) -> dict[int, list]:
        body = "\n\n".join(self.SECTIONS.values())
        entries = count_citations_numbered(body, self.REFS, self.SECTIONS)
        return {e.ref.ref_num: e.cite_contexts for e in entries}

    def test_citations_past_the_first_sentence_get_their_section(self):
        """회귀 방지의 핵심 — 세 인용 모두 각 섹션의 두 번째 문장에 있다."""
        contexts = self._contexts()
        for num, expected in ((1, "introduction"), (2, "method"), (3, "results")):
            with self.subTest(ref=num):
                self.assertTrue(contexts[num], f"[{num}] 인용을 못 찾았다")
                self.assertEqual(contexts[num][0].section, expected)

    def test_labels_are_empty_when_sections_are_unavailable(self):
        """섹션 분할이 실패한 논문(`{'full_text': ...}`만 나오는 경우)에서는 빈 값이 맞다."""
        body = "\n\n".join(self.SECTIONS.values())
        entries = count_citations_numbered(body, self.REFS, None)
        self.assertEqual(
            [c.section for e in entries for c in e.cite_contexts], ["", "", ""]
        )

    def test_citation_counts_are_unchanged_by_section_labelling(self):
        """라벨만 채워야 한다 — 문장 분할이나 카운트가 함께 흔들리면 안 된다."""
        body = "\n\n".join(self.SECTIONS.values())
        with_sections = count_citations_numbered(body, self.REFS, self.SECTIONS)
        without = count_citations_numbered(body, self.REFS, None)
        self.assertEqual(
            [e.cite_count for e in with_sections], [e.cite_count for e in without]
        )
        self.assertEqual([e.cite_count for e in with_sections], [1, 1, 1])


class ReferenceBranchSelectionTests(unittest.TestCase):
    """parse_references는 "[n]"과 "n." 두 갈래를 모두 파싱해 ref_num 중복이 적은 쪽을 쓴다.

    get_references_text가 본문까지 끌고 오는 논문(2017_COMST 261KB)에서는 본문의
    인용 마커 "[85]"가 대괄호 갈래의 구분자로 오인돼 같은 번호가 여러 번 나왔다
    (14편 중 5편이 22~72% 중복). 그런 논문은 "n." 갈래가 깨끗하다.
    """

    POLLUTED = (
        "We follow the approach of [1] and extend [2] as in [1]; see also [3] and [2].\n"
        "Later work [1] refined this further, and [3] applied it at scale.\n"
        "References\n"
        "1. A. Smith, B. Jones, Robust saliency detection, IEEE TIP, 2013.\n"
        "2. C. Lee, D. Kim, Background priors for segmentation, CVPR, 2014.\n"
        "3. E. Park, F. Choi, Optimization from robust background, ICCV, 2014.\n"
    )

    def test_dot_branch_wins_when_bracket_branch_is_polluted_by_body_markers(self):
        refs = parse_references(self.POLLUTED)
        self.assertEqual([r.ref_num for r in refs], [1, 2, 3])
        self.assertEqual([r.ref_id for r in refs], ["[1]", "[2]", "[3]"])
        self.assertIn("Smith", refs[0].raw_text)

    def test_bracket_branch_wins_on_tie(self):
        # 두 갈래 모두 3건, 중복 0 → 기존 동작(대괄호 우선) 보존
        text = "[1] Alpha.\n1. x\n[2] Beta.\n2. y\n[3] Gamma.\n3. z"
        refs = parse_references(text)
        self.assertEqual([r.ref_num for r in refs], [1, 2, 3])
        self.assertTrue(refs[0].raw_text.startswith("Alpha"))

    def test_clean_bracket_list_is_unchanged(self):
        text = "[1] A. Smith, Title one, J. Opt., 2019.\n[2] B. Lee, Title two, Nature, 2020.\n[3] C. Kim, Title three, Science, 2021."
        refs = parse_references(text)
        self.assertEqual([r.ref_id for r in refs], ["[1]", "[2]", "[3]"])
        self.assertEqual(refs[1].year, 2020)


class SectionCountsTests(unittest.TestCase):
    """to_dict의 section_counts는 5개로 잘린 cite_contexts가 아니라 전체 맥락을 집계한다.

    LLM 후보 필터가 "introduction 밖에서도 인용됐는가"를 볼 때 앞 5개만 보면 서베이 논문의
    상위 참고문헌(앞 5회가 전부 서론)이 잘못 탈락한다.
    """

    def test_section_counts_cover_all_contexts_not_just_the_first_five(self):
        contexts = [CitationContext(sentence=f"s{i}", section="introduction") for i in range(5)]
        contexts.append(CitationContext(sentence="s5", section="methods"))
        entry = CitationEntry(ref=ParsedReference(ref_id="[1]", ref_num=1), cite_count=6, cite_contexts=contexts)
        top = CitationAnalysisResult(total_references=1, entries=[entry]).to_dict()["top_cited"][0]
        self.assertEqual(len(top["cite_contexts"]), 5)
        self.assertEqual(top["section_counts"], {"introduction": 5, "methods": 1})

    def test_unlabelled_contexts_count_under_empty_key(self):
        entry = CitationEntry(
            ref=ParsedReference(ref_id="[1]", ref_num=1), cite_count=1,
            cite_contexts=[CitationContext(sentence="s", section="")],
        )
        top = CitationAnalysisResult(total_references=1, entries=[entry]).to_dict()["top_cited"][0]
        self.assertEqual(top["section_counts"], {"": 1})


if __name__ == "__main__":
    unittest.main()
