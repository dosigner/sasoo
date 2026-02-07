<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# LLM

## Purpose
LLM client implementations for AI provider integration. Dual-LLM strategy: Gemini for analysis (cost-efficient), Claude for Mermaid generation (quality).

## Key Files
| File | Description |
|------|-------------|
| __init__.py | Package initialization |
| claude_client.py (12KB) | Anthropic Claude client. Used primarily for Mermaid diagram generation (Sonnet 4.5 quality advantage) |
| gemini_client.py (34KB) | Google Gemini client. Primary analysis LLM (Gemini 3.0). Handles all 4 analysis phases + multimodal figure analysis |

## Subdirectories
None

## For AI Agents

### Working In This Directory
- Gemini used for: Screening, Visual, Recipe, Deep Dive phases + figure analysis
- Claude used for: Mermaid diagram generation (superior structured output)
- Both clients are async
- API keys loaded from settings database
- Handle rate limiting and retries appropriately

### Testing Requirements
- Test Gemini text analysis with sample paper sections
- Test Gemini multimodal with figure images
- Test Claude Mermaid generation with analysis results
- Verify API key validation and error handling
- Check cost tracking for token usage

### Common Patterns
- Async client initialization with API keys
- Retry logic for transient failures
- Token counting for cost estimation
- Streaming responses where applicable
- Error handling with fallback strategies

## Dependencies

### Internal
- Called by services/analysis_pipeline.py for analysis
- Called by services/viz/mermaid_generator.py for diagrams
- API keys managed via models/database.py settings

### External
- google-generativeai: Gemini API client
- anthropic: Claude API client

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
