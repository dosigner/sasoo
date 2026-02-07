import { useState, useEffect, useRef, useCallback } from 'react';
import mermaid from 'mermaid';
import {
  GitBranch,
  Code2,
  Eye,
  RefreshCw,
  Copy,
  Check,
  AlertCircle,
} from 'lucide-react';
import type { MermaidDiagram } from '@/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MermaidRendererProps {
  diagram: MermaidDiagram | null;
  loading?: boolean;
}

// ---------------------------------------------------------------------------
// Mermaid initialization
// ---------------------------------------------------------------------------

let mermaidInitialized = false;

function initMermaid() {
  if (mermaidInitialized) return;

  mermaid.initialize({
    startOnLoad: false,
    theme: 'dark',
    themeVariables: {
      primaryColor: '#4f46e5',
      primaryTextColor: '#e2e8f0',
      primaryBorderColor: '#6366f1',
      lineColor: '#64748b',
      secondaryColor: '#1e293b',
      tertiaryColor: '#334155',
      noteTextColor: '#e2e8f0',
      noteBkgColor: '#1e293b',
      noteBorderColor: '#475569',
      fontFamily:
        '-apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", sans-serif',
      fontSize: '12px',
    },
    flowchart: {
      useMaxWidth: true,
      htmlLabels: true,
      curve: 'basis',
    },
    sequence: {
      useMaxWidth: true,
    },
  });

  mermaidInitialized = true;
}

// ---------------------------------------------------------------------------
// Mermaid code sanitizer (last-resort defense for v10.x compatibility)
// ---------------------------------------------------------------------------

function sanitizeMermaidCode(code: string): string {
  let cleaned = code.trim();

  // 1. Strip markdown fences if somehow still present
  if (cleaned.startsWith('```mermaid')) {
    cleaned = cleaned.slice('```mermaid'.length).trim();
  } else if (cleaned.startsWith('```')) {
    cleaned = cleaned.slice(3).trim();
  }
  if (cleaned.endsWith('```')) {
    cleaned = cleaned.slice(0, -3).trim();
  }

  // 2. Remove --- frontmatter block (biggest cause of "Syntax error in text")
  const fmMatch = cleaned.match(/^\s*---\s*\n[\s\S]*?\n\s*---\s*\n?/);
  if (fmMatch) {
    cleaned = cleaned.slice(fmMatch[0].length);
  }

  // 3. Remove accTitle / accDescr lines
  cleaned = cleaned.replace(/^\s*accTitle\s*:.*$/gm, '');
  cleaned = cleaned.replace(/^\s*accDescr\s*:.*$/gm, '');
  cleaned = cleaned.replace(/^\s*accDescr\s*\{[^}]*\}/gms, '');

  // 4. Trim leading/trailing whitespace
  cleaned = cleaned.trim();

  return cleaned;
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function MermaidSkeleton() {
  return (
    <div className="card animate-pulse">
      <div className="flex items-center gap-2 mb-4">
        <div className="h-4 w-4 bg-surface-700 rounded" />
        <div className="h-4 bg-surface-700 rounded w-36" />
      </div>
      <div className="aspect-[16/9] bg-surface-700 rounded-lg" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MermaidRenderer({
  diagram,
  loading = false,
}: MermaidRendererProps) {
  const [showCode, setShowCode] = useState(false);
  const [editableCode, setEditableCode] = useState('');
  const [svgContent, setSvgContent] = useState('');
  const [renderError, setRenderError] = useState<string | null>(null);
  const [isRendering, setIsRendering] = useState(false);
  const [copied, setCopied] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const renderIdRef = useRef(0);

  // Initialize mermaid on mount
  useEffect(() => {
    initMermaid();
  }, []);

  // Set editable code when diagram changes
  useEffect(() => {
    if (diagram?.mermaid_code) {
      setEditableCode(diagram.mermaid_code);
    }
  }, [diagram?.mermaid_code]);

  // Render the mermaid diagram
  const renderDiagram = useCallback(
    async (code: string) => {
      if (!code.trim()) return;

      setIsRendering(true);
      setRenderError(null);
      renderIdRef.current += 1;
      const currentRenderId = renderIdRef.current;

      // Sanitize the code before rendering (fix frontmatter, accTitle, etc.)
      const sanitized = sanitizeMermaidCode(code);
      if (!sanitized) {
        if (currentRenderId === renderIdRef.current) {
          setRenderError('Empty diagram code after sanitization');
          setIsRendering(false);
        }
        return;
      }

      try {
        const diagramId = `mermaid-${Date.now()}-${currentRenderId}`;
        const { svg } = await mermaid.render(diagramId, sanitized);

        // Only update if this is still the latest render
        if (currentRenderId === renderIdRef.current) {
          setSvgContent(svg);
          setRenderError(null);
        }
      } catch (err) {
        if (currentRenderId === renderIdRef.current) {
          setRenderError(
            err instanceof Error ? err.message : 'Failed to render diagram'
          );
        }
      } finally {
        if (currentRenderId === renderIdRef.current) {
          setIsRendering(false);
        }
      }
    },
    []
  );

  // Render when code changes
  useEffect(() => {
    if (editableCode) {
      renderDiagram(editableCode);
    }
  }, [editableCode, renderDiagram]);

  const handleRerender = useCallback(() => {
    renderDiagram(editableCode);
  }, [editableCode, renderDiagram]);

  const handleCopyCode = useCallback(() => {
    navigator.clipboard.writeText(editableCode).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [editableCode]);

  const handleResetCode = useCallback(() => {
    if (diagram?.mermaid_code) {
      setEditableCode(diagram.mermaid_code);
    }
  }, [diagram?.mermaid_code]);

  if (loading) {
    return <MermaidSkeleton />;
  }

  if (!diagram) {
    return (
      <div>
        <h3 className="text-sm font-semibold text-surface-200 mb-3 flex items-center gap-2">
          <GitBranch className="w-4 h-4 text-primary-400" />
          Process Diagram
        </h3>
        <div className="card flex flex-col items-center justify-center py-8 text-center">
          <GitBranch className="w-8 h-8 text-surface-600 mb-2" />
          <p className="text-sm text-surface-400">
            Diagram not yet generated. Complete analysis to see the process
            flow.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-surface-200 flex items-center gap-2">
          <GitBranch className="w-4 h-4 text-primary-400" />
          Process Diagram
        </h3>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setShowCode(!showCode)}
            className={`btn-ghost text-2xs px-2 py-1 ${
              showCode ? 'bg-surface-700 text-primary-400' : ''
            }`}
            title={showCode ? 'Hide code' : 'View code'}
          >
            {showCode ? (
              <>
                <Eye className="w-3 h-3" />
                Preview
              </>
            ) : (
              <>
                <Code2 className="w-3 h-3" />
                Code
              </>
            )}
          </button>
          <button
            onClick={handleCopyCode}
            className="btn-ghost text-2xs px-2 py-1"
            title="Copy code"
          >
            {copied ? (
              <Check className="w-3 h-3 text-emerald-400" />
            ) : (
              <Copy className="w-3 h-3" />
            )}
          </button>
        </div>
      </div>

      {/* Description */}
      {diagram.description && (
        <p className="text-xs text-surface-400 mb-3 leading-relaxed">
          {diagram.description}
        </p>
      )}

      {/* Code editor */}
      {showCode && (
        <div className="mb-3 fade-in-up">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-2xs text-surface-500 uppercase tracking-wider">
              Mermaid Code
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={handleResetCode}
                className="btn-ghost text-2xs px-2 py-0.5"
                title="Reset to original"
              >
                Reset
              </button>
              <button
                onClick={handleRerender}
                className="btn-ghost text-2xs px-2 py-0.5"
                title="Re-render diagram"
              >
                <RefreshCw className="w-3 h-3" />
                Render
              </button>
            </div>
          </div>
          <textarea
            value={editableCode}
            onChange={(e) => setEditableCode(e.target.value)}
            className="input font-mono text-xs h-40 resize-y"
            spellCheck={false}
          />
        </div>
      )}

      {/* Rendered diagram */}
      <div className="card p-0 overflow-hidden">
        {isRendering && (
          <div className="flex items-center justify-center py-12">
            <RefreshCw className="w-5 h-5 text-primary-400 animate-spin" />
          </div>
        )}

        {renderError && !isRendering && (
          <div className="flex flex-col items-center justify-center py-8 px-4 text-center">
            <AlertCircle className="w-6 h-6 text-red-400 mb-2" />
            <p className="text-sm text-red-300 mb-1">
              Failed to render diagram
            </p>
            <p className="text-2xs text-surface-500 max-w-md">
              {renderError}
            </p>
          </div>
        )}

        {svgContent && !isRendering && !renderError && (
          <div
            ref={containerRef}
            className="p-4 bg-surface-800/50 overflow-x-auto [&>svg]:mx-auto [&>svg]:max-w-full fade-in-up"
            dangerouslySetInnerHTML={{ __html: svgContent }}
          />
        )}
      </div>
    </div>
  );
}
