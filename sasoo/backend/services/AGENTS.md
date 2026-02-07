<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# Services

## Purpose
Core business logic layer. Orchestrates PDF parsing, 4-phase analysis pipeline, domain routing, visualization generation, and report formatting.

## Key Files
| File | Description |
|------|-------------|
| __init__.py | Package initialization |
| README.md | Comprehensive service documentation |
| analysis_pipeline.py (34KB) | Main 4-phase orchestration: Screening→Visual→Recipe→Deep Dive. Coordinates agents, LLM calls, visualization |
| paper_library.py (26KB) | Paper library management, organization, search |
| report_generator.py (25KB) | Markdown report generation from analysis results |
| domain_router.py (20KB) | Routes papers to appropriate domain agents based on content |
| pdf_parser.py (16KB) | PDF extraction using PyMuPDF + pdfplumber (text, figures, tables, metadata). Max 50MB |
| section_splitter.py (16KB) | Splits paper text into logical sections for token-efficient phase-specific inputs. 70-80% token savings |
| test_parser_example.py (5.5KB) | Parser test/example script |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| agents/ | Domain-specific AI agent implementations (photon, cell, neural) |
| llm/ | LLM client implementations (Gemini, Claude) |
| viz/ | Visualization generation (Mermaid, PaperBanana) |

## For AI Agents

### Working In This Directory
- The 4-phase analysis strategy is the core architecture
- Each phase receives only relevant sections to save tokens (section_splitter.py)
- All services are async
- Use domain_router.py to select appropriate agent for paper type
- PDF parser supports max 50MB files
- Section splitter achieves 70-80% token reduction by filtering irrelevant sections per phase

### Testing Requirements
- Test PDF parsing: `python test_parser_example.py <pdf_path>`
- Verify all 4 phases complete successfully
- Check token usage optimization via section splitter
- Validate Mermaid diagram generation quality
- Test report formatting with real analysis results

### Common Patterns
- Async/await for all I/O operations
- Phase-specific section filtering for token efficiency
- Agent selection based on domain classification
- Progress tracking during analysis phases
- Error handling with phase rollback

## Dependencies

### Internal
- agents/ for domain-specific analysis
- llm/ for AI provider integration
- viz/ for diagram generation
- models/database.py for persistence
- models/schemas.py for data structures

### External
- PyMuPDF (fitz): PDF text extraction
- pdfplumber: Table and figure detection
- google-generativeai: Gemini API
- anthropic: Claude API
- paperbanana: Scientific figure generation

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
