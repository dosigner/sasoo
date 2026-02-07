<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# Sasoo Monorepo

Sasoo is an AI Co-Scientist desktop application for academic paper analysis. The application uses a fullstack architecture with Electron for desktop, React+TypeScript for UI, and Python FastAPI for backend multi-agent analysis.

---

## Purpose

This guide helps AI agents understand the Sasoo monorepo structure, key dependencies, build system, and development workflow. Use this to navigate codebases, understand component relationships, and execute development tasks efficiently.

---

## Architecture Overview

```
Sasoo (Monorepo)
├── frontend/           # React + TypeScript + Vite web UI
├── electron/           # Electron desktop wrapper (TypeScript)
├── backend/            # Python FastAPI multi-agent analysis engine
├── tests/              # Test suites (reserved)
├── package.json        # Monorepo scripts & build config
├── tsconfig.json       # Root TypeScript config
└── pnpm-lock.yaml      # Dependency lock file
```

### Architecture Pattern

- **Desktop:** Electron wraps React frontend and manages native OS integration (file dialogs, app lifecycle)
- **IPC Bridge:** Electron's IPC layer bridges frontend and Python backend
- **Backend:** FastAPI server (port 8000) runs Python analysis agents
- **Database:** SQLite database for paper metadata and analysis results
- **Build:** pnpm monorepo with concurrent development scripts

---

## Key Files

### Monorepo Root

| File | Purpose |
|------|---------|
| `package.json` | Monorepo definition, build scripts, Electron config, electron-builder packaging |
| `tsconfig.json` | Root TypeScript compiler configuration (targets ES2022, CommonJS) |
| `pnpm-lock.yaml` | Locked dependency versions (pnpm monorepo) |

### Build & Configuration

**Key scripts from `package.json`:**
- `pnpm dev` - Run frontend dev server + Electron dev mode concurrently
- `pnpm dev:frontend` - Start Vite dev server on port 5173
- `pnpm dev:electron` - Compile TypeScript and launch Electron
- `pnpm build` - Build frontend, compile electron TS, run electron-builder
- `pnpm start` - Launch built Electron app
- `pnpm clean` - Remove dist directories

**Electron builder config:**
- **App ID:** `com.dosigner.sasoo`
- **Product name:** Sasoo
- **Targets:**
  - macOS: dmg, zip
  - Windows: nsis, portable
  - Linux: AppImage, deb
- **Bundles:** Frontend (dist/), Electron (dist-electron/), Backend (backend/)

---

## Subdirectories

### 1. Frontend (`/frontend/`)

**Technology Stack:** React 18, TypeScript 5.3, Vite, Tailwind CSS, Lucide Icons

**Structure:**
```
frontend/
├── src/
│   ├── main.tsx              # React entry point
│   ├── App.tsx               # Root app component + routing
│   ├── components/           # Reusable React components
│   │   ├── ProgressTracker.tsx
│   │   ├── PdfViewer.tsx
│   │   ├── RecipeCard.tsx
│   │   ├── MermaidRenderer.tsx
│   │   └── ...
│   ├── pages/                # Route pages
│   │   ├── Workbench.tsx     # Analysis workbench
│   │   ├── Settings.tsx      # Settings page
│   │   └── ...
│   ├── hooks/                # Custom React hooks
│   │   ├── usePapers.ts      # Paper CRUD operations
│   │   ├── useAnalysis.ts    # Analysis workflow
│   │   └── ...
│   └── index.css             # Global styles
├── vite.config.ts            # Vite bundler config
├── tsconfig.json             # Frontend TS config
├── tailwind.config.js        # Tailwind CSS setup
├── postcss.config.js         # PostCSS plugins
├── index.html                # HTML template
└── package.json              # Frontend dependencies
```

**Key Features:**
- **Upload:** PDF file upload interface
- **Library:** Paper management and browsing
- **Workbench:** Interactive paper analysis UI with real-time visualizations
- **Settings:** Application configuration (API keys, analysis parameters)
- **Responsive Design:** Dark mode, sidebar navigation

**Key Dependencies:**
- `react-router-dom` - Client-side routing
- `tailwindcss` - Utility-first CSS framework
- `lucide-react` - Icon library
- `mermaid` - Diagram rendering (for visualizations)
- `pdfjs-dist` - PDF viewing

**Build Output:** `frontend/dist/` (bundled HTML/CSS/JS)

---

### 2. Electron (`/electron/`)

**Technology Stack:** Electron 28.2.1, TypeScript, IPC (Inter-Process Communication)

**Files:**
```
electron/
├── main.ts                   # Electron main process entry
├── preload.ts               # Preload script for context isolation
├── python-manager.ts        # Python backend process manager
└── tsconfig.json            # Electron TS config
```

**Main Responsibilities:**

1. **main.ts**
   - Creates BrowserWindow for React frontend
   - Registers IPC handlers for frontend-backend communication
   - Manages app lifecycle (ready, window-all-closed, activate, before-quit)
   - Handles file dialogs, file read/write operations
   - Proxies API calls to FastAPI backend (http://localhost:8000)
   - Security: Context isolation, preload script, no nodeIntegration

2. **python-manager.ts**
   - Spawns Python FastAPI process
   - Monitors Python process health
   - Handles startup/shutdown on app lifecycle events

3. **preload.ts**
   - Exposes safe API to frontend via contextBridge
   - Defines IPC channels for frontend use

**IPC Channels (Frontend → Electron → Backend):**
| Channel | Method | Purpose |
|---------|--------|---------|
| `dialog:openFile` | async | File picker for PDF upload |
| `dialog:saveFile` | async | Save dialog for exports |
| `file:read` | async | Read file as base64 buffer |
| `file:readText` | async | Read file as text |
| `file:write` | async | Write text file |
| `papers:upload` | async | Upload PDF to backend |
| `papers:getAll` | async | Fetch all papers |
| `papers:get` | async | Fetch single paper by ID |
| `papers:delete` | async | Delete paper from library |
| `analysis:run` | async | Trigger analysis on backend |
| `analysis:getStatus` | async | Check analysis progress |
| `settings:get` | async | Fetch app settings |
| `settings:update` | async | Update app settings |
| `backend:health` | async | Check if backend is healthy |
| `app:getInfo` | async | Get app version, platform info |
| `app:getPath` | async | Get user data paths |

**Build Output:** `dist-electron/main.js` (compiled CommonJS)

---

### 3. Backend (`/backend/`)

**Technology Stack:** Python 3.9+, FastAPI, SQLAlchemy ORM, Claude API / Gemini API

**Structure:**
```
backend/
├── main.py                       # FastAPI app entry point
├── models/
│   ├── database.py              # Database init, SQLAlchemy setup
│   ├── paper.py                 # Paper SQLAlchemy model
│   └── schemas.py               # Pydantic request/response schemas
├── api/
│   ├── __init__.py
│   ├── papers.py                # /api/papers endpoints
│   ├── analysis.py              # /api/analysis endpoints
│   └── settings.py              # /api/settings endpoints
├── services/
│   ├── pdf_parser.py            # PDF text extraction
│   ├── section_splitter.py      # Section identification
│   ├── analysis_pipeline.py     # Main analysis orchestration
│   ├── paper_library.py         # Paper CRUD logic
│   ├── report_generator.py      # Result formatting
│   ├── domain_router.py         # Route paper to agent
│   ├── agents/
│   │   ├── base_agent.py        # Agent base class
│   │   ├── agent_photon.py      # Physics domain agent
│   │   ├── agent_neural.py      # Neuroscience domain agent
│   │   ├── agent_cell.py        # Cell biology domain agent
│   │   └── profile_loader.py    # Load agent profiles
│   ├── llm/
│   │   ├── claude_client.py     # Anthropic Claude API
│   │   └── gemini_client.py     # Google Gemini API
│   ├── viz/
│   │   ├── mermaid_generator.py # Generate Mermaid diagrams
│   │   ├── paperbanana_bridge.py # PaperBanana visualization
│   │   └── viz_router.py        # Visualization routing
│   └── README.md                # Services layer documentation
├── agent_profiles/              # YAML agent configurations
├── requirements.txt             # Python dependencies
└── .env (optional)              # Environment variables
```

**Key Components:**

1. **Database Layer** (`models/`)
   - SQLite database: `~/.sasoo/sasoo.db`
   - Paper table: stores metadata, content, analysis results
   - Paths: PAPERS_DIR, FIGURES_DIR, PAPERBANANA_DIR

2. **API Layer** (`api/`)
   - `/api/papers` - CRUD operations on papers
   - `/api/analysis` - Run/status analysis jobs
   - `/api/settings` - Get/update app settings

3. **Services Layer** (`services/`)
   - **pdf_parser.py** - Extract text/structure from PDFs
   - **section_splitter.py** - Identify paper sections
   - **analysis_pipeline.py** - Orchestrate analysis workflow
   - **domain_router.py** - Route to appropriate agent based on domain
   - **agents/** - Domain-specific LLM agents (Physics, Neuroscience, Biology)
   - **llm/** - LLM client abstractions (Claude, Gemini)
   - **viz/** - Visualization generation (Mermaid diagrams, PaperBanana)

4. **Agent System**
   - Multi-agent architecture with domain specialization
   - Agents can be customized via YAML profiles
   - Each agent inherits from BaseAgent
   - LLM-powered analysis (Claude API preferred)

**Key Endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/papers` | GET | List all papers |
| `GET /api/papers/{id}` | GET | Get paper details |
| `POST /api/papers/upload` | POST | Upload PDF file |
| `DELETE /api/papers/{id}` | DELETE | Delete paper |
| `POST /api/analysis/run` | POST | Run analysis on paper |
| `GET /api/analysis/{id}/status` | GET | Check analysis progress |
| `GET /api/settings` | GET | Get app settings |
| `PUT /api/settings` | PUT | Update settings |

**Environment Variables:**
- `CLAUDE_API_KEY` - Anthropic API key (required for Claude agents)
- `GEMINI_API_KEY` - Google Gemini API key (optional)
- `LIBRARY_ROOT` - Paper storage directory (default: ~/.sasoo)

---

### 4. Tests (`/tests/`)

**Status:** Reserved for future test suites.

**Expected Structure (when populated):**
```
tests/
├── unit/              # Unit tests for services
├── integration/       # Integration tests (frontend-backend)
├── e2e/              # End-to-end tests
└── fixtures/         # Test data
```

---

## Dependencies

### Monorepo Root (`package.json`)

**Runtime:**
- `electron-store ^8.2.0` - Persistent app configuration storage

**Dev:**
- `electron ^28.2.1` - Desktop app framework
- `electron-builder ^24.13.3` - App packaging and installer creation
- `typescript ^5.3.3` - TypeScript compiler
- `concurrently ^8.2.2` - Run multiple processes concurrently
- `@types/node ^20.11.16` - Node.js type definitions

### Frontend (`frontend/package.json`)

**Runtime:**
- `react ^18` - UI framework
- `react-router-dom` - Client-side routing
- `tailwindcss` - CSS framework
- `lucide-react` - Icon library
- `mermaid` - Diagram rendering
- `pdfjs-dist` - PDF viewer

**Dev:**
- `vite` - Frontend bundler
- `typescript` - TypeScript support
- `postcss` - CSS processing
- `autoprefixer` - CSS vendor prefixes

### Backend (`backend/requirements.txt`)

**Core:**
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `sqlalchemy` - ORM
- `pydantic` - Data validation
- `python-dotenv` - Environment configuration

**PDF Processing:**
- `pdfplumber` - PDF text extraction
- `PyPDF2` - PDF manipulation

**AI/ML:**
- `anthropic` - Claude API client
- `google-generativeai` - Gemini API client

**Utilities:**
- `aiofiles` - Async file operations
- `python-multipart` - Form data parsing

---

## Development Workflow

### Getting Started

1. **Install dependencies:**
   ```bash
   cd /home/dosigner/논문/sasoo
   pnpm install
   ```

2. **Set environment variables:**
   ```bash
   cd backend
   cp .env.example .env  # or create .env with API keys
   # Add: CLAUDE_API_KEY=your_key
   ```

3. **Run dev mode:**
   ```bash
   pnpm dev
   ```
   This starts:
   - Frontend dev server (Vite on http://localhost:5173)
   - Electron with live reload
   - Python backend on http://localhost:8000

### Common Tasks

**Frontend development:**
```bash
pnpm dev:frontend
# Edit files in frontend/src/, changes hot-reload
```

**Backend development:**
```bash
cd backend
python main.py
# FastAPI auto-reloads on file changes
```

**Electron/IPC debugging:**
```bash
pnpm dev:electron:watch
# Watches electron/main.ts, rebuilds on changes
# Launch Electron manually to see logs
```

**Production build:**
```bash
pnpm build
# Creates native installers in dist/
# - macOS: Sasoo-{version}.dmg, Sasoo-{version}.zip
# - Windows: Sasoo Setup {version}.exe, Sasoo {version}.exe
# - Linux: Sasoo-{version}.AppImage, sasoo_{version}.deb
```

**Clean build artifacts:**
```bash
pnpm clean
# Removes dist/, dist-electron/, frontend/dist/
```

---

## For AI Agents

### Code Organization Patterns

**Frontend:**
- Pages in `src/pages/` (route-aligned)
- Components in `src/components/` (reusable UI)
- Hooks in `src/hooks/` (custom React logic)
- Routing via React Router in `App.tsx`
- State management via hooks (useState, useEffect, useCallback)

**Backend:**
- API endpoints use FastAPI decorators (`@app.get()`, `@app.post()`)
- Services are imported and called from route handlers
- SQLAlchemy models define database schema
- Pydantic schemas validate request/response data
- Agents inherit from BaseAgent, implement `analyze()` method

**Electron:**
- IPC handlers defined in `main.ts` with `ipcMain.handle()`
- Frontend calls via `window.api.{channelName}()` (from preload)
- All IPC is async (Promise-based)
- File operations use `fs.promises` for non-blocking I/O

### Common Development Tasks

**Add a new API endpoint:**
1. Create route handler in `backend/api/{feature}.py`
2. Define Pydantic schema in `backend/models/schemas.py`
3. Register route in `backend/main.py`
4. Add IPC handler in `electron/main.ts`
5. Call from frontend hook via `window.api.{channelName}`

**Add a new React page:**
1. Create component in `frontend/src/pages/{name}.tsx`
2. Add route in `frontend/src/App.tsx` (Routes section)
3. Add nav item to NAV_ITEMS if needed

**Add a new domain agent:**
1. Create `backend/services/agents/agent_{domain}.py` (inherit BaseAgent)
2. Create YAML config in `backend/agent_profiles/{domain}.yaml`
3. Register in domain router (`backend/services/domain_router.py`)

**Debugging:**
- **Frontend:** Use React DevTools, browser console (Electron DevTools opens by default in dev)
- **Backend:** Print to stdout (appears in Electron/terminal), use FastAPI docs at http://localhost:8000/docs
- **IPC:** Log in main.ts handlers and frontend code
- **Electron:** `mainWindow.webContents.openDevTools()` shows frontend console and backend logs

### Key Navigation

| Task | File(s) |
|------|---------|
| View all routes | `frontend/src/App.tsx` (Routes element) |
| Add API endpoint | `backend/api/{feature}.py` + `backend/main.py` |
| Modify database schema | `backend/models/{model}.py` |
| Add IPC channel | `electron/main.ts` (ipcMain.handle section) |
| Change app icon | `build/icon.png` or `build/icon.ico` |
| Modify app name/ID | `package.json` (build section) |
| Add backend dependency | `backend/requirements.txt` |
| Add frontend dependency | `frontend/package.json` |

### Important Notes

1. **Backend runs on port 8000** - All frontend IPC calls proxy to http://localhost:8000
2. **Frontend dev server runs on port 5173** - Configured in `electron/main.ts` (VITE_DEV_SERVER_URL)
3. **Context isolation enabled** - Frontend can't access Node.js APIs directly; use IPC
4. **Database location** - Papers stored in `~/.sasoo/` on user's machine
5. **Backend resources** - In production build, backend files bundled via `electron-builder.extraResources`
6. **TypeScript strict mode** - All root tsconfig has `"strict": true` - maintain this
7. **CORS enabled** - Backend allows requests from frontend (localhost)

---

## Build System Details

### electron-builder Configuration

The app is configured for cross-platform builds:

```json
{
  "appId": "com.dosigner.sasoo",
  "productName": "Sasoo",
  "files": [
    "dist-electron/**/*",
    "frontend/dist/**/*",
    "backend/**/*"
  ]
}
```

**Build process:**
1. `pnpm build:frontend` - Vite builds React to `frontend/dist/`
2. `pnpm build:electron` - TypeScript compiles to `dist-electron/`
3. `electron-builder` - Creates native installers

**Output locations:**
- **macOS:** `dist/Sasoo-{version}.dmg` (installer), `.zip` (portable)
- **Windows:** `dist/Sasoo Setup {version}.exe` (installer), portable exe
- **Linux:** `dist/Sasoo-{version}.AppImage` (portable), `.deb` (package)

---

## Version Information

| Tool | Version |
|------|---------|
| Electron | ^28.2.1 |
| TypeScript | ^5.3.3 |
| React | ^18 |
| Node.js (required) | 16+ (14+ for older Electron) |
| Python | 3.9+ |
| pnpm | 8+ (recommended) |

---

## Related Documentation

- **Parent Guide:** `../AGENTS.md` (if available)
- **Services Details:** `backend/services/README.md`
- **PRD:** `../PRD_Sasoo_v3.0.md` (project requirements)

---

Last updated: 2026-02-07
