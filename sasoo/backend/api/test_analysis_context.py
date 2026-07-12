from api.analysis_context import build_chain_system_instruction, EXPLANATION_LEVELS


def test_level_keys_complete():
    assert set(EXPLANATION_LEVELS) == {"elementary", "middle", "high", "undergrad", "masters", "phd"}


def test_instruction_composition():
    si = build_chain_system_instruction(
        persona_prompt="광학 전문가 페르소나",
        research_context="페로브스카이트 태양전지",
        focus={"chips": ["reproduction"], "note": "격자 정합"},
        level_key="high",
    )
    assert "광학 전문가 페르소나" in si
    assert "페로브스카이트" in si
    assert "재현 방법" in si
    assert "격자 정합" in si
    assert EXPLANATION_LEVELS["high"][:20] in si
    assert "한국어" in si  # 기본 한국어 지시 포함


def test_instruction_defaults():
    si = build_chain_system_instruction("", "", None, "masters")
    assert EXPLANATION_LEVELS["masters"][:20] in si
