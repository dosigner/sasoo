<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# Backend

## Purpose
Python FastAPI backend service for Sasoo AI Co-Scientist. Provides REST API for paper analysis, PDF parsing, AI-powered research assistance, and library management. Runs on localhost:8000.

## Key Files
| File | Description |
|------|-------------|
| main.py | FastAPI application entry point with lifespan management, CORS configuration, static file serving |
| requirements.txt | Python dependencies (FastAPI, PyMuPDF, pdfplumber, google-genai, anthropic, paperbanana, pydantic, aiosqlite, Pillow) |
| .env.example | Environment variable template for API keys (Gemini, Anthropic, OpenAI) |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| api/ | FastAPI route handlers for REST endpoints |
| models/ | Database schema, Pydantic models, data classes |
| services/ | Core business logic (PDF parsing, analysis pipeline, report generation) |
| agent_profiles/ | YAML configuration files for domain-specific AI agents |

## For AI Agents

### Working In This Directory
- Entry point: `uvicorn main:app --reload`
- Database location: `~/sasoo-library/sasoo.db`
- All database operations use async SQLite via aiosqlite
- CORS configured to allow all origins in development
- API routes mounted with `/api` prefix

### Testing Requirements
- Run backend server: `uvicorn main:app --reload`
- Access API docs: http://localhost:8000/docs
- Verify database initialization on first startup
- Test CORS by making requests from frontend

### Common Patterns
- Async/await for all I/O operations
- Singleton database connection pattern
- Lifespan context manager for startup/shutdown
- Environment variables loaded from .env file
- Static files served from ../frontend/dist

## Dependencies

### Internal
- api/ for route handlers
- models/ for data schemas and database
- services/ for business logic
- agent_profiles/ for AI agent configurations

### External
- FastAPI: Web framework
- uvicorn: ASGI server
- aiosqlite: Async SQLite driver
- PyMuPDF (fitz): PDF text extraction
- pdfplumber: PDF table/figure extraction
- google-generativeai: Gemini API client
- anthropic: Claude API client
- paperbanana: Scientific figure generation
- pydantic: Data validation
- Pillow: Image processing

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
