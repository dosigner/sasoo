"""Freeze visualization selection before moving its pure policy helpers."""

import json
from pathlib import Path

from services import analysis_execution as ae


PLAN = {
    "illustrations": [
        {"title": "Structure", "purpose": "structure", "importance": 60, "difficulty": 70},
        {"title": "Duplicate structure", "purpose": "structure", "importance": 100, "difficulty": 100},
        {"title": "Process", "purpose": "process", "importance": 59, "difficulty": 70},
        {"title": "Extra high", "purpose": "additional", "importance": 90, "category": "comparison"},
        {"title": "Extra boundary", "purpose": "additional", "importance": 60},
        {"title": "Extra below", "purpose": "additional", "importance": 59},
        {"title": "Text score", "purpose": "additional", "importance": "90"},
        {"title": "Boolean score", "purpose": "additional", "importance": True},
        {"title": "NaN score", "purpose": "additional", "importance": float("nan")},
    ],
    "diagrams": [
        {"title": "Sequence", "diagram_type": "sequence", "importance": 10},
        {"title": "High", "diagram_type": "flowchart", "importance": 61},
        {"title": "Boundary", "diagram_type": "flowchart", "importance": 60},
        {"title": "Below", "diagram_type": "flowchart", "importance": 59},
    ],
    "interactive_html": {"applicable": True, "title": "Calculator"},
    "diagram_count": 99,
}
SNAPSHOT = Path(__file__).parent / "fixtures" / "viz_plan_snapshot.json"


def test_normalized_and_legacy_gated_plan():
    normalized = ae._normalize_viz_plan(PLAN)
    legacy = normalized + [
        {"tool": "paperbanana", "diagram_type": "structure", "title": "duplicate", "importance": 100},
        {"tool": "html", "diagram_type": "interactive", "title": "duplicate html"},
        {"tool": "mermaid", "diagram_type": "sequence", "title": "duplicate sequence", "importance": 20},
    ]
    observed = {"normalized": normalized, "gated": ae._gate_viz_items(legacy)}
    assert observed == json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert [item["title"] for item in normalized] == [
        "Structure", "Process", "Extra high", "Extra boundary", "Sequence", "High", "Boundary", "Calculator"
    ]
    assert sum(item.get("image_model") == ae.MODEL_IMAGE_SUNBURST for item in normalized) == 1
