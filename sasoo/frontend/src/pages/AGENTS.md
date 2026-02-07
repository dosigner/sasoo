<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# pages

## Purpose
Top-level page components for each route in the Sasoo app. Each page represents a distinct user workflow.

## Key Files
| File | Description |
|------|-------------|
| Upload.tsx | PDF upload page with drag-and-drop zone, file validation (PDF only, max size), progress indicator, auto-redirect to Workbench after upload. Route: `/` |
| Library.tsx | Paper library grid/list view with search bar, filter by domain/status, sort by date/title, pagination, click to navigate to Workbench. Route: `/library` |
| Workbench.tsx | Main analysis workspace showing PDF viewer on left, analysis results panel on right, progress tracker, figure gallery, recipe cards. Route: `/workbench/:paperId` |
| Settings.tsx | App settings page: API key configuration (OpenAI/Anthropic), default domain selection, theme toggle, LLM model selection, budget limits, agent profile management. Route: `/settings` |

## Subdirectories
None

## For AI Agents

### Working In This Directory
- Pages compose components from `@/components/`
- Data fetching uses custom hooks from `@/hooks/`
- Navigation uses `useNavigate()` from react-router-dom
- Route params accessed via `useParams()` hook (e.g., `paperId` in Workbench)
- Pages manage local UI state (search query, filters, view mode) with useState
- All pages are responsive and support dark/light theme via Tailwind classes

### Testing Requirements
- Test each page route renders correctly
- Verify data fetching shows loading states
- Test error states (e.g., paper not found in Workbench)
- Test Upload page file validation (reject non-PDF, reject oversized files)
- Test Library page filters and search functionality
- Test Settings page saves to backend API
- Verify navigation flows: Upload → Workbench, Library → Workbench

### Common Patterns
- Page wrapper div uses `className="p-6 max-w-7xl mx-auto"`
- Loading states show spinner with "Loading..." text
- Error states show AlertCircle icon with error message and retry button
- Upload page auto-navigates to `/workbench/:paperId` on success
- Library page uses grid layout (3 columns on desktop, 1 on mobile)
- Workbench uses two-column layout (PDF left, analysis right) on desktop, stacked on mobile
- Settings uses form sections with labeled inputs and save button

## Dependencies

### Internal
- `@/components/*` - All UI components (AnalysisPanel, PdfViewer, ProgressTracker, etc.)
- `@/hooks/useAnalysis` - Analysis data fetching
- `@/hooks/usePapers` - Paper CRUD operations
- `@/lib/api` - Direct API calls for settings

### External
- react (useState, useEffect)
- react-router-dom (useNavigate, useParams, Link)
- lucide-react (icons: Upload, Search, Filter, Grid, List, Settings, Save, etc.)

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
