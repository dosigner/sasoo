<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# Agents

## Purpose
Domain-specific AI agent implementations for specialized paper analysis. Each agent extracts domain-specific parameters and provides expert-level insights for its field.

## Key Files
| File | Description |
|------|-------------|
| __init__.py | Package initialization |
| base_agent.py | Abstract base class defining agent interface (analyze method, phase prompts) |
| agent_photon.py (14KB) | Optics/Photonics specialist. Extracts optical parameters (wavelength, aperture, beam quality, power, etc.) |
| agent_cell.py (14KB) | Biology/Cell specialist. Protocol-focused parameter extraction (cell lines, antibodies, culture conditions) |
| agent_neural.py (14KB) | AI/ML specialist. Hyperparameter and architecture extraction (model, dataset, optimizer, learning rate) |
| profile_loader.py (8KB) | Loads YAML profiles from agent_profiles/ directory, applies overrides to agents |

## Subdirectories
None

## For AI Agents

### Working In This Directory
- All agents extend `BaseAgent` abstract class
- Each agent implements 4 phase methods: screening, visual, recipe, deepdive
- YAML profiles can override default prompts
- Agent selection handled by domain_router.py
- Recipe parameters are domain-specific extracted metrics

### Testing Requirements
- Test each agent with domain-appropriate papers
- Verify recipe parameter extraction accuracy
- Check prompt override mechanism with custom YAML profiles
- Validate all 4 phases produce structured output
- Test profile_loader with new agent profiles

### Common Patterns
- Inheritance from BaseAgent
- Phase-specific prompt engineering
- Structured output with recipe parameters
- Domain-specific terminology in prompts
- Profile-based customization

### Adding New Domain Agent
1. Create `agent_{name}.py` extending BaseAgent
2. Implement screening/visual/recipe/deepdive methods
3. Define domain-specific recipe parameters
4. Create `{name}_default.yaml` profile in agent_profiles/
5. Register in domain_router.py routing logic

## Dependencies

### Internal
- Loaded by services/domain_router.py
- Configured via agent_profiles/ YAML files
- Called by services/analysis_pipeline.py
- Uses services/llm/ for AI model calls

### External
- PyYAML: Profile loading (via profile_loader.py)

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
