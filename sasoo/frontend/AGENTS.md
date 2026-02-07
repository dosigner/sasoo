<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# Frontend

## Purpose
React 18 + TypeScript + Vite frontend for the Sasoo AI Co-Scientist desktop app. Provides the UI for paper upload, analysis visualization, library management, and settings configuration.

## Key Files
| File | Description |
|------|-------------|
| index.html | HTML entry point with root div for React mount |
| vite.config.ts | Vite bundler config with path alias @/ → src/ |
| tsconfig.json | TypeScript config for app code (strict mode, JSX) |
| tsconfig.node.json | TypeScript config for Vite config files |
| tailwind.config.js | Tailwind CSS 3.4 config with dark mode support |
| postcss.config.js | PostCSS config for Tailwind processing |
| package.json | Dependencies: react 18, react-router-dom 6, mermaid 10, react-markdown, react-pdf-viewer, lucide-react, tailwindcss 3.4, vite 5 |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| src/ | Application source code root |

## For AI Agents

### Working In This Directory
- Dev server runs at `http://localhost:5173` via `pnpm dev`
- Build production bundle with `pnpm build` (outputs to dist/)
- Use path alias `@/` for imports from src/ (e.g., `import { api } from '@/lib/api'`)
- All components use Tailwind CSS for styling
- Theme switching (dark/light) managed via localStorage key 'sasoo-theme'
- This is an Electron-embedded app - the frontend talks to a local FastAPI backend on port 8000

### Testing Requirements
- Run `pnpm dev` and verify hot reload works
- Check dark/light theme toggle functionality
- Test navigation between routes (Upload, Library, Workbench, Settings)
- Verify PDF upload and analysis workflows

### Common Patterns
- All API calls go through `src/lib/api.ts`
- Data fetching uses custom hooks from `src/hooks/`
- Components are functional with TypeScript props interfaces
- Icons imported from `lucide-react`
- Routing via `react-router-dom` v6 (Routes, Route, useNavigate)

## Dependencies

### Internal
- Communicates with FastAPI backend at localhost:8000
- Embedded in Electron app (parent directory has electron/ folder)

### External
- react ^18.2.0
- react-router-dom ^6.22.0
- mermaid ^10.8.0
- react-markdown ^9.0.1
- @react-pdf-viewer/core ^3.12.0
- lucide-react ^0.344.0
- tailwindcss ^3.4.1
- vite ^5.1.4

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
