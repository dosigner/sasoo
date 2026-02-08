# JSON Parsing Error Handling Fixes

## Summary
Fixed critical JSON parsing issues across the Sasoo analysis pipeline to properly detect, log, and handle malformed JSON responses from LLM APIs.

## Problems Fixed

### Problem 1: Silent Parse Errors in `gemini_client.py`
**Location**: `/home/dosigner/논문/sasoo/backend/services/llm/gemini_client.py`

**Issue**: The `_extract_json` function returned `{"_raw": text, "_parse_error": str(exc)}` on failure, but no downstream code checked for `_parse_error`. This meant malformed JSON silently became "valid" data.

**Fix**: Added `is_parse_error(result: dict) -> bool` helper function to check for parse error indicators.

```python
def is_parse_error(result: dict) -> bool:
    """
    Check if a result dict contains a JSON parse error.

    Args:
        result: Dictionary returned from _extract_json or similar parsing.

    Returns:
        True if the result contains a parse error indicator.
    """
    return "_parse_error" in result
```

### Problem 2: Parse Errors Not Validated in `analysis_pipeline.py`
**Location**: `/home/dosigner/논문/sasoo/backend/services/analysis_pipeline.py`

**Issue**: The `_parse_json_response` method returned `{"raw_response": text}` on parse failure, which was stored as if it were valid phase data. No validation occurred after parsing.

**Fix**:
1. Enhanced `_parse_json_response` to include `_parse_error` key in the error dict
2. Added validation after each phase's JSON parsing to check for `raw_response` or `_parse_error` keys
3. Set phase status to "error" and populate error_message when parse errors are detected
4. Raw data is still stored for debugging purposes

Changes applied to all 4 phases:
- Phase 1 (Screening) - line ~340
- Phase 2 (Visual) - line ~435
- Phase 3 (Recipe) - line ~521
- Phase 4 (Deep Dive) - line ~604

Example validation code:
```python
# Check for parse errors
if "raw_response" in result_data or "_parse_error" in result_data:
    logger.warning(
        "Paper %d Phase 1: JSON parse error detected. Storing raw response for debugging.",
        paper_id,
    )
    phase_result.status = "error"
    phase_result.error_message = result_data.get("_parse_error", "JSON parsing failed")
else:
    phase_result.status = "completed"

phase_result.result = result_data
phase_result.usage = usage
```

### Problem 3: No Validation After `_clean_llm_json` in `api/analysis.py`
**Location**: `/home/dosigner/논문/sasoo/backend/api/analysis.py`

**Issue**: `_clean_llm_json` only stripped markdown fences. The raw text was directly stored in DB without checking if it's valid JSON first (lines 240, 308, 376, 460).

**Fix**: After each `_clean_llm_json()` call, added validation with `json.loads()`. If parsing fails, wrap the text in proper error structure `{"_raw": original_text, "_parse_error": str(exc)}` and log warning.

Changes applied to all 4 phases:
- Phase 1 (Screening) - line ~235
- Phase 2 (Visual) - line ~312
- Phase 3 (Recipe) - line ~473
- Phase 4 (Deep Dive) - line ~549

Example validation code:
```python
cleaned_text = _clean_llm_json(result["text"])

# Validate JSON before storing
try:
    json.loads(cleaned_text)
    result["text"] = cleaned_text
except json.JSONDecodeError as exc:
    logger.warning("Phase 1 JSON validation failed: %s", exc)
    result["text"] = json.dumps({"_raw": cleaned_text, "_parse_error": str(exc)})
```

Also added logging import to api/analysis.py:
```python
import logging
logger = logging.getLogger(__name__)
```

## Benefits

1. **Error Detection**: Parse errors are now properly detected at all stages of the pipeline
2. **Error Logging**: All parse failures are logged with warnings for monitoring
3. **Error Propagation**: Phase status is correctly set to "error" when JSON parsing fails
4. **Debugging Support**: Raw malformed responses are preserved in the database for debugging
5. **Consistent Handling**: All three layers (gemini_client, analysis_pipeline, api) use consistent error structures

## Error Structure

When JSON parsing fails, the error structure is:
```json
{
  "_raw": "original malformed text",
  "_parse_error": "error message from JSONDecodeError"
}
```

This structure:
- Can be easily detected with `"_parse_error" in result` or `"raw_response" in result`
- Preserves the original response for debugging
- Provides the error message for logging and display

## Testing Recommendations

1. Test with intentionally malformed JSON responses
2. Verify phase status is set to "error" when parse fails
3. Check database contains error structure with `_parse_error` key
4. Verify logs contain appropriate warnings
5. Test downstream code handles error structures gracefully

## Files Modified

1. `/home/dosigner/논문/sasoo/backend/services/llm/gemini_client.py`
   - Added `is_parse_error()` helper function

2. `/home/dosigner/논문/sasoo/backend/services/analysis_pipeline.py`
   - Updated `_parse_json_response()` to include `_parse_error` in error dict
   - Added validation after parsing in all 4 phase methods

3. `/home/dosigner/논문/sasoo/backend/api/analysis.py`
   - Added logging import
   - Added JSON validation after `_clean_llm_json()` in all 4 phase functions
