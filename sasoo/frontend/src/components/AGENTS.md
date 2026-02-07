<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# components

## Purpose
Reusable React components for displaying paper analysis results, PDF viewing, progress tracking, and cost visualization in the Sasoo UI.

## Key Files
| File | Description |
|------|-------------|
| AnalysisPanel.tsx | Displays 4-phase analysis results (screening, visual, recipe, deep_dive) with collapsible sections, phase status indicators, and progress UI |
| CostDashboard.tsx | Token usage and API cost tracking visualization with charts, breakdown by phase/model, budget alerts |
| FigureGallery.tsx | Grid gallery of extracted paper figures with thumbnails, captions, AI-generated descriptions, zoom modal |
| MermaidRenderer.tsx | Renders Mermaid.js diagrams from code strings, handles mermaid.initialize(), error states, loading spinner |
| PdfViewer.tsx | PDF viewer component using @react-pdf-viewer/core, with page navigation, zoom controls, loading state |
| ProgressTracker.tsx | Step-by-step progress indicator for the 4-phase analysis pipeline (screening → visual → recipe → deep_dive) |
| RecipeCard.tsx | Displays experimental recipe card with extracted parameters, visual tags for [INFERRED]/[EXPLICIT] values, editable fields |

## Subdirectories
None

## For AI Agents

### Working In This Directory
- All components are functional TypeScript components with props interfaces
- Styling uses Tailwind CSS utility classes exclusively
- Icons imported from `lucide-react` (e.g., CheckCircle, Clock, AlertCircle, Loader2)
- Components are stateless - they receive data via props, events bubble up via callbacks
- Error states handled with try-catch and error UI (e.g., "Failed to render diagram")

### Testing Requirements
- Test each component in isolation with mock props
- Verify loading states render correctly (spinner/skeleton)
- Test error states (e.g., invalid Mermaid syntax, PDF load failure)
- Check responsive layout on different screen sizes
- Verify dark/light theme styles work correctly

### Common Patterns
- Props interface named `{ComponentName}Props`
- Loading state shows Loader2 icon with spin animation
- Error states show AlertCircle icon with error message
- All interactive elements have hover/focus states via Tailwind
- Collapsible sections use ChevronDown/ChevronRight icons
- Tag rendering for [INFERRED]/[EXPLICIT] uses badge components

## Dependencies

### Internal
- None (components are leaf nodes in dependency tree)

### External
- react (useState, useEffect, useMemo)
- lucide-react (icons: CheckCircle, Clock, AlertCircle, Loader2, ChevronDown, ChevronRight, ZoomIn, Download, etc.)
- mermaid ^10.8.0 (MermaidRenderer only)
- @react-pdf-viewer/core ^3.12.0 (PdfViewer only)
- react-markdown ^9.0.1 (for rendering analysis text with markdown)

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
