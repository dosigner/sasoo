"""Record what the shipped Python document context builder returns.

Output is read by tests/document_context.rs. Synthetic cases go to the committed
fixture; corpus cases (paper text, copyrighted) store only a path and sha256.

Usage: backend/.venv/bin/python -I tests/document_context_oracle.py <backend_dir> <out_json> [corpus_library_dir]
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from services.document_context import (  # noqa: E402
    build_document_context_from_text,
    input_coverage,
    select_visual_source,
    source_signature,
)

SIGNATURE = {"pdf_mtime_ns": 1, "pdf_size": 2}

REFS_BRACKET = """References
[1] A. Kim, B. Lee, "Adaptive optics for free-space links," Opt. Express 28, 1234 (2020).
[2] C. Park et al., Nature Photonics 12, 55-60, doi: 10.1038/s41566.
[3] D. Choi, "Turbulence," J. Opt. Soc. Am. A 30, 2013, pp. 100-110.
continued line for entry three with https://example.org/x
[3] Duplicate number entry that should be dropped, Science 2019 volume.
[4] short 2020
[٥] Arabic-Indic digit entry, Astron. Astrophys. Suppl 512, A1.
[１２] Fullwidth digit entry about Biomed. Opt. Express 11, 2020.
"""

STANDARD = f"""Deep Optical Networks for Imaging
Alice Author, Bob Author

Abstract
We propose a diffractive network. It reaches 95.2% accuracy at 532 nm. The layer is 10 x 20 μm wide.

1. Introduction
Free-space optics is important [1]. Prior work used 1.5 W lasers? Yes! It ran at 300 K.
We extend it.

2. Materials and Methods
Samples were annealed at 450 °C for 2 h. The flow was 5 mL/min and pressure 1.2 kPa.
A 3.5wt% solution and 5%a were mixed; 7% of it remained.

3. Results and Discussion
The efficiency reached 12 mAh/g and 3 A/g. Area 5 cm² was used; also 4 cm⁻¹ and 2 m³.
Values 1.2.3 nm and 10 min, 20 mins, 5 MHz, 2 GHz were seen. Temperature 25 °C이다.

4. Conclusion
We conclude that 2 dB gain is possible.

Acknowledgments
We thank the funding agency.

{REFS_BRACKET}"""

NUMBERED_REFS = """Abstract
Short abstract here.

Introduction
Intro text mentions the references briefly.

REFERENCES
1. Smith J, Doe K. Laser beams. Optics Letters 2018;43:100-105.
2. Wang L. Photonics review, Proc. SPIE 1234 (2017).
--- Page 9 ---
3. Zhao M, et al. Imaging with metasurfaces. Science 2021.
Supplementary Materials
4. Not a reference after the terminator, Nature 2020 extra words here.
"""

FEW_REFS = """Abstract
Tiny abstract.

## 7. References
Only one loose reference without numbering, Nature 2019.

12

Preprint

Another paragraph of the bibliography.
--- Page 4 ---
## A. Proofs
Proof text.
"""

HEADINGS_ONLY = """Title line ignored before any heading
1. Overview of the Work
This part has numbers like 3 nm and 4 kg.
1.1. Deeper Part
Text of deeper part.
II. Setup Straße Größe
Setup text with 10 Hz.
B. Lettered Item
Lettered text.
(3) Parenthesized Item
Paren text.
SYSTEM DESIGN NOTES
All caps heading content.
ǅUNGLE HEADING TEXT
Titlecase char prevents an all-caps heading.
1. ---
Content under an empty normalized heading.
4. 서론과 배경
한국어 본문입니다. 온도는 25 °C 입니다.
5. Overview of the Work
Duplicate name overwrites the first section.
"""

KOREAN = """초록
본 연구는 자유공간 광통신을 다룬다. 파장은 1550 nm이고 출력은 2 W이다.

서론
대기 난류는 중요한 문제이다.
"""

SPANNING = """Background and
Introduction text continues here
The background and introduction body.
RESULTŚ with a combining mark
Results body with 5 nm.
This line mentions results but is very long so that it exceeds the one hundred character limit for headers easily.
DISCUSSION
Discussion body.
Final Remarks
Closing text.
"""

CONTROL_WS = "Abstract\n5\x1fnm thick films.\x1cNext sentence here.\x1d\n\nResults\nA\x1e10 kHz signal. Done.\x0cMore.\r\nCRLF line 3 ms.\r\n"

TAIL_TRIM = """Intro paragraph one with plenty of words to make the head long enough for the fifteen percent rule.
1. Early numbered item, Nature 2019, that is before fifteen percent of text length.
2. Second early numbered item, Science 2018, still before the cut.
3. Third early numbered item, Photonics 2017, also early.
""" + "Body filler sentence about the experiment and its setup. " * 40 + """
Abstract
Abstract body.
Results
Results body describing 3 nm features.
[1] First tail reference, Opt. Express 2020, 25 pages long title here.
[2] Second tail reference with doi: 10.1000/xyz and more words to pass.
[3] Third tail reference et al. 2021 in a journal of record.
"""

BODY_FALLBACK = "İİİİ " * 30 + "Some prose without any headings at all. " * 20 + "\nreferences\nThe end list."

WORDS = " ".join(f"word{i}" for i in range(1001))

LONG_ABSTRACT = "Abstract\n" + ("긴 초록 문장입니다 5 nm.  " * 270) + "\nConclusion\n" + ("Conclusion text. " * 200)

LONG_METHOD = (
    "Methods\n" + ("The method uses 3 mm optics and 2 ms pulses. " * 280)
    + "\nIntroduction\n" + ("Intro sentence. " * 200)
    + "\nResults\n" + ("Result sentence with 4 dB.   " * 150)
    + "\nReferences\n[1] Ref one, Nature 2020, long enough entry.\n"
)

MATERIALS = """Materials and Methods
Body under a heading matched twice for the method type.
Results and Discussion
Body under a heading matched three times.
"""

SYNTHETIC = [
    ("standard", STANDARD),
    ("numbered_refs", NUMBERED_REFS),
    ("few_refs_markdown_heading", FEW_REFS),
    ("headings_only", HEADINGS_ONLY),
    ("korean_patterns", KOREAN),
    ("spanning_and_long_lines", SPANNING),
    ("control_whitespace", CONTROL_WS),
    ("tail_trim", TAIL_TRIM),
    ("body_fallback_unicode_lower", BODY_FALLBACK),
    ("no_headings_many_words", WORDS),
    ("no_headings_short", "just a short note. 5 nm! ok?"),
    ("empty", ""),
    ("whitespace_only", " \n\t \x1c "),
    ("long_abstract_truncation", LONG_ABSTRACT),
    ("long_method_truncation", LONG_METHOD),
    ("materials_double_match", MATERIALS),
    ("roman_references_heading", "Abstract\nA.\n\nIX. REFERENCES\n[1] A, Nature 2001, sufficiently long entry text.\n[2] B, Science 2002, sufficiently long entry text.\n[3] C, J. Appl. Phys. 2003, sufficiently long entry text.\nAppendix\n[4] D, Nature 2004, appendix entry text long enough.\n"),
    ("terminator_before_three", "Introduction\nx\nReferences\n[1] A, Nature 2001, long enough entry text here.\nAcknowledgements\n[2] B, Science 2002, long enough entry text here.\n[3] C, Photonics 2003, long enough entry text.\n"),
]

PAGED = """--- Page 1 ---
Intro page discussing the system architecture overview.
--- Page 2 ---
Results show Table 1: Main results
| Model | NLL |
| A | 3.12 |
--- Page 3 ---
| B | 2.99 |
Definitions of NLL follow. Table 2. Secondary
--- Page 4 ---
The loss is $L = a + b$ (3)
where a is the bias.
\\tag{5} and E = mc^2 (4)
--- Page 5 ---
Table IV (continued) more rows
| C | 1.00 |
--- Page 0 ---
Zero page label text with Table 1 DE caption form.
--- Page 6 ---
See Table 2 Q2 form.
"""

CHUNKED = "\n\n".join(
    [("Paragraph about optics and lasers. " * 30).strip()] * 3
    + ["$$x = y" + " + z" * 500, "w = 1 (7)$$"]
    + [("Tail paragraph regarding detectors. " * 20).strip()] * 4
)

VISUAL_PLANS = [
    ({"description": "Table 1"}, 16000),
    ({"title": "Compare Table 1 and Table 2", "description": "Use eqs. 3-5 and Equation (4)"}, 16000),
    ({"title": "Table IV", "description": "Check Eq. 3, Eq. 4"}, 16000),
    ({"description": "Table 1 Table 2 Table 9"}, 300),
    ({"title": "System architecture overview", "description": "Figure of optics lasers detectors"}, 16000),
    ({"title": None, "description": "Equation 7"}, 16000),
    ({}, 16000),
]

VISUAL_SYNTHETIC = [("paged", PAGED), ("chunked", CHUNKED), ("standard", STANDARD), ("empty", "")]

CORPUS_PLANS = [
    ({"description": "Table 1"}, 16000),
    ({"title": "Equation 3 and Table 2", "description": "Compare eqs. 1-4 results"}, 16000),
    ({"title": "System overview", "description": "Figure of the network architecture and results"}, 16000),
]


def visual(text, plans):
    return [{"plan": p, "limit": lim, "expected": select_visual_source(p, text, limit=lim)} for p, lim in plans]


def main() -> None:
    out_path = Path(sys.argv[2])
    cases = []
    for name, text in SYNTHETIC:
        cases.append({"name": name, "full_text": text,
                      "expected": build_document_context_from_text(text, pdf_signature=SIGNATURE, parser_version="fixture")})
    cases.append({"name": "default_signature", "full_text": "Abstract\nA\nResults\nB",
                  "pdf_signature": {},
                  "expected": build_document_context_from_text("Abstract\nA\nResults\nB", pdf_signature={}, parser_version="fixture")})
    visual_cases = [{"name": n, "full_text": t, "runs": visual(t, VISUAL_PLANS)} for n, t in VISUAL_SYNTHETIC]
    coverage = []
    for text, sha, limit in [("abc", None, None), ("x" * 12345, None, 12000), ("x" * 999, None, 1000),
                             ("한글" * 600, None, 1200), ("abc", "f" * 64, None), ("abc", "", 3)]:
        coverage.append({"text": text, "pdf_sha256": sha, "text_limit": limit,
                         "expected": input_coverage(text, pdf_sha256=sha, text_limit=limit)})
    signatures = []
    for text, sha, detail in [("source", None, "high"), ("한글 source", None, "high"), ("source", "a" * 64, "low"), ("", "", "high")]:
        signatures.append({"text": text, "pdf_sha256": sha, "detail": detail,
                           "expected": source_signature(text, pdf_sha256=sha, detail=detail)})

    if len(sys.argv) > 3:
        cases, visual_cases, coverage, signatures = [], [], [], []
        for path in sorted(Path(sys.argv[3]).glob("*/.text_cache.txt")):
            raw = path.read_bytes()  # bytes: read_text() would translate \r\n
            text = raw.decode("utf-8")
            cases.append({"name": path.parent.name, "full_text_path": str(path),
                          "sha256": hashlib.sha256(raw).hexdigest(),
                          "expected": build_document_context_from_text(text, pdf_signature=SIGNATURE, parser_version="fixture"),
                          "visual": visual(text, CORPUS_PLANS)})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"cases": cases, "visual_cases": visual_cases, "coverage": coverage,
                                    "signatures": signatures}, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} cases, {len(visual_cases)} visual cases to {out_path}")


main()
