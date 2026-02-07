# Sasoo Agent Profiles

This directory contains YAML profiles for domain-specific analysis agents.

## Overview

Agent profiles allow customization of:
- Agent metadata (display names, personality, icons)
- Recipe parameters (domain-specific extraction fields)
- Phase prompts (optional overrides for each analysis phase)

## Profile Structure

Each profile is a YAML file named `{agent_name}_default.yaml`:

```yaml
# Agent Profile: {Name}
agent_name: {identifier}
domain: {domain_key}
display_name: {English Name}
display_name_ko: {Korean Name}
personality: "{personality description}"
icon: {icon_identifier}

# Domain-specific parameters to extract during Phase 3 (Recipe Extraction)
recipe_parameters:
  - parameter1
  - parameter2
  - parameter3

# Optional prompt overrides (if not set, uses agent class defaults)
prompts:
  screening: "Custom screening prompt..."
  visual: "Custom visual prompt..."
  recipe: "Custom recipe prompt..."
  deepdive: "Custom deepdive prompt..."
```

## Available Profiles

### 1. Photon (Optics/Photonics)
- **File**: `photon_default.yaml`
- **Domain**: optics
- **Parameters**: wavelength, aperture, focal_length, beam_quality, power, etc.

### 2. Cell (Biology/Cell Biology)
- **File**: `cell_default.yaml`
- **Domain**: biology
- **Parameters**: cell_line, culture_medium, antibody, drug_concentration, etc.

### 3. Neural (AI/ML)
- **File**: `neural_default.yaml`
- **Domain**: ai_ml
- **Parameters**: model_architecture, dataset, learning_rate, optimizer, etc.

## API Endpoints

### List All Profiles
```http
GET /api/settings/agents
```

Response:
```json
{
  "agents": ["photon", "cell", "neural"],
  "count": 3
}
```

### Get Specific Profile
```http
GET /api/settings/agents/{agent_name}
```

Response:
```json
{
  "agent_name": "photon",
  "domain": "optics",
  "display_name": "Agent Photon",
  "display_name_ko": "포톤 에이전트",
  "personality": "반말 + 직설적 말투...",
  "icon": "photon",
  "recipe_parameters": ["wavelength", "aperture", ...],
  "prompts": {}
}
```

### Update Profile
```http
PUT /api/settings/agents/{agent_name}
Content-Type: application/json

{
  "agent_name": "photon",
  "domain": "optics",
  "display_name": "Agent Photon",
  "display_name_ko": "포톤 에이전트",
  "personality": "Custom personality...",
  "icon": "photon",
  "recipe_parameters": [...],
  "prompts": {
    "screening": "Custom screening prompt..."
  }
}
```

## Usage in Code

### Load a Profile

```python
from services.agents.profile_loader import load_profile

profile = load_profile("photon")
if profile:
    print(profile.display_name)
    print(profile.recipe_parameters)

    # Check for prompt overrides
    if profile.has_prompt_override("screening"):
        custom_prompt = profile.get_prompt_override("screening")
```

### Apply Profile to Agent

```python
from services.agents.profile_loader import load_profile, apply_profile_to_agent
from services.agents.agent_photon import AgentPhoton

agent = AgentPhoton()
profile = load_profile("photon")

if profile:
    apply_profile_to_agent(agent, profile)
    # Now agent uses profile overrides
```

### Save a Profile

```python
from services.agents.profile_loader import save_profile

profile_data = {
    "agent_name": "photon",
    "domain": "optics",
    "display_name": "Agent Photon",
    "display_name_ko": "포톤 에이전트",
    "personality": "반말 + 직설적",
    "icon": "photon",
    "recipe_parameters": ["wavelength", "aperture"],
    "prompts": {
        "screening": "Custom prompt..."
    }
}

save_profile("photon", profile_data)
```

## Customization

To customize an agent:

1. Edit the YAML file in this directory
2. Modify metadata, parameters, or add prompt overrides
3. Restart the backend to load changes
4. Or use the API to update profiles dynamically

## Notes

- If a YAML file exists, its prompt overrides replace the agent's defaults
- If no YAML file exists, the agent falls back to class defaults
- Profile location: `~/sasoo-library/agent_profiles/`
- All prompts are optional - only override what you need to customize
