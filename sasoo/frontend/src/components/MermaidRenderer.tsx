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
  Maximize2,
  Wand2,
  X,
  ZoomIn,
  ZoomOut,
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
// Fullscreen modal with zoom/pan
// ---------------------------------------------------------------------------

const ZOOM_MIN = 0.2;
const ZOOM_MAX = 8;

// Pan momentum (Apple-style exponential decay): release velocity is sampled
// from recent pointer history, then decays every frame until it drops below
// the stop threshold.
const MOMENTUM_DECAY_PER_MS = 0.998;
const MOMENTUM_STOP_SPEED = 20; // px/s — momentum loop halts below this
const MOMENTUM_MIN_RELEASE_SPEED = 50; // px/s — slower releases skip momentum entirely
const VELOCITY_SAMPLE_WINDOW_MS = 100; // pointer history window used to compute release velocity
const VELOCITY_SAMPLE_MAX = 6; // cap on retained samples within the window

// Wheel-zoom rubber-banding: boundary overshoot is resisted exponentially and
// capped near this fraction, then springs back once wheel input goes idle.
const ZOOM_RUBBER_BAND_MAX_OVERSHOOT = 0.08; // ~8% past ZOOM_MIN/MAX at full resistance
const ZOOM_WHEEL_IDLE_MS = 180; // debounce before the boundary spring-back kicks in
const ZOOM_SPRING_DURATION_MS = 200; // felt duration of the critically-damped return
const ZOOM_SPRING_TAU_MS = ZOOM_SPRING_DURATION_MS / 5;

function rubberBandScale(rawValue: number): number {
  if (rawValue < ZOOM_MIN) {
    const over = ZOOM_MIN - rawValue;
    const limit = ZOOM_MIN * ZOOM_RUBBER_BAND_MAX_OVERSHOOT;
    return ZOOM_MIN - limit * (1 - Math.exp(-over / limit));
  }
  if (rawValue > ZOOM_MAX) {
    const over = rawValue - ZOOM_MAX;
    const limit = ZOOM_MAX * ZOOM_RUBBER_BAND_MAX_OVERSHOOT;
    return ZOOM_MAX + limit * (1 - Math.exp(-over / limit));
  }
  return rawValue;
}

// Critically-damped spring step response (0 -> 1 progress) over t ms, scaled by tau.
function criticallyDampedProgress(tMs: number, tauMs: number): number {
  const x = tMs / tauMs;
  return 1 - Math.exp(-x) * (1 + x);
}

function MermaidModal({
  svg,
  title,
  onClose,
}: {
  svg: string;
  title: string;
  onClose: () => void;
}) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const viewportRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  // Recent pointer samples (position + time) used to compute release velocity.
  const pointerHistoryRef = useRef<{ x: number; y: number; t: number }[]>([]);
  // Mirrors of state that stay accurate between renders, so momentum/rubber-band
  // loops and interrupt handlers never read a stale value.
  const scaleRef = useRef(scale);
  const offsetRef = useRef(offset);
  const prefersReducedMotionRef = useRef(false);
  const momentumRafRef = useRef<number | null>(null);
  const zoomSpringRafRef = useRef<number | null>(null);
  const wheelIdleTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => { scaleRef.current = scale; }, [scale]);
  useEffect(() => { offsetRef.current = offset; }, [offset]);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    prefersReducedMotionRef.current = mq.matches;
    const handler = (e: MediaQueryListEvent) => { prefersReducedMotionRef.current = e.matches; };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const cancelMomentum = useCallback(() => {
    if (momentumRafRef.current !== null) {
      cancelAnimationFrame(momentumRafRef.current);
      momentumRafRef.current = null;
    }
  }, []);

  const cancelZoomSpring = useCallback(() => {
    if (zoomSpringRafRef.current !== null) {
      cancelAnimationFrame(zoomSpringRafRef.current);
      zoomSpringRafRef.current = null;
    }
  }, []);

  const cancelWheelIdleTimer = useCallback(() => {
    if (wheelIdleTimeoutRef.current !== null) {
      clearTimeout(wheelIdleTimeoutRef.current);
      wheelIdleTimeoutRef.current = null;
    }
  }, []);

  // Button/reset zoom is a discrete action, not a gesture — always hard clamp,
  // and cancel any in-flight wheel rubber-band/spring so it can't fight this.
  const zoomBy = useCallback((factor: number) => {
    cancelZoomSpring();
    cancelWheelIdleTimer();
    setScale((s) => {
      const next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, s * factor));
      scaleRef.current = next;
      return next;
    });
  }, [cancelZoomSpring, cancelWheelIdleTimer]);

  const resetView = useCallback(() => {
    cancelZoomSpring();
    cancelWheelIdleTimer();
    cancelMomentum();
    scaleRef.current = 1;
    offsetRef.current = { x: 0, y: 0 };
    setScale(1);
    setOffset({ x: 0, y: 0 });
  }, [cancelZoomSpring, cancelWheelIdleTimer, cancelMomentum]);

  // Animates scale from `from` back to the nearest ZOOM_MIN/MAX bound with a
  // critically damped step response (~200ms felt duration).
  const startZoomSpring = useCallback((from: number) => {
    const target = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, from));
    if (target === from) return;
    const start = performance.now();
    const step = (now: number) => {
      const t = now - start;
      const progress = criticallyDampedProgress(t, ZOOM_SPRING_TAU_MS);
      if (progress >= 0.99 || t > ZOOM_SPRING_DURATION_MS * 2.5) {
        scaleRef.current = target;
        setScale(target);
        zoomSpringRafRef.current = null;
        return;
      }
      const next = from + (target - from) * progress;
      scaleRef.current = next;
      setScale(next);
      zoomSpringRafRef.current = requestAnimationFrame(step);
    };
    zoomSpringRafRef.current = requestAnimationFrame(step);
  }, []);

  // Pan momentum: decays the release velocity exponentially (Apple-style)
  // each frame until it drops below the stop threshold.
  const startMomentum = useCallback((vx: number, vy: number) => {
    let velocity = { x: vx, y: vy };
    let lastT = performance.now();
    const step = (now: number) => {
      const dtMs = now - lastT;
      lastT = now;
      const decay = Math.pow(MOMENTUM_DECAY_PER_MS, dtMs);
      velocity = { x: velocity.x * decay, y: velocity.y * decay };
      const dtSec = dtMs / 1000;
      const next = {
        x: offsetRef.current.x + velocity.x * dtSec,
        y: offsetRef.current.y + velocity.y * dtSec,
      };
      offsetRef.current = next;
      setOffset(next);
      if (Math.hypot(velocity.x, velocity.y) < MOMENTUM_STOP_SPEED) {
        momentumRafRef.current = null;
        return;
      }
      momentumRafRef.current = requestAnimationFrame(step);
    };
    momentumRafRef.current = requestAnimationFrame(step);
  }, []);

  // Wheel zoom needs a non-passive listener to preventDefault page scroll.
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      cancelZoomSpring();
      cancelWheelIdleTimer();
      const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      const raw = scaleRef.current * factor;
      // Reduced motion: no overshoot, no spring-back — hard clamp like before.
      const next = prefersReducedMotionRef.current
        ? Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, raw))
        : rubberBandScale(raw);
      scaleRef.current = next;
      setScale(next);

      if (!prefersReducedMotionRef.current) {
        wheelIdleTimeoutRef.current = setTimeout(() => {
          wheelIdleTimeoutRef.current = null;
          const current = scaleRef.current;
          if (current < ZOOM_MIN || current > ZOOM_MAX) {
            startZoomSpring(current);
          }
        }, ZOOM_WHEEL_IDLE_MS);
      }
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [cancelZoomSpring, cancelWheelIdleTimer, startZoomSpring]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Clean up any in-flight rAF loop / timer on unmount.
  useEffect(() => {
    return () => {
      cancelMomentum();
      cancelZoomSpring();
      cancelWheelIdleTimer();
    };
  }, [cancelMomentum, cancelZoomSpring, cancelWheelIdleTimer]);

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex flex-col"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      {/* Toolbar */}
      <div
        className="flex items-center gap-2 px-4 py-2 bg-bg/90 border-b border-border"
        onClick={(e) => e.stopPropagation()}
      >
        <GitBranch className="w-4 h-4 text-accent shrink-0" />
        <span className="text-sm font-medium text-fg truncate flex-1">{title}</span>
        <button onClick={() => zoomBy(1 / 1.25)} className="btn-ghost text-2xs px-2 py-1" title={S.mermaid.zoomOut}>
          <ZoomOut className="w-3.5 h-3.5" />
        </button>
        <span className="text-2xs text-fg-muted w-12 text-center tabular-nums">
          {Math.round(scale * 100)}%
        </span>
        <button onClick={() => zoomBy(1.25)} className="btn-ghost text-2xs px-2 py-1" title={S.mermaid.zoomIn}>
          <ZoomIn className="w-3.5 h-3.5" />
        </button>
        <button onClick={resetView} className="btn-ghost text-2xs px-2 py-1" title={S.mermaid.zoomReset}>
          {S.mermaid.zoomReset}
        </button>
        <button
          onClick={() => downloadSvg(svg, title)}
          className="btn-ghost text-2xs px-2 py-1"
          title={`${S.mermaid.download} SVG`}
        >
          <Download className="w-3.5 h-3.5" />
          SVG
        </button>
        <button
          onClick={() => { void downloadPng(svg, title); }}
          className="btn-ghost text-2xs px-2 py-1"
          title={`${S.mermaid.download} PNG`}
        >
          <Download className="w-3.5 h-3.5" />
          PNG
        </button>
        <button onClick={onClose} className="btn-ghost text-2xs px-2 py-1" title={S.mermaid.close}>
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Zoom/pan viewport */}
      <div
        ref={viewportRef}
        className="flex-1 overflow-hidden cursor-grab active:cursor-grabbing"
        onClick={(e) => e.stopPropagation()}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          cancelMomentum();
          dragRef.current = { x: e.clientX, y: e.clientY, ox: offsetRef.current.x, oy: offsetRef.current.y };
          pointerHistoryRef.current = [{ x: e.clientX, y: e.clientY, t: performance.now() }];
        }}
        onPointerMove={(e) => {
          const drag = dragRef.current;
          if (!drag) return;
          const next = { x: drag.ox + (e.clientX - drag.x), y: drag.oy + (e.clientY - drag.y) };
          offsetRef.current = next;
          setOffset(next);

          const now = performance.now();
          const history = pointerHistoryRef.current;
          history.push({ x: e.clientX, y: e.clientY, t: now });
          while (history.length > 0 && now - history[0].t > VELOCITY_SAMPLE_WINDOW_MS) {
            history.shift();
          }
          while (history.length > VELOCITY_SAMPLE_MAX) {
            history.shift();
          }
        }}
        onPointerUp={() => {
          dragRef.current = null;
          const history = pointerHistoryRef.current;
          pointerHistoryRef.current = [];
          if (prefersReducedMotionRef.current || history.length < 2) return;
          const first = history[0];
          const last = history[history.length - 1];
          const dt = (last.t - first.t) / 1000;
          if (dt <= 0) return;
          const vx = (last.x - first.x) / dt;
          const vy = (last.y - first.y) / dt;
          if (Math.hypot(vx, vy) < MOMENTUM_MIN_RELEASE_SPEED) return;
          startMomentum(vx, vy);
        }}
        onPointerCancel={() => {
          dragRef.current = null;
          pointerHistoryRef.current = [];
        }}
        onDoubleClick={resetView}
      >
        <div
          className="w-full h-full flex items-center justify-center [&>svg]:max-w-none select-none"
          style={{
            transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
            transformOrigin: 'center center',
          }}
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
    </div>
  );
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
  const [showModal, setShowModal] = useState(false);
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
              <button
                onClick={() => setShowModal(true)}
                className="btn-ghost text-2xs px-2 py-1"
                title={S.mermaid.expand}
              >
                <Maximize2 className="w-3 h-3" />
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
              className="p-4 bg-surface/50 overflow-x-auto [&>svg]:mx-auto [&>svg]:max-w-full fade-in-up cursor-zoom-in"
              onClick={() => setShowModal(true)}
              dangerouslySetInnerHTML={{ __html: svgContent }}
            />
          </>
        )}
      </div>

      {showModal && svgContent && (
        <MermaidModal
          svg={svgContent}
          title={title || S.mermaid.title}
          onClose={() => setShowModal(false)}
        />
      )}
    </div>
  );
}
