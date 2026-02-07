<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# src

## Purpose
Application source code root containing all React components, pages, hooks, and utilities for the Sasoo frontend.

## Key Files
| File | Description |
|------|-------------|
| App.tsx | Main app component with sidebar navigation (Upload, Library, Settings), collapsible sidebar toggle, dark/light theme switcher, routing setup |
| main.tsx | React entry point mounting App to DOM with BrowserRouter wrapper |
| index.css | Global styles with Tailwind directives (@tailwind base/components/utilities), custom CSS variables for theming, scrollbar styles |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| components/ | Reusable React components for paper analysis UI |
| hooks/ | Custom React hooks for data fetching and state management |
| lib/ | Utility functions and API client |
| pages/ | Top-level page components for each route |

## For AI Agents

### Working In This Directory
- App.tsx defines the main layout: left sidebar + main content area
- Routes: `/` (Upload), `/library` (Library), `/workbench/:paperId` (Workbench), `/settings` (Settings)
- Theme state stored in localStorage as 'sasoo-theme' (light|dark)
- Sidebar collapse state persists in localStorage as 'sasoo-sidebar-collapsed'
- All routing uses react-router-dom v6 (declarative Routes, not Switch)

### Testing Requirements
- Verify all 4 routes render correctly
- Test sidebar collapse/expand animation
- Test theme toggle persists across page reloads
- Check navigation between pages maintains sidebar state

### Common Patterns
- Pages are lazy-loaded via React.lazy if needed
- Global CSS variables defined in index.css for consistent theming
- App.tsx uses useLocation() to highlight active nav item
- All pages receive routing params via useParams() hook

## Dependencies

### Internal
- components/ - UI building blocks
- hooks/ - Data fetching logic
- lib/ - API client and utilities
- pages/ - Route components

### External
- react, react-dom
- react-router-dom (BrowserRouter, Routes, Route, Link, useNavigate, useParams, useLocation)
- lucide-react (icons: FileText, Library, Settings, ChevronLeft, ChevronRight, Sun, Moon)

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
