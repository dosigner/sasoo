<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# hooks

## Purpose
Custom React hooks for managing data fetching, state, and side effects related to papers and analysis operations.

## Key Files
| File | Description |
|------|-------------|
| useAnalysis.ts | Hook for analysis pipeline: start analysis, poll status, get results per phase (screening/visual/recipe/deep_dive), handle SSE or polling for progressive loading, track errors |
| usePapers.ts | Hook for paper CRUD operations: upload PDF, list papers with filters, get single paper, update metadata, delete paper, cache management |

## Subdirectories
None

## For AI Agents

### Working In This Directory
- Hooks use the API client from `@/lib/api.ts` for all backend calls
- State management is local with `useState` and `useEffect` - no Redux/Zustand
- All async operations return promises and handle errors with try-catch
- Polling intervals should be cleaned up in useEffect return functions
- SSE connections should be closed on unmount

### Testing Requirements
- Test hook behavior with React Testing Library's renderHook
- Mock API responses from `@/lib/api.ts`
- Verify loading states transition correctly
- Test error handling (network errors, API errors)
- Verify cleanup functions run on unmount (polling, SSE)

### Common Patterns
- Return object structure: `{ data, loading, error, refetch, ...operations }`
- Loading state starts `true`, sets `false` after first fetch
- Error state stores error message string or null
- Operations (upload, delete, etc.) are async functions
- Polling uses `setInterval` with cleanup in `useEffect` return
- SSE uses EventSource API with readyState checks

## Dependencies

### Internal
- `@/lib/api.ts` - All backend API calls

### External
- react (useState, useEffect, useCallback, useMemo)

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
