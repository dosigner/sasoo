from copy import deepcopy

import pytest

from services.summary_contract import validate_summary_extensions


def summary_payload():
    return {
        "section_answers": [{
            "section_title": "2. Methods", "question": "무엇을 비교했나요?",
            "answer": "두 측정 조건을 비교합니다.", "explanation": "",
            "source_refs": ["2. Methods"],
        }],
        "transfer_checks": [{
            "item": "측정 조건", "paper_condition": "동일한 측정 조건입니다.",
            "condition_basis": "reported", "check_before_transfer": "측정 조건을 확인합니다.",
            "source_refs": ["2. Methods"],
        }],
    }


def test_legacy_is_readable_but_not_new_generation():
    legacy = {"detailed_analysis": "기존 분석"}
    assert validate_summary_extensions(legacy) is False
    with pytest.raises(ValueError):
        validate_summary_extensions(legacy, require=True)


def test_generation_error_envelope_is_not_a_legacy_summary():
    with pytest.raises(ValueError):
        validate_summary_extensions({"_raw": "broken JSON", "_parse_error": "invalid JSON"})


def test_valid_payload_is_preserved():
    payload = summary_payload()
    original = deepcopy(payload)
    assert validate_summary_extensions(payload, require=True) is True
    assert payload == original


def test_empty_arrays_are_valid():
    assert validate_summary_extensions({"section_answers": [], "transfer_checks": []}, require=True)


@pytest.mark.parametrize("field,limit", [("section_answers", 12), ("transfer_checks", 8)])
def test_array_bounds(field, limit):
    payload = summary_payload()
    payload[field] *= limit
    assert validate_summary_extensions(payload)
    payload[field].append(payload[field][0])
    with pytest.raises(ValueError):
        validate_summary_extensions(payload)


@pytest.mark.parametrize("field", ["section_answers", "transfer_checks"])
@pytest.mark.parametrize("invalid", [None, {}, "", [None]])
def test_invalid_arrays(field, invalid):
    payload = summary_payload()
    payload[field] = invalid
    with pytest.raises(ValueError):
        validate_summary_extensions(payload)


@pytest.mark.parametrize("field", ["section_answers", "transfer_checks"])
def test_partial_extensions_are_invalid(field):
    with pytest.raises(ValueError):
        validate_summary_extensions({field: []})


@pytest.mark.parametrize("field,key", [
    ("section_answers", "section_title"), ("section_answers", "question"),
    ("section_answers", "answer"), ("section_answers", "explanation"),
    ("transfer_checks", "item"), ("transfer_checks", "paper_condition"),
    ("transfer_checks", "check_before_transfer"),
])
def test_required_string_types(field, key):
    payload = summary_payload()
    payload[field][0][key] = 1
    with pytest.raises(ValueError):
        validate_summary_extensions(payload)


@pytest.mark.parametrize("field", ["section_answers", "transfer_checks"])
@pytest.mark.parametrize("refs", [[], [" "], [3], ["s"] * 5, "s"])
def test_sources_require_nonempty_strings_within_limit(field, refs):
    payload = summary_payload()
    payload[field][0]["source_refs"] = refs
    with pytest.raises(ValueError):
        validate_summary_extensions(payload)


@pytest.mark.parametrize("basis", ["reported", "inferred", "not_reported", "invented"])
def test_condition_basis_controls_source_requirement(basis):
    payload = summary_payload()
    payload["transfer_checks"][0].update(condition_basis=basis, source_refs=[])
    if basis == "not_reported":
        assert validate_summary_extensions(payload)
    else:
        with pytest.raises(ValueError):
            validate_summary_extensions(payload)
