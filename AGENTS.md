<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# Sasoo (사수) — AI Co-Scientist for Research Paper Analysis
> **Technology Stack**: Electron 28 + React 18 + TypeScript 5 + Python FastAPI + SQLite

---

## Purpose

Sasoo is an AI Co-Scientist desktop application that analyzes research papers through a **4-phase engineering analysis strategy** (Screening → Visual Verification → Recipe Extraction → Deep Dive) powered by **dual LLM** (Gemini 3.0 + Claude Sonnet 4.5) with domain-specialized AI agents.

The application:
- Accepts PDF research papers and classifies them by domain
- Executes structured analysis phases with token-optimized prompts
- Extracts experimental recipes with parameter validation
- Auto-generates visualizations via Mermaid (logic/structure) and PaperBanana (illustrations)
- Produces integrated Markdown analysis reports with embedded figures
- Stores all data and artifacts in local SQLite + file system (no cloud/database complexity)

---

## Key Files

| File | Purpose | Owner |
|------|---------|-------|
| `/sasoo/main.ts` | Electron entry point; spawns backend Python server and frontend renderer | Electron Core |
| `/sasoo/backend/main.py` | FastAPI application; initializes DB, mounts static routes, registers API routers | Backend Core |
| `/sasoo/frontend/src/App.tsx` | React root; routes to upload/library/analysis views | Frontend Core |
| `/sasoo/electron/python-manager.ts` | Spawns and manages the backend Python FastAPI process | Electron IPC |
| `/sasoo/backend/services/analysis_pipeline.py` | Orchestrates the 4-phase pipeline; calls LLM clients in sequence | Analysis Engine |
| `/sasoo/backend/services/agents/base_agent.py` | Abstract base class for domain-specialized agents | Agent Framework |
| `/sasoo/backend/services/agents/agent_photon.py` | Optics/Photonics domain agent; defines phase prompts + recipe params | Agent: Optics |
| `/sasoo/backend/services/agents/agent_cell.py` | Cell Biology / Biomedical domain agent | Agent: Biology |
| `/sasoo/backend/services/agents/agent_neural.py` | Neural networks / Deep learning domain agent | Agent: AI/ML |
| `/sasoo/backend/services/agents/profile_loader.py` | Loads/saves agent profiles from YAML for customization | Agent Config |
| `/sasoo/backend/services/llm/gemini_client.py` | Wrapper for Google Gemini API (Flash + Pro models) | LLM: Gemini |
| `/sasoo/backend/services/llm/claude_client.py` | Wrapper for Anthropic Claude Sonnet 4.5 API | LLM: Claude |
| `/sasoo/backend/services/viz/viz_router.py` | Routes analysis outputs to Mermaid (logic) or PaperBanana (illustrations) | Visualization Router |
| `/sasoo/backend/services/viz/mermaid_generator.py` | Generates Mermaid diagrams via Claude Sonnet 4.5 | Mermaid Engine |
| `/sasoo/backend/services/viz/paperbanana_bridge.py` | Bridges to PaperBanana library for publication-quality illustrations | PaperBanana Bridge |
| `/sasoo/backend/models/database.py` | SQLite async client; schema definition; DB paths | Database Layer |
| `/sasoo/backend/models/schemas.py` | Pydantic models for API request/response validation | Data Models |
| `/sasoo/backend/api/papers.py` | FastAPI router: upload, list, get, delete papers | Papers API |
| `/sasoo/backend/api/analysis.py` | FastAPI router: start analysis, get results, stream updates | Analysis API |
| `/PRD_Sasoo_v3.0.md` | Complete product requirements document (60 KB) | Specification |

---

## Subdirectories

| Path | Purpose | Ownership |
|------|---------|-----------|
| `/sasoo/electron/` | Electron main process (TypeScript); IPC handlers; Python subprocess management |  Electron Core |
| `/sasoo/frontend/` | React 18 + Vite 5 + TypeScript 5; UI components, hooks, routing | Frontend |
| `/sasoo/backend/` | Python FastAPI application; agents, LLM clients, analysis pipeline | Backend |
| `/sasoo/backend/services/` | Domain logic: PDF parsing, LLM clients, analysis orchestration, visualization | Services |
| `/sasoo/backend/services/agents/` | Domain-specialized agent implementations (Photon, Cell, Neural, etc.) | AI Agents |
| `/sasoo/backend/services/llm/` | LLM client wrappers (Gemini, Claude) with token usage tracking | LLM Integration |
| `/sasoo/backend/services/viz/` | Visualization routers and generators (Mermaid, PaperBanana) | Visualization |
| `/sasoo/backend/api/` | FastAPI routers (papers, analysis, settings) | API Layer |
| `/sasoo/backend/models/` | Database layer, Pydantic schemas, ORM utilities | Data Layer |
| `/sasoo/backend/agent_profiles/` | YAML configuration templates for agent customization | Config |
| `/doc/` | External reference docs (PaperBanana.pdf usage guide) | Documentation |
| `/outputs/` | Analysis run artifacts: diagrams, metadata, iteration logs | Results |

---

## AI Agents

### Overview

Sasoo uses **domain-specialized agents** to tailor analysis prompts for different research fields. Each agent:
1. Inherits from `BaseAgent` abstract class
2. Implements 4 phase prompts (Screening, Visual, Recipe, DeepDive)
3. Defines a list of domain-specific recipe parameters
4. Can be customized via YAML profiles in `~/sasoo-library/agent_profiles/`

Current agents:
- **Agent Photon**: Optics, Photonics, Laser Physics, FSO, Spectroscopy
- **Agent Cell**: Cell Biology, Biomedical Engineering, Microscopy
- **Agent Neural**: Deep Learning, Neural Networks, AI/ML Methods

Future phases will add agents for Chemistry, Materials Science, and other domains.

### Agent Architecture

#### BaseAgent (Abstract Base Class)

**Location**: `/sasoo/backend/services/agents/base_agent.py`

**Responsibilities**:
- Define the abstract interface all agents must implement
- Provide metadata container (`AgentInfo`) for display names, personality, domain classification
- Manage phase prompt dispatch via `get_system_prompt(phase: str)` utility
- Serialize agent info to dict for API responses

**Core Methods**:
```python
@property
@abstractmethod
def info(self) -> AgentInfo:
    """Return agent metadata."""

@abstractmethod
def get_screening_prompt() -> str:
    """Phase 1: Quick triage + relevance check."""

@abstractmethod
def get_visual_prompt() -> str:
    """Phase 2: Figure/graph analysis guidance."""

@abstractmethod
def get_recipe_prompt() -> str:
    """Phase 3: Parameter extraction + tagging instructions."""

@abstractmethod
def get_deepdive_prompt() -> str:
    """Phase 4: Critical analysis + claim-vs-evidence evaluation."""

@abstractmethod
def get_recipe_parameters() -> list[str]:
    """Return domain-specific parameter names (e.g., ['wavelength', 'power'])."""

def get_system_prompt(phase: str) -> str:
    """Dispatcher: retrieve prompt for a given phase name."""

def to_dict() -> dict:
    """Serialize agent to API response format."""
```

#### Agent Photon (Optics Specialist)

**Location**: `/sasoo/backend/services/agents/agent_photon.py`

**Domain**: Optics, Photonics, Laser Physics, Fiber Optics, Free-Space Optical (FSO) Communications, Imaging Systems, Spectroscopy

**Personality**: 반말 + Direct Honesty ("이거 봐봐", "이건 좀 이상해", "여기 잘했네")

**Phase Prompts**:
- **Screening**: Identifies optical keywords (wavelength, laser, beam, cavity, photon, etc.); classifies paper relevance within optics scope
- **Visual**: Checks graph axes (Linear vs Log scale), error bars, beam profiles, spectral data; flags suspicious scaling or missing uncertainty ranges
- **Recipe**: Extracts optical parameters: wavelength (λ), laser power (P), cavity Q-factor, fiber properties (SMF/MMF, NA, diameter), coupling efficiency, polarization, modulation frequency
- **DeepDive**: Validates error propagation in optical measurements, checks physical constraint violations (e.g., efficiency > 100%), compares vs. SOTA optical techniques

**Recipe Parameters**:
```python
[
    "wavelength",
    "laser_power",
    "pulse_duration",
    "repetition_rate",
    "cavity_finesse",
    "fiber_type",
    "coupling_efficiency",
    "beam_quality_M2",
    "polarization",
    "modulation_frequency",
    "detection_method",
    "signal_to_noise_ratio",
    "dark_count_rate",
]
```

#### Agent Cell (Biomedical Specialist)

**Location**: `/sasoo/backend/services/agents/agent_cell.py`

**Domain**: Cell Biology, Microscopy, Biomedical Engineering, Tissue Engineering, Drug Delivery

**Personality**: Careful, Protocol-Focused ("이 프로토콜 맞아?", "cell viability 어떻게 확인했어?")

**Phase Prompts**:
- **Screening**: Flags cell biology keywords (cell type, cultured/primary, assay, biocompatibility, etc.)
- **Visual**: Analyzes microscopy images (resolution, staining quality, cell morphology, artifact detection)
- **Recipe**: Extracts biomedical parameters: cell line, seeding density, culture medium, incubation time/temperature, assay protocol, detection threshold, animal model (if applicable)
- **DeepDive**: Checks biological plausibility, validates statistics on sample sizes, flags unreported controls, assesses reproducibility of live-cell imaging

**Recipe Parameters**:
```python
[
    "cell_type",
    "passage_number",
    "seeding_density",
    "culture_medium",
    "incubation_temperature",
    "incubation_duration",
    "assay_type",
    "antibody_primary",
    "antibody_secondary",
    "detection_method",
    "sample_size_n",
    "cell_viability",
    "staining_protocol",
]
```

#### Agent Neural (AI/ML Specialist)

**Location**: `/sasoo/backend/services/agents/agent_neural.py`

**Domain**: Deep Learning, Neural Networks, Computer Vision, NLP, Reinforcement Learning, ML Methods

**Personality**: Technical, Detail-Oriented ("이 loss function 왜 선택했어?", "training data bias 체크했어?")

**Phase Prompts**:
- **Screening**: Identifies ML keywords (neural network, CNN, Transformer, training, optimization, etc.)
- **Visual**: Analyzes training curves (convergence, overfitting), confusion matrices, loss landscapes, ROC curves
- **Recipe**: Extracts hyperparameters: architecture (layers, neurons, kernel size), optimizer (Adam, SGD), learning rate, batch size, regularization (L1/L2, dropout), initialization method
- **DeepDive**: Validates statistical test selections (t-test vs ANOVA), checks for data leakage, evaluates generalization bounds, flags cherry-picked results

**Recipe Parameters**:
```python
[
    "architecture",
    "num_layers",
    "hidden_units",
    "activation_function",
    "optimizer",
    "learning_rate",
    "batch_size",
    "epochs",
    "regularization",
    "dropout_rate",
    "weight_initialization",
    "training_data_size",
    "test_data_split",
    "loss_function",
]
```

---

## Working Instructions for AI Agents

### Phase 1: Screening (Triage)

**Input**: Abstract + Conclusion (minimal tokens)
**Model**: Gemini 3.0 Flash (low cost, fast)
**Cost**: ~$0.001 per paper
**Agent Overlay**: Domain-specific relevance keywords

**Expected Output**:
- Relevance score: High/Medium/Low
- Top 3 keywords
- 1-2 sentence summary
- Recommendation: Skip/Continue

**Quality Gate**: If Low relevance, user can skip Phase 2-4.

**Common Patterns**:
- Photon agent checks for λ, laser, cavity, FSO, beam terms
- Cell agent looks for "cell", "culture", "primary", "cell line" mentions
- Neural agent scans for "neural", "CNN", "Transformer", "training" keywords

---

### Phase 2: Visual Verification (Data Trust)

**Input**: Extracted figures (PNG/JPG) + captions
**Model**: Gemini 3.0 Flash Multimodal (image analysis)
**Cost**: ~$0.003 per paper
**Agent Overlay**: Domain-specific figure interpretation guidance

**Expected Output**:
- Per-figure interpretation
- Data quality assessment
- Suspicious patterns (log-scale tricks, missing error bars, outliers)
- Confidence score per figure

**Quality Gate**: If data quality is poor, flag in final report with [LOW_CONFIDENCE] tag.

**Common Patterns**:
- Photon: Checks for axes labels, log vs linear deception, missing wavelength specs
- Cell: Looks at microscopy resolution, color saturation, staining uniformity
- Neural: Validates curve smoothness, statistical noise levels, train/val divergence

---

### Phase 3: Recipe Extraction (Parameter Harvesting)

**Input**: Methods/Experimental section
**Model**: Gemini 3.0 Pro (high accuracy)
**Cost**: ~$0.008 per paper + variable output cost
**Agent Overlay**: Domain-specific parameter definitions + tagging rules

**Output Format**: Structured parameter table with tags:
```markdown
| Parameter | Value | Tag | Source |
|-----------|-------|-----|--------|
| Wavelength | 1064 nm | [EXPLICIT] | Methods, line 3 |
| Laser Power | 10 W | [EXPLICIT] | Table 1 |
| Cavity Finesse | ~50 | [INFERRED] | Implied by Q-factor calc |
| Thermal Drifts | Not mentioned | [MISSING] | ⚠️ |
```

**Tags**:
- `[EXPLICIT]`: Directly stated in paper
- `[INFERRED]`: Derived from other stated parameters (with assumption noted)
- `[MISSING]`: Critical param absent; reproducibility risk flagged

**Common Patterns**:
- Photon: Extracts wavelength, power, cavity specs, fiber details, efficiency measurements
- Cell: Harvests cell line ID, seeding density, medium formulation, assay endpoints
- Neural: Pulls architecture diagrams, hyperparameter grid, data split ratios

---

### Phase 4: Deep Dive (Critical Analysis)

**Input**: Introduction + Results & Discussion (full reasoning)
**Model**: Gemini 3.0 Pro (critical thinking)
**Cost**: ~$0.016 per paper + variable output cost
**Agent Overlay**: Domain-specific error propagation + validation rules

**Expected Output**:
- Research motivation (Why this approach?)
- Prior work comparison table
- Claim-vs-Evidence table
- Limitations identified
- Suggested future work

**Quality Gate**: Flags papers with **unsubstantiated claims** or **physical impossibilities**.

**Common Patterns**:
- Photon: Checks diffraction-limit violations, computes SNR math, validates Fresnel numbers
- Cell: Assesses cell viability statistics, control group completeness, staining quality assumptions
- Neural: Verifies overfitting detection (val loss trends), checks data augmentation justification

---

## Testing Requirements for Agents

### Unit Tests
Each agent must pass:
1. **Info Serialization**: `agent.to_dict()` returns all required fields
2. **Prompt Coherence**: Each phase prompt is non-empty and domain-relevant
3. **Recipe Parameters**: Parameter list matches domain (e.g., Photon has 13+ optical params)

### Integration Tests
1. **Phase Dispatch**: `AnalysisPipeline` correctly routes agent → phase prompt
2. **Visualization Router**: Phase 3/4 outputs trigger correct viz selection (Mermaid vs PaperBanana)
3. **Token Accounting**: LLM client correctly accumulates tokens across all phases

### E2E Tests
1. **Sample Paper Analysis**: Run 1-2 real papers per agent domain through full 4-phase pipeline
2. **Output Completeness**: Verify markdown report, recipe table, figures, and mermaid/paperbanana outputs are generated
3. **Cost Validation**: Total cost per paper is within budget (expected: $0.025-0.05 USD per paper)

### Test Data
- `/sasoo/backend/services/test_parser_example.py`: Example test harness
- `/doc/PaperBanana.pdf`: Reference for illustration verification
- Sample papers: Stored in `outputs/` with expected outputs

---

## Common Agent Patterns & Usage

### Pattern 1: Custom Agent Addition

To add a new domain agent (e.g., Chemistry):

1. Create `/sasoo/backend/services/agents/agent_chem.py`:
```python
from services.agents.base_agent import AgentInfo, BaseAgent

class AgentChem(BaseAgent):
    @property
    def info(self) -> AgentInfo:
        return AgentInfo(
            name="chem",
            domain="chemistry",
            display_name="Agent Chem",
            display_name_ko="켐 에이전트",
            description="Synthetic chemistry & materials characterization specialist",
            description_ko="...",
            personality="...",
            icon="chem",
        )

    def get_screening_prompt(self) -> str:
        return "Look for synthesis, reaction, molecular weight, yield keywords..."

    # ... implement visual, recipe, deepdive ...

    def get_recipe_parameters(self) -> list[str]:
        return ["temperature", "pressure", "catalyst", "reaction_time", ...]
```

2. Register in domain router:
```python
# services/domain_router.py
AGENT_REGISTRY = {
    "optics": AgentPhoton(),
    "biology": AgentCell(),
    "neural": AgentNeural(),
    "chemistry": AgentChem(),  # NEW
}
```

3. Add YAML profile template:
```bash
mkdir -p ~/sasoo-library/agent_profiles
cat > ~/sasoo-library/agent_profiles/chem_default.yaml <<EOF
agent_name: chem
domain: chemistry
display_name: Agent Chem
recipe_parameters:
  - temperature
  - pressure
  - catalyst
EOF
```

### Pattern 2: Prompt Customization

Users can override phase prompts via YAML profile without code changes:

```yaml
# ~/sasoo-library/agent_profiles/photon_custom.yaml
agent_name: photon
domain: optics
prompts:
  screening: |
    For optics papers, prioritize free-space optical communication and ignore fiber-optic theory.
  recipe: |
    Extract only: wavelength, power, BER. Ignore cavity parameters.
```

### Pattern 3: Recipe Parameter Extraction

The `get_recipe_parameters()` method defines what a domain expert cares about:

```python
def get_recipe_parameters(self) -> list[str]:
    # These become the column headers in the auto-generated recipe table
    return [
        "wavelength",
        "laser_power",
        "pulse_duration",
        "cavity_finesse",
        "coupling_efficiency",
    ]
```

The Gemini Pro API is instructed to extract ONLY these fields, reduce hallucination, and tag with `[EXPLICIT]`, `[INFERRED]`, or `[MISSING]`.

---

## Dependencies

### Internal Dependencies

| Component | Depends On | Reason |
|-----------|-----------|--------|
| `AnalysisPipeline` | BaseAgent + GeminiClient + ClaudeClient + VizRouter | Orchestration |
| `VizRouter` | MermaidGenerator + PaperBananaBridge | Visualization dispatch |
| `MermaidGenerator` | ClaudeClient | Mermaid code generation |
| `PaperBananaBridge` | `paperbanana` (pip) + GeminiClient | Illustration generation |
| API routers | AnalysisPipeline + DatabaseLayer | Paper analysis endpoints |
| DomainRouter | Agent Registry + ProfileLoader | Agent selection + customization |

### External Dependencies

#### Python Backend

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | Latest | Web framework |
| `uvicorn` | Latest | ASGI server |
| `aiosqlite` | Latest | Async SQLite |
| `pydantic` | Latest | Data validation |
| `google-genai` | Latest | Gemini API client |
| `anthropic` | Latest | Claude API client |
| `paperbanana` | Via `pip install` | Publication-quality illustration library |
| `pymupdf` (fitz) | Latest | PDF text extraction |
| `pdf2image` | Latest | PDF → PNG conversion for figures |
| `pyyaml` | Latest | YAML profile parsing |
| `dotenv` | Latest | .env file loading |

#### JavaScript/Frontend

| Package | Version | Purpose |
|---------|---------|---------|
| `react` | 18.2.0 | UI framework |
| `typescript` | 5.3.3 | Type safety |
| `vite` | 5.0.12 | Build tool |
| `react-markdown` | 9.0.1 | Render markdown reports |
| `mermaid` | 10.7.0 | Render mermaid diagrams |
| `@react-pdf-viewer` | 3.12.0 | PDF viewing |
| `tailwindcss` | 3.4.1 | CSS utility framework |
| `lucide-react` | 0.312.0 | Icon library |

#### Electron Core

| Package | Version | Purpose |
|---------|---------|---------|
| `electron` | 28.2.1 | Desktop framework |
| `electron-builder` | 24.13.3 | App packaging |
| `electron-store` | 8.2.0 | Local config persistence |

#### APIs

| Service | Key Storage | Auth |
|---------|-------------|------|
| Google Gemini 3.0 | `~/.sasoo-library/config.json` | `gemini_api_key` env var |
| Anthropic Claude | Sonnet 4.5 | `ANTHROPIC_API_KEY` env var |

---

## Manual Operations

### Initial Setup

**For Developers**:

```bash
# Backend setup
cd sasoo/backend
pip install -r requirements.txt
export GEMINI_API_KEY="your-key-here"
export ANTHROPIC_API_KEY="your-key-here"

# Frontend setup
cd ../frontend
pnpm install

# Run dev environment
cd ..
pnpm dev
```

This spawns:
- Electron main process (TypeScript, watches electron/)
- Frontend dev server (Vite, port 5173)
- Backend FastAPI (Python, port 8000) via electron/python-manager.ts

### Adding a New Agent

1. Create agent class in `/sasoo/backend/services/agents/agent_*.py`
2. Add to domain router registry
3. Create YAML template in `~/sasoo-library/agent_profiles/`
4. Write unit + integration tests
5. Verify phase prompts + recipe parameter list completeness

### Running Analysis on a Paper

**Via API**:
```bash
curl -X POST http://localhost:8000/api/analysis/start \
  -F "pdf=@paper.pdf" \
  -F "domain=optics" \
  -F "agent=photon"
```

**Via UI**:
1. Open Sasoo desktop app
2. Upload PDF
3. Select domain (auto-detects via agent classification)
4. Click "Analyze"
5. Watch 4-phase progress in real time
6. Review markdown report + figures in Results panel

### Exporting Results

Results are auto-saved to:
```
~/sasoo-library/
├── papers/{paper_id}/
│   ├── original.pdf
│   ├── analysis_report.md
│   ├── recipe_card.csv
│   ├── figures/
│   │   ├── figure_01.png
│   │   ├── figure_02.png
│   │   └── ...
│   ├── mermaid/
│   │   ├── diagram_01.mmd
│   │   └── ...
│   └── paperbanana/
│       ├── illustration_01.png
│       └── ...
├── sasoo.db
└── config.json
```

### Customizing Agent Behavior

1. Edit YAML profile:
```bash
nano ~/sasoo-library/agent_profiles/photon_default.yaml
```

2. Modify recipe parameters, display names, or add prompt overrides
3. Restart app (changes auto-reload on next analysis)

### Database Inspection

```bash
sqlite3 ~/sasoo-library/sasoo.db
> SELECT * FROM papers WHERE domain='optics' LIMIT 5;
> SELECT * FROM analysis_results WHERE phase='screening';
```

### Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `GEMINI_API_KEY` | Google Gemini API key | `AIza...` |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key | `sk-ant-...` |
| `SASOO_LIBRARY` | Override default library path | `/custom/path` |
| `SASOO_DEBUG` | Enable debug logging | `true` |

---

## Roadmap & Future Phases

### v0.2 (Next)
- [ ] Add Agent Chemistry (synthesis papers)
- [ ] Add Agent Materials (materials science)
- [ ] Implement user preference learning (agent selection history)
- [ ] Add search/filter across analyzed papers

### v0.3
- [ ] Support multi-paper batch analysis with parallel processing
- [ ] Implement paper comparison mode (2-3 papers side-by-side)
- [ ] Add annotation tools for user markup on figures

### v1.0
- [ ] Cloud sync (optional) for cross-device library access
- [ ] Publish-ready report export (PDF, HTML, Jupyter)
- [ ] Team collaboration features (shared library, comments)
- [ ] Plugin system for custom agents

---

## Troubleshooting

### API Key Issues

**Error**: `403 Unauthorized` for Gemini API

**Fix**: Verify API key in `~/.sasoo-library/config.json`:
```json
{
  "gemini_api_key": "AIza...",
  "anthropic_api_key": "sk-ant-..."
}
```

### Database Corruption

**Error**: `DatabaseError: disk I/O error`

**Fix**: Replace `~/sasoo-library/sasoo.db`:
```bash
rm ~/sasoo-library/sasoo.db
# Restart app (DB will reinitialize)
```

### Memory Leaks in Electron

**Symptom**: App slows down after 5+ analyses

**Mitigation**: Electron subprocess cleanup in `python-manager.ts` includes kill timeout. Check Task Manager for orphaned Python processes.

### Agent Not Found

**Error**: `AgentNotFoundError: domain 'materials' not in AGENT_REGISTRY`

**Fix**: Register agent in `/sasoo/backend/services/domain_router.py`

---

## Contact & Support

- **Maintainer**: DJ (dosigner)
- **Repository**: Local Electron desktop app
- **Issues**: Tracked in project outputs/
- **Documentation**: See `/PRD_Sasoo_v3.0.md` for full specification

---

**Last Updated**: 2026-02-07
