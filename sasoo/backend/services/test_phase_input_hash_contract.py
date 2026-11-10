"""Freeze phase input bytes that contribute to provider cache keys."""

import hashlib

from services.document_context import _build_phase_inputs


def test_phase_input_utf8_hashes():
    sections = {
        "abstract": "Synthetic abstract: 한국어 and equation x = 1.\n" * 12,
        "introduction": "Introduction: question and scope.\n" * 30,
        "background": "Background context.\n" * 20,
        "method": "Method: step and parameter 42 mm.\n" * 140,
        "materials_methods": "Materials and methods.\n" * 30,
        "experimental": "Experiment at 20 C.\n" * 35,
        "results": "Results: measured value 3.14.\n" * 120,
        "discussion": "Discussion and limitation.\n" * 20,
        "conclusion": "Conclusion: bounded result.\n" * 12,
        "references": "[1] Example Author. Example Study. 2020.\n[2] Example B. 2021.",
    }
    full_text = "Synthetic source fallback.\n" + "\n".join(sections.values())
    expected = {
        "screening": "1eb789f22b515db1b0a06979d4ea1d54e7bde9e2844ba4f26b1053698a6bf9e8",
        "citation_body": "5a594793b03166fd8fbdb1233c73cac8f33877925e75ecd41fe130e22f890d1e",
        "citation_references": "4035f3d5416587c8658963fea6ea419b526fc6d671e6c012f32d82fff50c5fbb",
        "visual": "dd1343e307a6cfa6327c9e593ebb5d117d95e116fe4c1e2a4f30a59c966cd66a",
        "recipe": "9bd75dda8373d0f30303b0b5e04fbb799af50e58402d64652c05f53b0113cf26",
        "deep_dive": "51457b129f60c5507d9cfa2696a813b5ff4146b62f269ee529d7a3d8f137db68",
        "visualization": "12a9cc8d0f1bb24e5731c1bc2bea893ee46be33adfc3892ba4990e033ee53eea",
        "chat": "ee59a36960b3b122e01c6fc3266eb74917ff7b89bb099d3c1285d51e054c364e",
        "figure_detail": "fe416d84ed69182a1f7a065c8a80e2b084ebc72fc8d33a6eac43adb452469224",
    }
    actual = _build_phase_inputs(sections, full_text)
    assert {name: hashlib.sha256(value.encode("utf-8")).hexdigest()
            for name, value in actual.items()} == expected
