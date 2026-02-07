<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# Viz

## Purpose
Visualization generation services. Automatic routing between Mermaid diagrams (logic/flow) and PaperBanana illustrations (publication-quality scientific figures).

## Key Files
| File | Description |
|------|-------------|
| __init__.py | Package initialization |
| viz_router.py (21KB) | Routes visualization requests: determines whether to use Mermaid (logic diagrams) or PaperBanana (publication-quality illustrations) |
| mermaid_generator.py (16KB) | Generates Mermaid.js diagram code via Claude Sonnet 4.5 |
| paperbanana_bridge.py (10KB) | Integration with PaperBanana package for scientific figure generation via Gemini Pro Image |

## Subdirectories
None

## For AI Agents

### Working In This Directory
- Visualization router auto-classifies diagram type from request
- Mermaid used for: flowcharts, sequence diagrams, class diagrams, state machines
- PaperBanana used for: publication-quality scientific figures, experimental setups, data visualizations
- Claude Sonnet 4.5 provides superior Mermaid syntax quality
- Generated diagrams saved to paper-specific directories

### Testing Requirements
- Test router classification with various diagram descriptions
- Verify Mermaid syntax validity (use online Mermaid editor)
- Test PaperBanana integration with scientific figure requests
- Check file saving to correct paper directories
- Validate diagram embedding in reports

### Common Patterns
- Intent classification for diagram type selection
- Prompt engineering for diagram generation
- File I/O for saving generated artifacts
- Error handling for invalid syntax
- Quality validation before returning results

## Dependencies

### Internal
- Called by services/analysis_pipeline.py
- Uses services/llm/claude_client.py for Mermaid
- Uses services/llm/gemini_client.py for PaperBanana
- Saves to directories from models/database.py helpers

### External
- paperbanana: Scientific figure generation library
- anthropic: Claude API (via claude_client.py)
- google-generativeai: Gemini API (via gemini_client.py)

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
