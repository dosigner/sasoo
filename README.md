# Sasoo (사수)

AI-powered academic paper analysis desktop application. Transforms PDF research papers into structured insights through a 4-phase multi-agent analysis pipeline with 70-80% token savings.

"사수" means "senior mentor" in Korean — your AI research assistant.

## Features

- **PDF Processing** — Text, figure, table extraction with metadata parsing
- **Multi-Agent Analysis** — Domain-specific AI agents (Optics, AI/ML, Biology) with tailored prompts
- **4-Phase Pipeline** — Screening → Visual Verification → Recipe Extraction → Deep Dive
- **Dual LLM Strategy** — Gemini for analysis, Claude for Mermaid diagram generation
- **Visualization** — Mermaid diagrams (structural) + PaperBanana illustrations (visual)
- **Recipe Cards** — Structured experimental protocols with [EXPLICIT]/[INFERRED]/[MISSING] parameter tagging
- **Smart Domain Classification** — Hybrid keyword + semantic classification with ambiguity detection
- **Korean-First Output** — All analysis results in Korean with domain-appropriate personality

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Frontend** | React 18, TypeScript, Vite 5, Tailwind CSS 3.4 |
| **Desktop** | Electron 28 |
| **Backend** | Python, FastAPI, aiosqlite |
| **LLM** | Google Gemini (Flash/Pro), Anthropic Claude Sonnet 4.5 |
| **PDF** | PyMuPDF (fitz), pdfplumber |
| **Visualization** | Mermaid 10.7, PaperBanana |

## Project Structure

```
sasoo/
├── backend/                       # Python FastAPI backend
│   ├── main.py                    # Entry point (port 8000)
│   ├── api/
│   │   ├── papers.py              # Paper upload, CRUD
│   │   ├── analysis.py            # Analysis pipeline endpoints
│   │   └── settings.py            # Settings & API cost tracking
│   ├── models/
│   │   ├── database.py            # SQLite async layer
│   │   └── schemas.py             # Pydantic models
│   ├── services/
│   │   ├── analysis_pipeline.py   # 4-phase orchestration
│   │   ├── domain_router.py       # Domain classification
│   │   ├── pdf_parser.py          # PDF extraction
│   │   ├── report_generator.py    # Markdown report generation
│   │   ├── agents/                # Domain-specific agents
│   │   │   ├── base_agent.py      # Abstract base class
│   │   │   ├── agent_photon.py    # Optics specialist
│   │   │   ├── agent_neural.py    # AI/ML specialist
│   │   │   └── agent_cell.py      # Biology specialist
│   │   ├── llm/                   # LLM clients
│   │   │   ├── gemini_client.py   # Gemini wrapper
│   │   │   └── claude_client.py   # Claude wrapper
│   │   └── viz/                   # Visualization services
│   │       ├── viz_router.py      # Visualization target routing
│   │       ├── mermaid_generator.py
│   │       └── paperbanana_bridge.py
│   └── requirements.txt
├── frontend/                      # React frontend
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── Upload.tsx         # PDF upload
│   │   │   ├── Library.tsx        # Paper library
│   │   │   ├── Workbench.tsx      # Analysis workbench
│   │   │   └── Settings.tsx       # Settings
│   │   └── components/
│   └── package.json
├── electron/                      # Electron wrapper
│   └── main.ts
└── package.json
```

## Analysis Pipeline

```
PDF Upload → Domain Classification → Agent Selection
                                         ↓
              Phase 1: Screening (Abstract + Conclusion, ~10-20s)
                                         ↓
              Phase 2: Visual Verification (Figures, ~30-60s)
                                         ↓
              Phase 3: Recipe Extraction (Methods, ~20-40s)
                                         ↓
              Phase 4: Deep Dive (Results & Discussion, ~60-120s)
                                         ↓
              Visualization (Mermaid + PaperBanana)
                                         ↓
              Report Generation (Markdown)
```

### Agents

| Agent | Domain | Specialization |
|-------|--------|----------------|
| **Photon** | Optics & Photonics | Laser systems, beam propagation, FSO, spectroscopy |
| **Neural** | AI & Machine Learning | Neural networks, transformers, CV, NLP |
| **Cell** | Biology & Biochemistry | Cell biology, Western blot, PCR, CRISPR |

## Data Storage

```
~/sasoo-library/
├── sasoo.db              # SQLite database
├── papers/               # Uploaded PDFs & analysis reports
├── figures/              # Extracted figure images
├── paperbanana/          # Generated illustrations
└── exports/              # Exported reports
```

## Setup

### Prerequisites

- Node.js 18+
- Python 3.10+
- pnpm

### Installation

```bash
# Backend
cd sasoo/backend
pip install -r requirements.txt

# Frontend
cd sasoo/frontend
pnpm install

# Root (Electron)
cd sasoo
pnpm install
```

### Environment Variables

Copy `sasoo/backend/.env.example` to `sasoo/backend/.env` and fill in:

```env
GEMINI_API_KEY=your_gemini_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
```

### Run

```bash
# Backend (http://localhost:8000)
cd sasoo/backend
python main.py

# Frontend dev (http://localhost:5173)
cd sasoo/frontend
pnpm dev

# Electron desktop app
cd sasoo
pnpm dev
```

## API Endpoints

### Papers
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/papers/upload` | Upload PDF |
| `GET` | `/api/papers` | List papers |
| `GET` | `/api/papers/{id}` | Get paper details |
| `DELETE` | `/api/papers/{id}` | Delete paper |

### Analysis
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/analysis/{id}/start` | Start analysis |
| `GET` | `/api/analysis/{id}/status` | Get progress |
| `GET` | `/api/analysis/{id}/results` | Get results |
| `GET` | `/api/analysis/{id}/figures` | List figures |

### Settings
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/settings` | Get settings |
| `PATCH` | `/api/settings` | Update settings |
| `GET` | `/api/settings/costs` | API cost stats |

## License

Private
