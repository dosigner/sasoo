"""Freeze the shared default instruction before moving its definition."""

import hashlib

from services.llm import gemini_client, openai_client


def test_default_instruction_identity_and_utf8_bytes():
    instruction = gemini_client._SYSTEM_INSTRUCTION_KO
    assert openai_client._SYSTEM_INSTRUCTION_KO is instruction
    assert hashlib.sha256(instruction.encode("utf-8")).hexdigest() == (
        "ebadc3fd3fd2c3e638c575f603e5d7460c6fcc8cfe8d8b483243eaa1ada3060c"
    )
