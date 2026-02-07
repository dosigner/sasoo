<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# Models

## Purpose
Data models, database schema, and Pydantic schemas for API validation. Defines the data layer for papers, analysis results, figures, and settings.

## Key Files
| File | Description |
|------|-------------|
| __init__.py | Package initialization |
| database.py | Async SQLite layer via aiosqlite. Singleton connection pattern. Tables: papers, analysis_results, figures, settings. WAL mode, foreign keys ON. Library root: ~/sasoo-library/. Helper functions: fetch_one, fetch_all, execute_insert, execute_update, get_paper_dir, get_figures_dir, get_paperbanana_dir |
| paper.py | Dataclass models: Figure, Table, Metadata, ParsedPaper. Used internally by pdf_parser service |
| schemas.py (12KB) | Pydantic models for API. Enums: PaperStatus(pending/analyzing/completed/error), AnalysisPhase(screening/visual/recipe/deep_dive), DomainType(optics/materials/bio/energy/quantum/general), AgentType(photon/crystal/helix/volt/qubit/atlas) |

## Subdirectories
None

## For AI Agents

### Working In This Directory
- Database location: `~/sasoo-library/sasoo.db`
- All database operations are async (use `await`)
- `paper.py` models are for internal pipeline use
- `schemas.py` models are for API request/response validation
- Database helpers abstract SQL queries

### Testing Requirements
- Verify database initialization creates all tables
- Test foreign key constraints (papers → analysis_results → figures)
- Validate Pydantic schema validation with invalid data
- Check WAL mode enabled: `PRAGMA journal_mode;`
- Test path helpers: get_paper_dir, get_figures_dir

### Common Patterns
- Singleton database connection: `get_db()`
- Async context manager for connections
- Helper functions for common queries (fetch_one, fetch_all, execute_insert, execute_update)
- Pydantic models with validators for enums
- Dataclasses for internal data structures

## Dependencies

### Internal
- Used by api/ for request/response validation
- Used by services/ for data manipulation
- Database helpers called throughout application

### External
- aiosqlite: Async SQLite operations
- pydantic: Data validation and serialization
- dataclasses: Internal model definitions

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
