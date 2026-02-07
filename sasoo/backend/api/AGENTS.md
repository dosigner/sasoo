<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# API

## Purpose
FastAPI route handlers implementing REST API endpoints for paper management, analysis pipeline, and settings.

## Key Files
| File | Description |
|------|-------------|
| __init__.py | Package initialization |
| analysis.py (40KB) | Analysis pipeline endpoints: run/monitor/retrieve 4-phase analysis (screening, visual, recipe, deep_dive), Mermaid diagram generation, report generation, cost tracking |
| papers.py (16KB) | Paper CRUD: upload PDF, list/get/update/delete papers, domain classification heuristic |
| settings.py (13KB) | Settings management: API keys, default domain, theme, budget. Agent profile CRUD endpoints. Defaults: gemini_model="gemini-2.5-flash", anthropic_model="claude-sonnet-4-20250514" |

## Subdirectories
None

## For AI Agents

### Working In This Directory
- All routers use prefix `/api/{resource}`
- Import Pydantic schemas from `models/schemas.py`
- Database operations via helpers in `models/database.py`
- Use async route handlers for all I/O operations
- Return proper HTTP status codes (200, 201, 404, 500)

### Testing Requirements
- Access interactive docs: http://localhost:8000/docs
- Test upload: POST /api/papers with multipart/form-data
- Test analysis: POST /api/analysis/run/{paper_id}
- Monitor progress: GET /api/analysis/status/{paper_id}
- Verify database persistence after operations

### Common Patterns
- Router pattern: `router = APIRouter(prefix="/api/resource")`
- Async handlers: `async def endpoint(...):`
- Error handling with HTTPException
- Database transactions wrapped in try/except
- JSON response formatting with Pydantic models
- File upload handling with UploadFile type

## Dependencies

### Internal
- models/schemas.py: Pydantic request/response models
- models/database.py: Database operations
- services/analysis_pipeline.py: Analysis orchestration
- services/pdf_parser.py: PDF parsing
- services/report_generator.py: Report generation

### External
- FastAPI: APIRouter, HTTPException, UploadFile
- Pydantic: Data validation
- aiosqlite: Async database queries

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
