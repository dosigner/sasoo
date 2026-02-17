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
import { S } from '@/lib/strings';

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

function initMermaid(isDark = true) {
  const theme = isDark ? 'dark' : 'default';
  mermaid.initialize({
    startOnLoad: false,
    theme,
    themeVariables: isDark ? {
      primaryColor: '#0071e3',
      primaryTextColor: '#e8e8ed',
      primaryBorderColor: '#0a84ff',
      lineColor: '#636366',
      secondaryColor: '#1c1c1e',
      tertiaryColor: '#3a3a3c',
      noteTextColor: '#e8e8ed',
      noteBkgColor: '#1c1c1e',
      noteBorderColor: '#48484a',
      fontFamily:
        '"SF Pro Display", "SF Pro Text", -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif',
      fontSize: '12px',
    } : {
      primaryColor: '#007aff',
      primaryTextColor: '#1d1d1f',
      primaryBorderColor: '#0071e3',
      lineColor: '#aeaeb2',
      secondaryColor: '#f5f5f7',
      tertiaryColor: '#e8e8ed',
      noteTextColor: '#1d1d1f',
      noteBkgColor: '#f5f5f7',
      noteBorderColor: '#d1d1d6',
      fontFamily:
        '"SF Pro Display", "SF Pro Text", -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif',
      fontSize: '12px',
    },
    flowchart: {
      useMaxWidth: true,
      htmlLabels: false,
      curve: 'basis',
    },
    sequence: {
      useMaxWidth: true,
    },
  });
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
          setRenderError(S.mermaid.emptyCode);
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
            err instanceof Error ? err.message : S.mermaid.renderFailed
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

  // Initialize/reinitialize mermaid when theme changes
  useEffect(() => {
    const isDark = !document.documentElement.classList.contains('light');
    initMermaid(isDark);
    // Re-render if we have content
    if (editableCode) {
      renderDiagram(editableCode);
    }
  }, []);

  // Watch for theme changes
  useEffect(() => {
    const observer = new MutationObserver(() => {
      const isDark = !document.documentElement.classList.contains('light');
      initMermaid(isDark);
      if (editableCode) {
        renderDiagram(editableCode);
      }
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });
    return () => observer.disconnect();
  }, [editableCode, renderDiagram]);

  // Set editable code when diagram changes
  useEffect(() => {
    if (diagram?.mermaid_code) {
      setEditableCode(diagram.mermaid_code);
    }
  }, [diagram?.mermaid_code]);

  // Render only when the diagram source changes (not on every edit)
  useEffect(() => {
    if (diagram?.mermaid_code) {
      renderDiagram(diagram.mermaid_code);
    }
  }, [diagram?.mermaid_code, renderDiagram]);

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
          {S.mermaid.title}
        </h3>
        <div className="card flex flex-col items-center justify-center py-8 text-center">
          <GitBranch className="w-8 h-8 text-surface-600 mb-2" />
          <p className="text-sm text-surface-400">
            {S.mermaid.notGenerated}
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
          {S.mermaid.title}
        </h3>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setShowCode(!showCode)}
            className={`btn-ghost text-2xs px-2 py-1 ${
              showCode ? 'bg-surface-700 text-primary-400' : ''
            }`}
            title={showCode ? S.mermaid.preview : S.mermaid.code}
          >
            {showCode ? (
              <>
                <Eye className="w-3 h-3" />
                {S.mermaid.preview}
              </>
            ) : (
              <>
                <Code2 className="w-3 h-3" />
                {S.mermaid.code}
              </>
            )}
          </button>
          <button
            onClick={handleCopyCode}
            className="btn-ghost text-2xs px-2 py-1"
            title={S.mermaid.copy}
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
              {S.mermaid.mermaidCode}
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={handleResetCode}
                className="btn-ghost text-2xs px-2 py-0.5"
                title={S.mermaid.reset}
              >
                {S.mermaid.reset}
              </button>
              <button
                onClick={handleRerender}
                className="btn-ghost text-2xs px-2 py-0.5"
                title={S.mermaid.render}
              >
                <RefreshCw className="w-3 h-3" />
                {S.mermaid.render}
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
              {S.mermaid.renderFailed}
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
