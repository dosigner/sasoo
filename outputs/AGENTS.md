<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# Outputs Directory

## Purpose

This directory stores analysis run outputs from Sasoo. Each run creates a timestamped subdirectory containing analysis results, visualizations, and detailed iteration data.

## Directory Structure

```
outputs/
├── run_20260207_112030_01d219/
│   ├── planning.json          # Analysis planning data
│   ├── metadata.json          # Run metadata (timestamp, parameters, etc.)
│   ├── diagram_iter_1.png     # First iteration visualization
│   ├── diagram_iter_2.png     # Subsequent iterations
│   ├── final_output.png       # Final visualization output
│   ├── iter_1/
│   │   └── details.json       # Detailed results for iteration 1
│   ├── iter_2/
│   │   └── details.json       # Detailed results for iteration 2
│   └── ...
├── run_20260207_141530_a2f891/
│   └── (same structure as above)
└── ...
```

## File Descriptions

### Metadata Files

- **planning.json** - Analysis planning configuration and parameters used for the run
- **metadata.json** - Run information including timestamp, analysis type, and execution parameters

### Visualization Files

- **diagram_iter_N.png** - Mermaid/PaperBanana diagram for iteration N (2-3 MB each)
- **final_output.png** - Final visualization output combining all iterations

### Iteration Data

- **iter_N/details.json** - Detailed analysis results for each iteration, including computed metrics and intermediate findings

## AI Agent Guidelines

### Output-Only Data

This directory contains generated output from the Sasoo backend analysis pipeline. **Do not modify existing run data.**

### Key Constraints

- Each run directory is self-contained with a unique timestamp ID
- PNG files can be large (2-3 MB each)
- Run data is immutable after generation
- Always preserve iteration history for traceability

### Working with Outputs

When accessing run data:

1. **Read metadata.json** to understand run parameters
2. **Check planning.json** for analysis configuration
3. **Reference iter_N/details.json** for numerical results
4. **Use final_output.png** for presentation/review purposes

## Naming Convention

Run directories follow the pattern: `run_YYYYMMDD_HHMMSS_XXXXX`

- `YYYYMMDD_HHMMSS` - Timestamp of run execution
- `XXXXX` - 5-character run identifier

## Note

Do not create, move, or delete run directories manually. The Sasoo backend manages the complete lifecycle of output data.
