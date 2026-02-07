<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# Agent Profiles

## Purpose
YAML configuration profiles for domain-specific AI agents. Each profile defines agent personality, domain expertise, icon, and recipe parameters for specialized paper analysis.

## Key Files
| File | Description |
|------|-------------|
| __init__.py | Package initialization |
| README.md | Detailed documentation for profile structure and usage |
| photon_default.yaml | Optics/Photonics agent (wavelength, aperture, focal_length, beam_quality, power) |
| cell_default.yaml | Biology/Cell agent (cell_line, culture_medium, antibody, drug_concentration) |
| neural_default.yaml | AI/ML agent (model_architecture, dataset, learning_rate, optimizer) |

## Subdirectories
None

## For AI Agents

### Working In This Directory
- Each YAML file defines one agent profile
- Profiles loaded by `services/agents/profile_loader.py`
- Structure: agent_name, domain, display_name, personality, icon, recipe_parameters, optional prompt overrides
- To create new agent: Add {name}_default.yaml with required fields

### Testing Requirements
- Validate YAML syntax after edits
- Test profile loading via settings API: GET /api/settings/agent-profiles
- Verify recipe parameters appear correctly in analysis results
- Check icon and display_name render in frontend

### Common Patterns
- Naming convention: `{domain}_default.yaml`
- agent_name should match filename prefix
- recipe_parameters are domain-specific metrics to extract
- Prompt overrides are optional (screening_prompt, visual_prompt, recipe_prompt, deepdive_prompt)
- Icons use emoji or Unicode symbols

## Dependencies

### Internal
- Loaded by services/agents/profile_loader.py
- Applied to agents in services/agents/agent_{name}.py
- Exposed via api/settings.py endpoints

### External
- PyYAML: YAML parsing (implicit, used by profile_loader)

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
