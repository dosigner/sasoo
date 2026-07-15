import { useState, useEffect, useRef, useCallback } from 'react';
import mermaid from 'mermaid';
import elkLayouts from '@mermaid-js/layout-elk';
import {
  GitBranch,
  Code2,
  Eye,
  RefreshCw,
  Copy,
  Check,
  AlertCircle,
  Download,
  Wand2,
} from 'lucide-react';
import type { MermaidDiagram } from '@/lib/api';
import { S } from '@/lib/strings';

mermaid.registerLayoutLoaders(elkLayouts);

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MermaidRendererProps {
  diagram: MermaidDiagram | null;
  loading?: boolean;
  /** Used for download filenames. */
  title?: string;
  /**
   * Self-heal hook: given failing code + parser error, return repaired code
   * (or null when repair is unavailable/failed). Called at most once per
   * diagram source.
   */
  onRepair?: (code: string, errorMessage: string) => Promise<string | null>;
}

// ---------------------------------------------------------------------------
// Mermaid initialization
// ---------------------------------------------------------------------------

type MermaidLayout = 'elk' | 'dagre';

function isDarkTheme(): boolean {
  return document.documentElement.classList.contains('dark');
}

function initMermaid(isDark = true, layout: MermaidLayout = 'elk') {
  const theme = isDark ? 'dark' : 'default';
  mermaid.initialize({
    startOnLoad: false,
    theme,
    layout,
    // Multi-stage fallback re-renders on failure; don't inject error SVGs.
    suppressErrorRendering: true,
    themeVariables: isDark ? {
      primaryColor: '#5e6ad2',
      primaryTextColor: '#f4f4f5',
      primaryBorderColor: '#6e79dd',
      lineColor: '#70707a',
      secondaryColor: '#17171a',
      tertiaryColor: '#202024',
      noteTextColor: '#f4f4f5',
      noteBkgColor: '#17171a',
      noteBorderColor: '#2a2a30',
      fontFamily:
        '"SF Pro Display", "SF Pro Text", -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif',
      fontSize: '12px',
    } : {
      primaryColor: '#5e6ad2',
      primaryTextColor: '#18181b',
      primaryBorderColor: '#4f5abf',
      lineColor: '#8e8e96',
      secondaryColor: '#ffffff',
      tertiaryColor: '#f0f0f2',
      noteTextColor: '#18181b',
      noteBkgColor: '#ffffff',
      noteBorderColor: '#e4e4e7',
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

  // 3. Remove accTitle / accDescr lines and init directives
  cleaned = cleaned.replace(/^\s*accTitle\s*:.*$/gm, '');
  cleaned = cleaned.replace(/^\s*accDescr\s*:.*$/gm, '');
  cleaned = cleaned.replace(/^\s*accDescr\s*\{[^}]*\}/gms, '');
  cleaned = cleaned.replace(/%%\{init:[\s\S]*?\}%%\s*/g, '');

  // 4. Trim leading/trailing whitespace
  cleaned = cleaned.trim();

  return cleaned;
}

// Styling statements (classDef/linkStyle/…) are additive decoration on
// flowcharts. When the fully styled code fails to parse, retry with the risky
// parts removed before surfacing an error to the user.

function isFlowchart(code: string): boolean {
  return /^\s*(flowchart|graph)\b/.test(code);
}

function stripLinkStyles(code: string): string {
  // Numbered linkStyle lines fail hard when an index is out of range.
  return code.replace(/^\s*linkStyle\s+.*$/gm, '').trim();
}

function stripAllStyling(code: string): string {
  return code
    .replace(/^\s*(classDef|class|style|linkStyle)\s+.*$/gm, '')
    .replace(/:::[A-Za-z0-9_-]+/g, '')
    .trim();
}

function buildRenderCandidates(code: string): string[] {
  const candidates = [code];
  if (isFlowchart(code)) {
    for (const variant of [stripLinkStyles(code), stripAllStyling(code)]) {
      if (variant && !candidates.includes(variant)) {
        candidates.push(variant);
      }
    }
  }
  return candidates;
}

// ---------------------------------------------------------------------------
// Download helpers
// ---------------------------------------------------------------------------

export function safeFilename(name: string): string {
  return (name || 'diagram').replace(/[\\/:*?"<>|\s]+/g, '_').slice(0, 60);
}

export function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Mermaid SVGs carry viewBox + max-width style but no pixel size; pin one for export. */
function svgWithPixelSize(svg: string): { svg: string; width: number; height: number } {
  const doc = new DOMParser().parseFromString(svg, 'image/svg+xml');
  const el = doc.documentElement;
  let width = parseFloat(el.getAttribute('width') || '');
  let height = parseFloat(el.getAttribute('height') || '');
  const viewBox = (el.getAttribute('viewBox') || '').split(/[\s,]+/).map(Number);
  if ((!width || Number.isNaN(width)) && viewBox.length === 4) width = viewBox[2];
  if ((!height || Number.isNaN(height)) && viewBox.length === 4) height = viewBox[3];
  width = Math.ceil(width || 1200);
  height = Math.ceil(height || 800);
  el.setAttribute('width', String(width));
  el.setAttribute('height', String(height));
  el.removeAttribute('style');
  return { svg: new XMLSerializer().serializeToString(el), width, height };
}

function downloadSvg(svg: string, name: string) {
  const { svg: sized } = svgWithPixelSize(svg);
  downloadBlob(
    `${safeFilename(name)}.svg`,
    new Blob([sized], { type: 'image/svg+xml;charset=utf-8' })
  );
}

export async function svgToPngBlob(svg: string, scale = 2): Promise<Blob | null> {
  const { svg: sized, width, height } = svgWithPixelSize(svg);
  const img = new Image();
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve();
    img.onerror = () => reject(new Error('SVG image load failed'));
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(sized)}`;
  });
  const canvas = document.createElement('canvas');
  canvas.width = width * scale;
  canvas.height = height * scale;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  // Pale diagram text disappears on a transparent PNG viewed on white — bake
  // the app background in.
  ctx.fillStyle = isDarkTheme() ? '#0f0f11' : '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.scale(scale, scale);
  ctx.drawImage(img, 0, 0, width, height);
  return new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, 'image/png')
  );
}

async function downloadPng(svg: string, name: string, scale = 2) {
  const blob = await svgToPngBlob(svg, scale);
  if (blob) downloadBlob(`${safeFilename(name)}.png`, blob);
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function MermaidSkeleton() {
  return (
    <div className="card animate-pulse">
      <div className="flex items-center gap-2 mb-4">
        <div className="h-4 w-4 bg-border rounded" />
        <div className="h-4 bg-border rounded w-36" />
      </div>
      <div className="aspect-[16/9] bg-border rounded-lg" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

// Sanitize + render, using the same fallback ladder as the component. For
// programmatic use (e.g. bulk export) outside the renderer UI.
let exportRenderSeq = 0;
export async function renderMermaidSvg(
  code: string
): Promise<{ svg: string; degraded: boolean } | { error: string }> {
  const sanitized = sanitizeMermaidCode(code);
  if (!sanitized) return { error: S.mermaid.emptyCode };
  exportRenderSeq += 1;
  return attemptRender(sanitized, 100000 + exportRenderSeq);
}

// Try candidates × layouts; returns the first successful SVG.
async function attemptRender(
  code: string,
  renderId: number
): Promise<{ svg: string; degraded: boolean } | { error: string }> {
  const candidates = buildRenderCandidates(code);
  let lastError: unknown = null;

  // ELK produces much cleaner layouts for dense flowcharts, but non-flowchart
  // diagrams (sequence, mindmap, ...) ignore pluggable layouts entirely — an
  // ELK attempt there is a wasted render pass, so only flowcharts get it.
  const layouts: MermaidLayout[] = isFlowchart(code) ? ['elk', 'dagre'] : ['dagre'];

  for (let i = 0; i < candidates.length; i++) {
    for (const layout of layouts) {
      try {
        initMermaid(isDarkTheme(), layout);
        const diagramId = `mermaid-${Date.now()}-${renderId}-${i}-${layout}`;
        const { svg } = await mermaid.render(diagramId, candidates[i]);
        if (i > 0) {
          console.warn(
            `Mermaid: rendered with styling stripped (fallback stage ${i})`
          );
        }
        return { svg, degraded: i > 0 };
      } catch (err) {
        lastError = err;
      }
    }
  }
  return {
    error:
      lastError instanceof Error ? lastError.message : S.mermaid.renderFailed,
  };
}

// ---------------------------------------------------------------------------
// User-facing error mapping
// ---------------------------------------------------------------------------

// attemptRender's raw error is a parser exception message or, in some cases,
// a native V8 error surfaced through a failed dynamic import — neither is
// meaningful to a non-technical user. Map to a short Korean explanation and
// keep the raw text out of the UI (callers should console.error it instead).
function friendlyMermaidError(raw: string): string {
  if (/Parse error|Expecting|got '|Syntax error/i.test(raw)) {
    return S.mermaid.errorSyntax;
  }
  if (/Invalid or unexpected token|Failed to fetch|import|module|Unexpected token '<'/i.test(raw)) {
    return S.mermaid.errorEngine;
  }
  return S.mermaid.renderFailed;
}

export default function MermaidRenderer({
  diagram,
  loading = false,
  title,
  onRepair,
}: MermaidRendererProps) {
  const [showCode, setShowCode] = useState(false);
  const [editableCode, setEditableCode] = useState('');
  const [svgContent, setSvgContent] = useState('');
  const [renderError, setRenderError] = useState<string | null>(null);
  const [styleDegraded, setStyleDegraded] = useState(false);
  const [wasRepaired, setWasRepaired] = useState(false);
  const [isRendering, setIsRendering] = useState(false);
  const [isRepairing, setIsRepairing] = useState(false);
  const [copied, setCopied] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const renderIdRef = useRef(0);
  // Last source we already asked the LLM to repair — one attempt per source.
  const repairAttemptedForRef = useRef<string | null>(null);

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

      let outcome = await attemptRender(sanitized, currentRenderId);
      let repaired = false;

      // Local fallbacks exhausted → ask the LLM to fix the code, once per source.
      if (
        'error' in outcome &&
        onRepair &&
        repairAttemptedForRef.current !== sanitized
      ) {
        repairAttemptedForRef.current = sanitized;
        if (currentRenderId === renderIdRef.current) setIsRepairing(true);
        try {
          const fixed = await onRepair(sanitized, outcome.error);
          const fixedSanitized = fixed ? sanitizeMermaidCode(fixed) : '';
          if (fixedSanitized) {
            const second = await attemptRender(fixedSanitized, currentRenderId);
            if (!('error' in second)) {
              outcome = second;
              repaired = true;
              if (currentRenderId === renderIdRef.current) {
                setEditableCode(fixedSanitized);
              }
            }
          }
        } catch (err) {
          console.warn('Mermaid repair failed:', err);
        }
        if (currentRenderId === renderIdRef.current) setIsRepairing(false);
      }

      // Only update if this is still the latest render
      if (currentRenderId !== renderIdRef.current) return;

      if ('error' in outcome) {
        setStyleDegraded(false);
        setWasRepaired(false);
        // Raw parser/engine error stays in the console for debugging; the UI
        // only ever shows the friendly mapping (see friendlyMermaidError).
        console.error('Mermaid render failed:', outcome.error);
        setRenderError(outcome.error);
      } else {
        setSvgContent(outcome.svg);
        setRenderError(null);
        setStyleDegraded(outcome.degraded);
        setWasRepaired(repaired);
      }
      setIsRendering(false);
    },
    [onRepair]
  );

  // Re-render when the theme changes (attemptRender re-reads the theme on
  // every pass, so a plain re-render is enough).
  useEffect(() => {
    const observer = new MutationObserver(() => {
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
        <h3 className="text-sm font-semibold text-fg mb-3 flex items-center gap-2">
          <GitBranch className="w-4 h-4 text-accent" />
          {S.mermaid.title}
        </h3>
        <div className="card flex flex-col items-center justify-center py-8 text-center">
          <GitBranch className="w-8 h-8 text-fg-muted mb-2" />
          <p className="text-sm text-fg-muted">
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
        <h3 className="text-sm font-semibold text-fg flex items-center gap-2">
          <GitBranch className="w-4 h-4 text-accent" />
          {S.mermaid.title}
        </h3>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setShowCode(!showCode)}
            className={`btn-ghost text-2xs px-2 py-1 ${
              showCode ? 'bg-surface text-accent' : ''
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
              <Check className="w-3 h-3 text-success" />
            ) : (
              <Copy className="w-3 h-3" />
            )}
          </button>
          {svgContent && !renderError && (
            <>
              <button
                onClick={() => downloadSvg(svgContent, title || S.mermaid.title)}
                className="btn-ghost text-2xs px-2 py-1"
                title={`${S.mermaid.download} SVG`}
              >
                <Download className="w-3 h-3" />
                SVG
              </button>
              <button
                onClick={() => { void downloadPng(svgContent, title || S.mermaid.title); }}
                className="btn-ghost text-2xs px-2 py-1"
                title={`${S.mermaid.download} PNG`}
              >
                <Download className="w-3 h-3" />
                PNG
              </button>
            </>
          )}
        </div>
      </div>

      {/* Description */}
      {diagram.description && (
        <p className="text-xs text-fg-muted mb-3 leading-relaxed">
          {diagram.description}
        </p>
      )}

      {/* Code editor */}
      {showCode && (
        <div className="mb-3 fade-in-up">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-2xs text-fg-muted uppercase tracking-wider">
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
          <div className="flex flex-col items-center justify-center py-12 gap-2">
            {isRepairing ? (
              <>
                <Wand2 className="w-5 h-5 text-accent animate-pulse" />
                <span className="text-xs text-fg-muted">{S.mermaid.repairing}</span>
              </>
            ) : (
              <RefreshCw className="w-5 h-5 text-accent animate-spin" />
            )}
          </div>
        )}

        {renderError && !isRendering && (
          <div className="flex flex-col items-center justify-center py-8 px-4 text-center">
            <AlertCircle className="w-6 h-6 text-danger mb-2" />
            <p className="text-sm text-danger mb-1">
              {S.mermaid.renderFailed}
            </p>
            <p className="text-2xs text-fg-muted max-w-md">
              {friendlyMermaidError(renderError)}
            </p>
          </div>
        )}

        {svgContent && !isRendering && !renderError && (
          <>
            {wasRepaired && (
              <p className="text-2xs text-fg-muted px-4 pt-3 flex items-center gap-1">
                <Wand2 className="w-3 h-3 text-accent" />
                {S.mermaid.repairedNotice}
              </p>
            )}
            {styleDegraded && (
              <p className="text-2xs text-fg-muted px-4 pt-3 flex items-center gap-1">
                <AlertCircle className="w-3 h-3" />
                {S.mermaid.styleFallback}
              </p>
            )}
            <div
              ref={containerRef}
              className="p-4 bg-surface/50 overflow-x-auto [&>svg]:mx-auto [&>svg]:max-w-full fade-in-up"
              dangerouslySetInnerHTML={{ __html: svgContent }}
            />
          </>
        )}
      </div>
    </div>
  );
}
