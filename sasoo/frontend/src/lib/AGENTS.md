<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# lib

## Purpose
Utility functions and HTTP client for communicating with the FastAPI backend.

## Key Files
| File | Description |
|------|-------------|
| api.ts | HTTP client for all backend API endpoints. Base URL: http://localhost:8000. Functions for papers CRUD, analysis operations, settings, agent profiles, cost tracking. Uses native fetch API with error handling and JSON parsing. |

## Subdirectories
None

## For AI Agents

### Working In This Directory
- All API calls in the app MUST go through this module - never use fetch directly in components
- Base URL is hardcoded to `http://localhost:8000` (local FastAPI server)
- In Electron, this points to the embedded Python backend managed by python-manager.ts
- All functions are async and throw errors on non-2xx responses
- Request bodies are JSON, responses parsed as JSON
- File uploads use FormData with multipart/form-data

### Testing Requirements
- Mock fetch globally in tests
- Verify error handling for network errors and API errors
- Test that request headers include Content-Type: application/json
- Verify file upload uses FormData correctly
- Test that query params are properly encoded

### Common Patterns
- Function names match REST semantics: `getPapers()`, `createPaper()`, `updatePaper()`, `deletePaper()`
- Error responses throw with message from backend or generic message
- Analysis endpoints: `startAnalysis(paperId)`, `getAnalysisStatus(paperId)`, `getAnalysisResults(paperId, phase)`
- Settings endpoints: `getSettings()`, `updateSettings(settings)`
- All functions return typed promises (TypeScript interfaces defined in api.ts)

## Dependencies

### Internal
- None (this is a leaf utility module)

### External
- Native fetch API (built into browser/Electron)

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
