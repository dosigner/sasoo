from unittest.mock import patch

from services.odl_parser import _resolve_stage_engine


def test_text_engine_explicit_override_precedes_environment():
    with patch.dict("os.environ", {"SASOO_PDF_ENGINE": "gemini", "SASOO_PDF_TEXT_ENGINE": "gemini"}, clear=True):
        assert _resolve_stage_engine("text", "odl") == "odl"
