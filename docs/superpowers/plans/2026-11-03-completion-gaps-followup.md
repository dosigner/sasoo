# Completion Gaps Follow-up Implementation Plan

**Goal:** Make saved analysis completion, provenance, visualization and cost states reproducible and honest without paid calls.

**Architecture:** Reuse existing response schemas and result records. Add only the provenance and planned-item data needed to verify a run, while preserving legacy rows and successful artifacts.

**Tech Stack:** FastAPI, SQLite, React, pytest, Vitest, Electron.

**Spec:** `docs/validation/2026-11-03-ai-scientist-v3-completion-contract.md` and the user's handoff.

## Global Constraints

Preserve analysis content, models, effort, parallel execution, dirty changes and paid evidence. No paid requests, retries, releases or paper comparison.

## Completion criteria

1. **Stage structure and citation.** Reproduce malformed nested values, enums and missing required fields in screening, citation, visual, recipe, deep dive and synthesis. Reuse the provider schemas or existing validators as the source of truth; keep permitted empty arrays, system skips, partial outputs and readable legacy rows. Invalid requested citation interpretation must preserve local counts and raw response, fail completion and never become a successful cache hit. Test old ambiguous citation cache rows without issuing requests.
2. **Source and dependency identity.** Add an additive run manifest that records a common source signature, relevant configuration identity and the exact result IDs consumed or deliberately reused by each stage. Check the manifest against results on completion and restore. Different phase input hashes are expected. Missing legacy provenance is reported as unverified rather than fabricated; conflicting provenance cannot yield a verified complete set. Exercise changed source, changed configuration, cache reuse, interruption, concurrent/fenced runs and restart using isolated data.
3. **Visualization plan.** Persist the gate-approved ordered IDs and tools independently of produced items at each checkpoint. Reject missing, duplicate, extra or wrong-tool output on both final and cached paths. Preserve the intentional empty-plan case, successful paid items, cancellation checkpoints and existing per-item merge behavior. Add integration tests that inspect stored rows and simulate partial failure and resume without provider calls.
4. **Execution evidence.** Expose saved, verified, unverified and failed states without claiming that stored code or an image file proves execution or scientific accuracy. Preserve existing reuse/failure policy. Any HTML execution check must run in isolation with network and user data access blocked; distinguish timeout and absence of verification from success. Test HTML, Mermaid, image, legacy and explicit failure paths and corresponding UI labels.
5. **Cost and usage.** Define one live/restored accounting basis based on identifiable requests, distinguishing new spend, reuse and unknown usage. Never turn unknown cost into zero or count a reused request as new spending. Cover synthesis, visualization planning and generation, retries, duplicate IDs, partial checkpoints and restart. Where historical records lack enough evidence, show uncertainty rather than invent a total.

## Regression loop and evidence

- For each issue, add a deterministic test that fails for the reported behavior before fixing it, then run the focused test and adjacent tests after the change.
- Trace every changed shared function through its callers, persistence, API, frontend and cache paths. Add a regression for a newly found failure and repeat this loop after the fix.
- Once all five criteria pass individually, run the combined backend suite, frontend tests, type check, lint and build. If a combined check finds a defect, fix the cause, rerun its focused tests and rerun every affected wider suite. Do not call the loop complete on an unrelated pre-existing failure: record and classify it with evidence.
- Exercise changed UI in isolated Electron with network and generation/write endpoints blocked. Verify normal, partial, legacy, unverified and failed states, representative widths, console errors and at least one displayed value against the backend fixture.
- Record commands, outcomes, preservation checks, limitations and evidence in a validation report. The stopping condition is that all required checks pass after the last relevant change, and no unresolved in-scope failure remains. Do not repeat unchanged passing suites indefinitely.
- Do not run paid providers, retry issued requests, publish a release or alter frozen evidence. Structural readiness and mocked/fixture checks do not establish scientific correctness, real provider behavior or packaged-release quality.
