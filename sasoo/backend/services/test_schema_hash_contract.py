"""Freeze provider schema content before extracting schema definitions."""

import hashlib
import json

import pytest

from services import analysis_execution


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("SCREENING", "55170d737be82e733fd93bf3f760b0730b11b0a55aa840081a857a7c70a3d754"),
        ("CITATION", "4644840cbf94c145c01931773981bd273e74a8fead6415f3bffdc2896144eb68"),
        ("VISUAL", "bde9bc15b2c121d322c6871916f3648b912b03f09685bec2b0aa255f700bc174"),
        ("RECIPE", "c67fd25ba323358a55a9c187738cde292ea4ce616e5a1f8ca5409342157eac63"),
        ("DEEP_DIVE", "be3010c070a8ca472155761f4f588fbddc7bd8e773e60aaa6d0b436441fe0e39"),
        ("VIZ_PLAN", "e5fe4b9819ac909c3c9c25abdb9bd687acd07893958109e30f5e6874f36e7ed3"),
        ("SYNTHESIS", "0d1a2f38fe37b2ceb0bb9edcaddcb1067a409e746bd6d30d05f11eadb5244e3e"),
    ],
)
def test_schema_json_hash(name, expected):
    schema = getattr(analysis_execution, f"_{name}_SCHEMA")
    encoded = json.dumps(schema, sort_keys=True).encode("utf-8")
    assert hashlib.sha256(encoded).hexdigest() == expected
