import { useState, useCallback, useEffect, lazy, Suspense } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  BookOpen,
  GitBranch,
  Check,
  Loader2,
  Circle,
  AlertCircle,
} from 'lucide-react';
import {
  type ArtifactStatus,
  getStaticUrl,
  type AnalysisResults,
  type AnalysisStatus,
  type FigureListResponse,
  type TableListResponse,
  type Recipe,
  type MermaidDiagram,
  type VisualizationPlan,
  type VisualizationItem,
  type PhaseStatusValue,
  type AnalysisPhase,
  type Figure,
  type Table,
  rewriteSection,
} from '@/lib/api';
import { getAgentMeta } from '@/lib/agents';
import { buildPhaseSummary, buildWorkbenchStatusSummary } from '@/lib/workbenchSummaries';
import { S } from '@/lib/strings';
import { useToast } from '@/components/Toast';
import LevelSlider from './LevelSlider';
import FigureGallery from './FigureGallery';
import TableGallery from './TableGallery';
import RecipeCard from './RecipeCard';
import ExperimentPlanTab from './ExperimentPlanTab';
import { ContentState } from '@/components/ui';
import { AppIcon } from '@/components/icons';
const MermaidRenderer = lazy(() => import('./MermaidRenderer'));
import ProgressTracker from './ProgressTracker';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AnalysisPanelProps {
  status: AnalysisStatus | null;
  artifactStatus?: ArtifactStatus | null;
  results: AnalysisResults | null;
  figures: FigureListResponse | null;
  tables: TableListResponse | null;
  recipe: Recipe | null;
  mermaid: MermaidDiagram | null;
  visualizations: VisualizationPlan | null;
  isRunning: boolean;
  agentName?: string;
  paperId?: string;
  paperLevel?: string;
  onJumpToFigurePage?: (figure: Figure) => void;
  onJumpToTablePage?: (table: Table) => void;
  terminalState?: 'cancelled' | null;
}

// ---------------------------------------------------------------------------
// deep_dive 수준 재작성 — 표시 상태 결정 (순수 함수, 단위 검증 가능)
// ---------------------------------------------------------------------------

export interface DeepDiveViewState {
  /** 렌더할 텍스트. null이면 원본 마크다운 대신 하위 로더/children으로 폴백 */
  content: string | null;
  /** true면 스켈레톤 표시 + 슬라이더 disabled */
  loading: boolean;
}

/**
 * 현재 viewLevel에 대해 어떤 deep_dive 텍스트를 보여줄지 결정한다.
 * - viewLevel === paperLevel  → 원본(분석 시 사용된 수준)
 * - rewrites[viewLevel] 존재  → 프론트 캐시된 재작성본
 * - rewriting === true        → 로딩(스켈레톤), 그동안 원본 유지
 * - 그 외(실패/미요청)         → 원본 유지(폴백)
 */
export function resolveDeepDiveView(params: {
  viewLevel: string;
  paperLevel: string;
  original: string | null;
  rewrites: Record<string, string>;
  rewriting: boolean;
}): DeepDiveViewState {
  const { viewLevel, paperLevel, original, rewrites, rewriting } = params;
  if (viewLevel === paperLevel) return { content: original, loading: false };
  const cached = rewrites[viewLevel];
  if (cached !== undefined) return { content: cached, loading: false };
  if (rewriting) return { content: original, loading: true };
  return { content: original, loading: false };
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PHASE_META: Record<string, {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  description: string;
  number: number;
}> = {
  screening: {
    icon: (props) => <AppIcon name="summary" {...props} />,
    label: S.analysis.phase1,
    description: S.analysis.phase1Desc,
    number: 1,
  },
  citation: {
    icon: BookOpen,
    label: S.analysis.phase2,
    description: S.analysis.phase2Desc,
    number: 2,
  },
  visual: {
    icon: (props) => <AppIcon name="figures" {...props} />,
    label: S.analysis.phase3,
    description: S.analysis.phase3Desc,
    number: 3,
  },
  recipe: {
    icon: (props) => <AppIcon name="recipe" {...props} />,
    label: S.analysis.phase4,
    description: S.analysis.phase4Desc,
    number: 4,
  },
  deep_dive: {
    icon: GitBranch,
    label: S.analysis.phase5,
    description: S.analysis.phase5Desc,
    number: 5,
  },
};

// Phase order (used for rendering in the panel below)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getPhaseStatusInfo(phaseStatus: PhaseStatusValue): {
  icon: React.ReactNode;
  label: string;
  classes: string;
} {
  switch (phaseStatus) {
    case 'completed':
      return {
        icon: <Check className="w-4 h-4" />,
        label: S.status.complete,
        classes: 'text-emerald-400 bg-emerald-500/10',
      };
    case 'running':
      return {
        icon: <Loader2 className="w-4 h-4 animate-spin" />,
        label: S.status.running,
        classes: 'text-primary-400 bg-primary-500/10',
      };
    case 'error':
      return {
        icon: <AlertCircle className="w-4 h-4" />,
        label: S.status.error,
        classes: 'text-red-400 bg-red-500/8 border border-red-500/10',
      };
    case 'pending':
    default:
      return {
        icon: <Circle className="w-4 h-4" />,
        label: S.status.pending,
        classes: 'text-surface-500 bg-surface-800/80 border border-surface-700/45',
      };
  }
}

// ---------------------------------------------------------------------------
// Phase Section Component
// ---------------------------------------------------------------------------

interface PhaseSectionProps {
  phaseName: AnalysisPhase;
  phaseStatus: PhaseStatusValue;
  content: string | null;
  defaultExpanded: boolean;
  summaryLine?: string | null;
  collapsedMeta?: string[];
  expandedMeta?: string[];
  tone?: 'primary' | 'muted' | 'practical';
  accentColor?: string;
  children?: React.ReactNode;
  /** 확장된 본문 상단에 렌더할 컨트롤(예: 설명 수준 슬라이더) */
  headerControl?: React.ReactNode;
  /** true면 content 대신 스켈레톤을 표시(재작성 로딩) */
  contentLoading?: boolean;
}

function rgbaFromHex(color: string, alpha: number): string {
  const cleaned = color.replace('#', '');
  if (cleaned.length !== 6) return color;
  const r = parseInt(cleaned.slice(0, 2), 16);
  const g = parseInt(cleaned.slice(2, 4), 16);
  const b = parseInt(cleaned.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function buildMetaPillStyle(color?: string, variant: 'default' | 'soft' = 'default'): React.CSSProperties | undefined {
  if (!color) return undefined;

  return {
    color,
    borderColor: rgbaFromHex(color, variant === 'soft' ? 0.24 : 0.28),
    backgroundColor: rgbaFromHex(color, variant === 'soft' ? 0.08 : 0.13),
  };
}

function PhaseSection({
  phaseName,
  phaseStatus,
  content,
  defaultExpanded,
  summaryLine,
  collapsedMeta = [],
  expandedMeta = [],
  tone = 'muted',
  accentColor,
  children,
  headerControl,
  contentLoading = false,
}: PhaseSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const meta = PHASE_META[phaseName];
  const statusInfo = getPhaseStatusInfo(phaseStatus);
  const isActive = phaseStatus === 'running';

  // Allow expanding if: there's content, children, currently running, OR already completed
  const hasContent = !!(content) || !!children || phaseStatus === 'running' || phaseStatus === 'completed';

  const toggleExpanded = useCallback(() => {
    if (hasContent) setExpanded((e) => !e);
  }, [hasContent]);

  if (!meta) return null;

  const Icon = meta.icon;
  const toneClasses =
    tone === 'primary'
      ? 'text-surface-100'
      : tone === 'practical'
        ? 'text-surface-200'
        : 'text-surface-300';

  return (
    <div
      className={`phase-section border-b last:border-b-0 ${
        phaseStatus === 'running'
          ? 'border-primary-500/16'
          : phaseStatus === 'completed'
            ? 'border-surface-700/38'
            : phaseStatus === 'error'
              ? 'border-red-500/16'
              : 'border-surface-700/32'
      }`}
    >
      <button
        onClick={toggleExpanded}
        className={`w-full flex items-center gap-3 px-0 py-3 text-left transition-colors ${
          hasContent
            ? 'hover:text-surface-100 cursor-pointer'
            : 'cursor-default opacity-60'
        }`}
        disabled={!hasContent}
        aria-expanded={expanded}
        aria-label={`${meta.label} ${expanded ? '닫기' : '열기'}`}
      >
        <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border ${
          isActive
            ? 'border-primary-500/18 bg-primary-500/8'
            : phaseStatus === 'error'
              ? 'border-red-500/18 bg-red-500/8'
              : 'border-surface-700/45 bg-surface-900/75'
        }`}>
          <Icon className={`w-3.5 h-3.5 ${isActive ? 'text-primary-400' : phaseStatus === 'error' ? 'text-red-400' : 'text-surface-500'}`} />
        </div>

        <div className="flex-1 min-w-0">
          <div className={`text-sm font-medium ${toneClasses}`}>
            {meta.label}
          </div>
          <div className="mt-1 text-2xs text-surface-500">
            {expanded ? meta.description : statusInfo.label}
          </div>
          {!expanded && collapsedMeta.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1.5">
              {collapsedMeta.map((item) => (
                <span
                  key={item}
                  className="phase-meta-pill"
                  style={buildMetaPillStyle(accentColor)}
                >
                  {item}
                </span>
              ))}
            </div>
          )}
          {expanded && expandedMeta.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {expandedMeta.map((item) => (
                <span
                  key={item}
                  className="phase-meta-pill phase-meta-pill-soft"
                  style={buildMetaPillStyle(accentColor, 'soft')}
                >
                  {item}
                </span>
              ))}
            </div>
          )}
          {!expanded && summaryLine && (
            <div className="mt-1 line-clamp-2 text-xs leading-relaxed text-surface-400">
              {summaryLine}
            </div>
          )}
        </div>

        <span className={`badge text-2xs shrink-0 ${statusInfo.classes}`}>
          {statusInfo.icon}
          <span className="ml-1 hidden sm:inline">{statusInfo.label}</span>
        </span>

        <span className="text-surface-500 shrink-0">
          {expanded ? (
            <AppIcon name="chevron-down" className="w-4 h-4" />
          ) : (
            <AppIcon name="chevron-right" className="w-4 h-4" />
          )}
        </span>
      </button>

      {expanded && hasContent && (
        <div className="pb-5">
          {headerControl && (
            <div className="mb-3">
              {headerControl}
            </div>
          )}

          {contentLoading ? (
            <div className="mt-2 space-y-2" role="status" aria-busy="true" aria-label={S.analysis.rewriting}>
              <div className="h-3 w-11/12 animate-pulse rounded bg-surface-700/40" />
              <div className="h-3 w-full animate-pulse rounded bg-surface-700/40" />
              <div className="h-3 w-10/12 animate-pulse rounded bg-surface-700/40" />
              <div className="h-3 w-9/12 animate-pulse rounded bg-surface-700/40" />
              <span className="sr-only">{S.analysis.rewriting}</span>
            </div>
          ) : (
          <>
          {phaseStatus === 'running' && !content && (
            <div className="flex items-center gap-2 py-4" role="status" aria-busy="true">
              <Loader2 className="w-4 h-4 text-primary-400 animate-spin" />
              <span className="text-xs text-surface-400">
                {S.analysis.analyzingDots}
              </span>
            </div>
          )}

          {phaseStatus === 'completed' && !content && !children && (
            <div className="flex items-center gap-2 py-4" role="status" aria-busy="true">
              <Loader2 className="w-4 h-4 text-surface-500 animate-spin" />
              <span className="text-xs text-surface-400">
                {S.analysis.loadingResults}
              </span>
            </div>
          )}

          {content && (
            <div className="analysis-content mt-2 fade-in-up">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {content}
              </ReactMarkdown>
            </div>
          )}

          {children && (
            <div className="mt-4 space-y-5 fade-in-up">
              {children}
            </div>
          )}
          </>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Markdown Formatter
// ---------------------------------------------------------------------------

/** Pretty-print a snake_case key into a human-readable label */
function prettyKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Try to strip markdown code fences and parse JSON from raw text */
function tryParseJson(text: string): Record<string, unknown> | null {
  let cleaned = text.trim();
  // Strip ```json ... ``` fences
  if (cleaned.startsWith('```')) {
    const lines = cleaned.split('\n');
    const start = lines.findIndex((l) => l.trim().startsWith('```'));
    let end = -1;
    for (let i = lines.length - 1; i >= 0; i--) {
      if (lines[i].trim() === '```') { end = i; break; }
    }
    if (start >= 0 && end > start) {
      cleaned = lines.slice(start + 1, end).join('\n').trim();
    }
  }
  try {
    const parsed = JSON.parse(cleaned);
    if (typeof parsed === 'object' && parsed !== null) return parsed;
  } catch { /* not JSON */ }
  return null;
}

/** Format a single value (string, number, boolean, array, object) into markdown */
function formatValue(value: unknown, indent = 0): string {
  if (value == null) return '_N/A_';
  if (typeof value === 'boolean') return value ? S.analysis.md.yes : S.analysis.md.no;
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    if (value.length === 0) return '_N/A_';
    return '\n' + value.map((item) => {
      if (typeof item === 'object' && item !== null) {
        // Object in array: show key-value pairs inline
        const parts = Object.entries(item as Record<string, unknown>)
          .filter(([, v]) => v != null && v !== '')
          .map(([k, v]) => `**${prettyKey(k)}:** ${v}`);
        return `${'  '.repeat(indent)}- ${parts.join(' · ')}`;
      }
      return `${'  '.repeat(indent)}- ${String(item)}`;
    }).join('\n');
  }
  if (typeof value === 'object') {
    return '\n' + Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v != null && v !== '')
      .map(([k, v]) => `${'  '.repeat(indent)}- **${prettyKey(k)}:** ${formatValue(v, indent + 1)}`)
      .join('\n');
  }
  return String(value);
}

/** Universal auto-formatter: turn any key-value data into readable markdown */
function autoFormatAsMarkdown(data: Record<string, unknown>): string {
  const lines: string[] = [];

  // Prioritize long text fields first (summary, detailed_analysis, etc.)
  const longTextKeys = ['summary', 'detailed_analysis', 'objective', 'quality_summary', 'description'];
  for (const key of longTextKeys) {
    if (data[key] && typeof data[key] === 'string' && (data[key] as string).length > 50) {
      lines.push(`${data[key]}\n`);
    }
  }

  // Then format all other fields
  for (const [key, value] of Object.entries(data)) {
    if (value == null || value === '') continue;
    // Skip keys already rendered as long text
    if (longTextKeys.includes(key) && typeof value === 'string' && value.length > 50) continue;
    // Skip internal keys
    if (key === 'raw_text' || key === 'raw') continue;

    const label = prettyKey(key);

    if (Array.isArray(value)) {
      if (value.length === 0) continue;
      lines.push(`\n**${label}:**`);
      value.forEach((item, i) => {
        if (typeof item === 'object' && item !== null) {
          const parts = Object.entries(item as Record<string, unknown>)
            .filter(([, v]) => v != null && v !== '')
            .map(([k, v]) => `**${prettyKey(k)}:** ${v}`);
          lines.push(`${i + 1}. ${parts.join(' · ')}`);
        } else {
          lines.push(`- ${String(item)}`);
        }
      });
    } else if (typeof value === 'object') {
      lines.push(`\n**${label}:**`);
      for (const [subKey, subVal] of Object.entries(value as Record<string, unknown>)) {
        if (subVal != null && subVal !== '') {
          lines.push(`- **${prettyKey(subKey)}:** ${formatValue(subVal)}`);
        }
      }
    } else if (typeof value === 'number' && key.includes('score')) {
      // Scores (0-1) → show as percentage
      const pct = value <= 1 ? (value * 100).toFixed(0) : String(value);
      lines.push(`**${label}:** ${pct}%`);
    } else if (typeof value === 'boolean') {
      lines.push(`**${label}:** ${value ? 'Yes' : 'No'}`);
    } else {
      lines.push(`**${label}:** ${value}`);
    }
  }

  return lines.join('\n');
}

function formatPhaseAsMarkdown(phase: AnalysisPhase, data: Record<string, unknown>): string {
  // If data has raw_text or raw, try to parse it as JSON first
  const rawText = (data.raw_text ?? data.raw) as string | undefined;
  if (rawText && typeof rawText === 'string' && Object.keys(data).length <= 2) {
    const parsed = tryParseJson(rawText);
    if (parsed) {
      return formatPhaseAsMarkdown(phase, parsed);
    }
    // Not JSON — return the raw text directly as markdown
    return rawText;
  }

  // Phase-specific enhanced formatting
  const lines: string[] = [];

  const md = S.analysis.md;

  if (phase === 'screening') {
    if (data.summary) lines.push(`${data.summary}\n`);
    if (data.domain) lines.push(`**${md.domain}:** ${data.domain}  `);
    if (data.relevance_score != null) lines.push(`**${md.relevance}:** ${(Number(data.relevance_score) * 100).toFixed(0)}%  `);
    if (data.methodology_type) lines.push(`**${md.methodology}:** ${data.methodology_type}  `);
    if (data.estimated_complexity) lines.push(`**${md.complexity}:** ${data.estimated_complexity}  `);
    if (data.is_experimental != null) lines.push(`**${md.experimental}:** ${data.is_experimental ? md.yes : md.no}  `);
    if (data.has_figures != null) lines.push(`**${md.hasFigures}:** ${data.has_figures ? md.yes : md.no}  `);
    if (data.agent_recommended) lines.push(`**${md.agent}:** ${data.agent_recommended}  `);
    const topics = data.key_topics as string[] | undefined;
    if (topics?.length) {
      lines.push(`\n**${md.keyTopics}:**`);
      topics.forEach(t => lines.push(`- ${t}`));
    }
  } else if (phase === 'citation') {
    const totalRefs = Number(data.total_references ?? 0);
    if (totalRefs === 0) {
      lines.push('PDF에서 참고문헌 섹션을 찾을 수 없습니다.');
    } else {
      if (data.summary) lines.push(`${data.summary}\n`);
      lines.push(`**참고문헌 수:** ${totalRefs}`);
      if (data.citation_style) lines.push(`**인용 스타일:** ${data.citation_style}`);
      if (data.self_citation_count != null) {
        const ratio = data.self_citation_ratio != null ? ` (${(Number(data.self_citation_ratio) * 100).toFixed(1)}%)` : '';
        lines.push(`**자기 인용:** ${data.self_citation_count}건${ratio}`);
      }
      const topCited = data.top_cited as Array<Record<string, unknown>> | undefined;
      if (topCited?.length) {
        lines.push(`\n#### 가장 많이 인용된 참고문헌\n`);
        lines.push('| # | Ref | 저자 | 연도 | 인용 수 | 역할 |');
        lines.push('|---|-----|------|------|---------|------|');
        topCited.slice(0, 10).forEach((ref, i) => {
          const refId = String(ref.ref_id || '');
          const authors = String(ref.authors || '').slice(0, 30);
          const year = ref.year != null ? String(ref.year) : '';
          const count = ref.cite_count != null ? String(ref.cite_count) : '0';
          const role = String(ref.citation_role || '');
          lines.push(`| ${i + 1} | ${refId} | ${authors} | ${year} | ${count} | ${role} |`);
        });
        lines.push('');
        // Why cited
        const hasWhy = topCited.slice(0, 10).some(r => r.why_cited);
        if (hasWhy) {
          lines.push('#### 인용 역할 분석\n');
          topCited.slice(0, 10).forEach(ref => {
            if (ref.why_cited) {
              lines.push(`- **${ref.ref_id}**: ${ref.why_cited}`);
            }
          });
          lines.push('');
        }
      }
      const dist = data.citation_distribution as Record<string, number> | undefined;
      if (dist && Object.keys(dist).length > 0) {
        lines.push('#### 섹션별 인용 분포\n');
        Object.entries(dist)
          .sort(([, a], [, b]) => (b as number) - (a as number))
          .forEach(([sec, count]) => lines.push(`- **${sec}**: ${count}건`));
        lines.push('');
      }
    }
  } else if (phase === 'visual') {
    if (data.quality_summary) lines.push(`${data.quality_summary}\n`);
    if (data.figure_count != null) lines.push(`**${md.figures}:** ${data.figure_count}`);
    if (data.tables_found != null) lines.push(`**${md.tables}:** ${data.tables_found}`);
    if (data.equations_found != null) lines.push(`**${md.equations}:** ${data.equations_found}`);
    const types = data.diagram_types as string[] | undefined;
    if (types?.length) lines.push(`**${md.diagramTypes}:** ${types.join(', ')}`);
    const findings = data.key_findings_from_visuals as string[] | undefined;
    if (findings?.length) {
      lines.push(`\n**${md.keyFindings}:**`);
      findings.forEach(f => lines.push(`- ${f}`));
    }

    // Statistical Red Flags
    const redFlags = data.statistical_red_flags as Array<Record<string, string>> | undefined;
    if (redFlags?.length) {
      const severityEmoji: Record<string, string> = { high: '🔴', medium: '🟡', low: '🟢' };
      const severityLabel = md.redFlagSeverity as unknown as Record<string, string>;
      const flagTypeLabel = md.redFlagTypes as unknown as Record<string, string>;
      lines.push(`\n---\n\n**${md.statisticalRedFlags}:**\n`);
      lines.push(`| ${severityEmoji['high']} | 대상 | 유형 | 설명 |`);
      lines.push('|---|------|------|------|');
      redFlags.forEach((flag) => {
        const emoji = severityEmoji[flag.severity] || '🟡';
        const sLabel = severityLabel?.[flag.severity] || flag.severity;
        const tLabel = flagTypeLabel?.[flag.flag_type] || flag.flag_type;
        lines.push(`| ${emoji} ${sLabel} | ${flag.target || '-'} | ${tLabel} | ${flag.description || '-'} |`);
      });
      lines.push('');
    }
  } else if (phase === 'recipe') {
    if (data.title) lines.push(`### ${data.title}\n`);
    if (data.objective) lines.push(`${data.objective}\n`);

    // Scores as inline badges
    const scoreParts: string[] = [];
    if (data.confidence != null) scoreParts.push(`**${md.confidence}:** ${(Number(data.confidence) * 100).toFixed(0)}%`);
    if (data.reproducibility_score != null) scoreParts.push(`**${md.reproducibility}:** ${(Number(data.reproducibility_score) * 100).toFixed(0)}%`);
    if (scoreParts.length > 0) lines.push(scoreParts.join(' · ') + '\n');

    // ── Parameters as Markdown Table ──
    const params = data.parameters as Array<Record<string, unknown>> | undefined;
    if (params?.length) {
      lines.push(`#### ${md.parameters}\n`);
      lines.push(`| ${md.paramNum} | ${md.paramName} | ${md.paramValue} | ${md.paramUnit} | ${md.paramNotes} |`);
      lines.push('|---|-----------|-------|------|-------|');
      params.forEach((p, i) => {
        if (typeof p === 'object' && p !== null) {
          const name = String(p.name || p.Name || p.parameter || '-');
          const value = String(p.value || p.Value || '-');
          const unit = String(p.unit || p.Unit || '-');
          const notes = String(p.notes || p.Notes || p.note || '-');
          lines.push(`| ${i + 1} | ${name} | ${value} | ${unit} | ${notes} |`);
        } else {
          lines.push(`| ${i + 1} | ${String(p)} | - | - | - |`);
        }
      });
      lines.push('');
    }

    // ── Materials ──
    const materials = data.materials as string[] | undefined;
    if (materials?.length) {
      lines.push(`#### ${md.materials}\n`);
      materials.forEach(m => lines.push(`- ${m}`));
      lines.push('');
    }

    // ── Equipment ──
    const equipment = data.equipment as string[] | undefined;
    if (equipment?.length) {
      lines.push(`#### ${md.equipment}\n`);
      equipment.forEach(e => lines.push(`- ${e}`));
      lines.push('');
    }

    // ── Steps ──
    const steps = data.steps as string[] | undefined;
    if (steps?.length) {
      lines.push(`#### ${md.experimentalSteps}\n`);
      steps.forEach((s, i) => lines.push(`${i + 1}. ${s}`));
      lines.push('');
    }

    // ── Critical Notes ──
    const notes = data.critical_notes as string[] | undefined;
    if (notes?.length) {
      lines.push(`#### ${md.criticalNotes}\n`);
      notes.forEach(n => lines.push(`- ${n}`));
      lines.push('');
    }

    // ── Missing Info ──
    const missing = data.missing_info as string[] | undefined;
    if (missing?.length) {
      lines.push(`#### ${md.missingInfo}\n`);
      missing.forEach(m => lines.push(`- ${m}`));
      lines.push('');
    }

    if (data.expected_results) lines.push(`**${md.expectedResults}:** ${data.expected_results}\n`);
    if (data.safety_notes) lines.push(`**${md.safetyNotes}:** ${data.safety_notes}\n`);
  } else if (phase === 'deep_dive') {
    if (data.detailed_analysis) lines.push(`${data.detailed_analysis}\n`);
    if (data.novelty_assessment) lines.push(`**${md.novelty}:** ${data.novelty_assessment}\n`);
    if (data.comparison_to_prior_work) lines.push(`**${md.comparisonToPrior}:** ${data.comparison_to_prior_work}\n`);
    const sections: [string, string][] = [
      ['strengths', `✅ ${md.strengths}`],
      ['weaknesses', `⚠️ ${md.weaknesses}`],
      ['suggested_improvements', `💡 ${md.suggestedImprovements}`],
      ['practical_applications', `🔧 ${md.practicalApplications}`],
      ['follow_up_questions', `❓ ${md.followUpQuestions}`],
    ];
    for (const [key, label] of sections) {
      const items = data[key] as string[] | undefined;
      if (items?.length) {
        lines.push(`\n**${label}:**`);
        items.forEach(item => lines.push(`- ${item}`));
      }
    }
  }

  // If phase-specific formatting produced results, return them
  if (lines.length > 0) {
    return lines.join('\n');
  }

  // Universal fallback: auto-format all key-value pairs as markdown
  return autoFormatAsMarkdown(data);
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// PaperBanana Image Viewer (inline)
// ---------------------------------------------------------------------------

function PaperBananaViewer({ item }: { item: VisualizationItem }) {
  if (item.status === 'error') {
    return (
      <div className="flex flex-col items-center justify-center py-6 text-center">
        <AlertCircle className="w-6 h-6 text-red-400 mb-2" />
        <p className="text-sm text-red-300">{S.mermaid.illustrationFailed}</p>
        {item.error_message && (
          <p className="text-2xs text-surface-500 mt-1">{item.error_message}</p>
        )}
      </div>
    );
  }

  if (!item.image_url) {
    return (
      <div className="flex items-center justify-center py-8" role="status" aria-busy="true">
        <Loader2 className="w-5 h-5 text-primary-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-surface-700">
      <img
        src={getStaticUrl(item.image_url)}
        alt={item.title}
        className="w-full h-auto object-contain bg-surface-800"
        loading="lazy"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Visualization Gallery (renders multiple items)
// ---------------------------------------------------------------------------

function VisualizationGallery({
  visualizations,
  legacyMermaid,
  loading,
}: {
  visualizations: VisualizationPlan | null;
  legacyMermaid: MermaidDiagram | null;
  loading: boolean;
}) {
  // If we have the new visualization plan, use it
  if (visualizations && visualizations.items.length > 0) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2 mb-2">
          <AppIcon name="experiment" className="w-4 h-4 text-primary-400" />
          <span className="text-sm font-semibold text-surface-200">
            {S.mermaid.visualizations}
          </span>
          <span className="badge text-2xs bg-primary-500/10 text-primary-400">
            {visualizations.items.length}
          </span>
        </div>
        {visualizations.items.map((item) => (
          <div key={item.id} className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-surface-300">
                {item.id}. {item.title}
              </span>
              <span className={`badge text-2xs ${
                item.tool === 'mermaid'
                  ? 'bg-indigo-500/10 text-indigo-400'
                  : 'bg-amber-500/10 text-amber-400'
              }`}>
                {item.tool === 'mermaid' ? 'Mermaid' : 'PaperBanana'}
              </span>
            </div>
            {item.description && (
              <p className="text-xs text-surface-500 leading-relaxed">
                {item.description}
              </p>
            )}
            {item.tool === 'mermaid' && item.mermaid_code ? (
              <Suspense fallback={<div className="flex items-center gap-2 py-4 justify-center"><Loader2 className="w-4 h-4 text-primary-400 animate-spin" /></div>}>
                <MermaidRenderer
                  diagram={{
                    paper_id: visualizations.paper_id,
                    mermaid_code: item.mermaid_code,
                    diagram_type: item.diagram_type,
                    description: item.description,
                  }}
                  loading={false}
                />
              </Suspense>
            ) : item.tool === 'paperbanana' ? (
              <PaperBananaViewer item={item} />
            ) : item.status === 'error' ? (
              <div className="text-sm text-red-400 py-2">
                {item.error_message || S.mermaid.generationFailed}
              </div>
            ) : (
              <div className="flex items-center gap-2 py-4 justify-center" role="status" aria-busy="true">
                <Loader2 className="w-4 h-4 text-primary-400 animate-spin" />
                <span className="text-xs text-surface-400">{S.mermaid.generating}</span>
              </div>
            )}
          </div>
        ))}
      </div>
    );
  }

  // If deep_dive is done but visualizations haven't arrived yet, show generating state
  if (!loading && !legacyMermaid) {
    return (
      <div>
        <h3 className="text-sm font-semibold text-surface-200 mb-3 flex items-center gap-2">
          <AppIcon name="experiment" className="w-4 h-4 text-primary-400" />
          {S.mermaid.visualizations}
        </h3>
        <div className="card flex flex-col items-center justify-center py-8 text-center">
          <Loader2 className="w-6 h-6 text-primary-400 animate-spin mb-2" />
          <p className="text-sm text-surface-400">
            {S.mermaid.generating}
          </p>
          <p className="text-2xs text-surface-500 mt-1">
            {S.mermaid.generatingTime}
          </p>
        </div>
      </div>
    );
  }

  // Fallback: legacy single mermaid diagram
  return (
    <Suspense fallback={<div className="flex items-center gap-2 py-4 justify-center"><Loader2 className="w-4 h-4 text-primary-400 animate-spin" /></div>}>
      <MermaidRenderer
        diagram={legacyMermaid}
        loading={loading}
      />
    </Suspense>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function AnalysisPanel({
  status,
  artifactStatus,
  results,
  figures,
  tables,
  recipe,
  mermaid: mermaidDiagram,
  visualizations,
  isRunning,
  agentName,
  paperId,
  paperLevel,
  onJumpToFigurePage,
  onJumpToTablePage,
  terminalState,
}: AnalysisPanelProps) {
  const [activeTab, setActiveTab] = useState<'summary' | 'figures' | 'tables' | 'recipe' | 'experiment'>('summary');
  const { toast } = useToast();

  // deep_dive 섹션의 설명 수준 재작성 상태
  const originalLevel = paperLevel ?? 'masters';
  const [viewLevel, setViewLevel] = useState<string>(originalLevel);
  const [rewrites, setRewrites] = useState<Record<string, string>>({}); // level → text
  const [rewriting, setRewriting] = useState(false);

  // 논문(또는 원본 수준)이 바뀌면 재작성 상태 초기화
  useEffect(() => {
    setViewLevel(originalLevel);
    setRewrites({});
    setRewriting(false);
  }, [paperId, originalLevel]);

  const handleLevelChange = useCallback(async (level: string) => {
    setViewLevel(level);
    if (level === originalLevel || rewrites[level] !== undefined || !paperId) return; // 원본/캐시
    setRewriting(true);
    try {
      const r = await rewriteSection(Number(paperId), 'deep_dive', level);
      setRewrites((prev) => ({ ...prev, [level]: r.text }));
    } catch {
      // 실패 시 원본 유지 + 한국어 에러 토스트
      setViewLevel(originalLevel);
      toast.error(S.analysis.rewriteFailed);
    } finally {
      setRewriting(false);
    }
  }, [originalLevel, rewrites, paperId, toast]);

  useEffect(() => {
    setActiveTab('summary');
  }, [paperId]);

  // Determine phase statuses
  const getPhaseStatus = (phaseName: AnalysisPhase): PhaseStatusValue => {
    if (!status) return 'pending';
    const phase = status.phases.find((p) => p.phase === phaseName);
    return phase?.status || 'pending';
  };

  // Get phase content as formatted markdown
  const getPhaseContent = (phaseName: AnalysisPhase): string | null => {
    if (!results) return null;
    const data = results[phaseName] as Record<string, unknown> | null;
    if (!data) return null;
    const formatted = formatPhaseAsMarkdown(phaseName, data);
    // Return null instead of empty string so hasContent logic works correctly
    return formatted.trim() || null;
  };

  // No analysis yet
  if (!status && !isRunning) {
    return (
      <div className="px-5 py-6">
        <ContentState
          icon={(props) => <AppIcon name="summary" {...props} />}
          title={S.analysis.noResults}
          description={S.analysis.noResultsDesc}
          tone="muted"
        />
      </div>
    );
  }

  const agentMeta = getAgentMeta(agentName);
  const phaseAccentColor = agentMeta?.color;
  const figureList = figures?.figures ?? [];
  const tableList = tables?.tables ?? [];
  const screeningSummary = buildPhaseSummary('screening', results, recipe, figureList, tableList, visualizations);
  const citationSummary = buildPhaseSummary('citation', results, recipe, figureList, tableList, visualizations);
  const visualSummary = buildPhaseSummary('visual', results, recipe, figureList, tableList, visualizations);
  const recipeSummary = buildPhaseSummary('recipe', results, recipe, figureList, tableList, visualizations);
  const deepDiveSummary = buildPhaseSummary('deep_dive', results, recipe, figureList, tableList, visualizations);
  const deepDiveOriginal = getPhaseContent('deep_dive');
  const deepDiveView = resolveDeepDiveView({
    viewLevel,
    paperLevel: originalLevel,
    original: deepDiveOriginal,
    rewrites,
    rewriting,
  });
  const deepDiveCompleted = getPhaseStatus('deep_dive') === 'completed';
  const recipeReady = getPhaseStatus('recipe') === 'completed' && Boolean(paperId);
  const workbenchStatus = buildWorkbenchStatusSummary({
    status,
    artifactStatus,
    figures: figureList,
    tables: tableList,
    recipe,
    visualizations,
    terminalState,
  });

  const visibleTab = activeTab === 'experiment' && !recipeReady ? 'summary' : activeTab;

  const tabs: Array<{ key: 'summary' | 'figures' | 'tables' | 'recipe' | 'experiment'; label: string; icon: 'summary' | 'figures' | 'tables' | 'recipe' | 'experiment'; disabled?: boolean }> = [
    { key: 'summary', label: S.workbench.summaryTab, icon: 'summary' },
    { key: 'figures', label: S.workbench.figuresTab, icon: 'figures' },
    { key: 'tables', label: S.workbench.tablesTab, icon: 'tables' },
    { key: 'recipe', label: S.workbench.recipeTab, icon: 'recipe' },
    { key: 'experiment', label: S.workbench.experimentTab, icon: 'experiment', disabled: !recipeReady },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="sticky top-0 z-20 border-b border-surface-700/45 bg-surface-900/95 backdrop-blur [.light_&]:bg-white/95">
        <div className="px-5 py-4">
          <div className="border border-surface-700/45 bg-surface-900/50 px-4 py-3 [.light_&]:bg-surface-50" style={{ borderRadius: 'var(--radius-surface)' }}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="mb-1 flex items-center gap-2 text-[11px] tracking-[0.08em] text-surface-500">
                  <AppIcon name="summary" className="h-3.5 w-3.5 text-primary-400" />
                  <span>{S.workbench.statusRailTitle}</span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-semibold text-surface-100">
                    {workbenchStatus.runStateLabel}
                  </h3>
                  <span className="status-pill border-surface-700/50 bg-surface-800/80 text-surface-300">
                    {workbenchStatus.currentPhaseLabel}
                  </span>
                  <span className="status-pill border-surface-700/50 bg-surface-800/80 text-surface-300">
                    {workbenchStatus.completedCount}/{workbenchStatus.totalCount} 완료
                  </span>
                  <span className="status-pill border-emerald-500/20 bg-emerald-500/10 text-emerald-300">
                    {workbenchStatus.trustStateLabel}
                  </span>
                </div>
              </div>

              <p className="max-w-md text-xs leading-relaxed text-surface-400">
                {workbenchStatus.nextActionLabel}
              </p>
            </div>
          </div>

          <div className="mt-4">
            <div className="segmented-control">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => !tab.disabled && setActiveTab(tab.key)}
                disabled={tab.disabled}
                className={`segmented-control__item ${
                  visibleTab === tab.key ? 'segmented-control__item-active' : ''
                } ${tab.disabled ? 'segmented-control__item-disabled' : ''}`}
              >
                <AppIcon name={tab.icon} className="h-4 w-4" />
                {tab.label}
              </button>
            ))}
            </div>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {visibleTab === 'summary' && (
          <div className="space-y-5">
            {status && status.overall_status !== 'pending' && (
              <ProgressTracker
                phases={status.phases}
                overallProgress={status.progress_pct}
                variant="minimal"
              />
            )}

            <div className="space-y-0">
              <PhaseSection
                phaseName="screening"
                phaseStatus={getPhaseStatus('screening')}
                content={getPhaseContent('screening')}
                defaultExpanded={true}
                summaryLine={screeningSummary.summaryLine}
                collapsedMeta={screeningSummary.collapsedMeta}
                expandedMeta={screeningSummary.expandedMeta}
                tone={screeningSummary.tone}
                accentColor={phaseAccentColor}
              />

              <PhaseSection
                phaseName="citation"
                phaseStatus={getPhaseStatus('citation')}
                content={getPhaseContent('citation')}
                defaultExpanded={false}
                summaryLine={citationSummary.summaryLine}
                collapsedMeta={citationSummary.collapsedMeta}
                expandedMeta={citationSummary.expandedMeta}
                tone={citationSummary.tone}
                accentColor={phaseAccentColor}
              />

              <PhaseSection
                phaseName="deep_dive"
                phaseStatus={getPhaseStatus('deep_dive')}
                content={deepDiveView.content}
                contentLoading={deepDiveView.loading}
                defaultExpanded={false}
                summaryLine={deepDiveSummary.summaryLine}
                collapsedMeta={deepDiveSummary.collapsedMeta}
                expandedMeta={deepDiveSummary.expandedMeta}
                tone={deepDiveSummary.tone}
                accentColor={phaseAccentColor}
                headerControl={
                  deepDiveCompleted && paperId ? (
                    <div className="rounded-lg border border-surface-700/40 bg-surface-900/40 px-3 py-2 [.light_&]:bg-surface-50">
                      <div className="mb-1.5 text-2xs text-surface-500">
                        {S.analysis.rewriteLevel}
                      </div>
                      <LevelSlider
                        compact
                        value={viewLevel}
                        onChange={(key) => void handleLevelChange(key)}
                        disabled={rewriting}
                      />
                    </div>
                  ) : undefined
                }
              >
                <VisualizationGallery
                  visualizations={visualizations}
                  legacyMermaid={mermaidDiagram}
                  loading={getPhaseStatus('deep_dive') === 'running'}
                />
              </PhaseSection>
            </div>
          </div>
        )}

        {visibleTab === 'figures' && (
          <div className="space-y-5">
            <div className="border border-surface-700/45 bg-surface-900/40 px-4 py-4 [.light_&]:bg-white" style={{ borderRadius: 'var(--radius-surface)' }}>
              <div className="flex items-center gap-2">
                <AppIcon name="figures" className="w-4 h-4 text-primary-400" />
                <h3 className="text-sm font-semibold text-surface-100">
                  {S.workbench.figuresTab}
                </h3>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-surface-400">
                {visualSummary.summaryLine || '시각 검증 결과와 Figure를 한곳에서 확인할 수 있습니다.'}
              </p>
            </div>

            <FigureGallery
              figures={figureList}
              paperId={paperId ?? ''}
              loading={getPhaseStatus('visual') === 'running'}
              visualState={figures?.visual_state}
              visualError={figures?.visual_error}
              artifactsReady={figures?.artifacts_ready}
              artifactsError={figures?.artifacts_error}
              onJumpToFigurePage={onJumpToFigurePage}
            />
          </div>
        )}

        {visibleTab === 'tables' && (
          <div className="space-y-5">
            <div className="border border-surface-700/45 bg-surface-900/40 px-4 py-4 [.light_&]:bg-white" style={{ borderRadius: 'var(--radius-surface)' }}>
              <div className="flex items-center gap-2">
                <AppIcon name="tables" className="w-4 h-4 text-primary-400" />
                <h3 className="text-sm font-semibold text-surface-100">
                  {S.workbench.tablesTab}
                </h3>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-surface-400">
                {visualSummary.summaryLine || '복구된 Table 구조와 저장된 CSV/HTML 자산을 한곳에서 확인할 수 있습니다.'}
              </p>
            </div>

            <TableGallery
              tables={tableList}
              loading={getPhaseStatus('visual') === 'running'}
              visualState={tables?.visual_state}
              visualError={tables?.visual_error}
              artifactsReady={tables?.artifacts_ready}
              artifactsError={tables?.artifacts_error}
              onJumpToTablePage={onJumpToTablePage}
            />
          </div>
        )}

        {visibleTab === 'recipe' && (
          <div className="space-y-5">
            <div className="border border-surface-700/45 bg-surface-900/40 px-4 py-4 [.light_&]:bg-white" style={{ borderRadius: 'var(--radius-surface)' }}>
              <div className="flex items-center gap-2">
                <AppIcon name="recipe" className="w-4 h-4 text-primary-400" />
                <h3 className="text-sm font-semibold text-surface-100">
                  {S.workbench.recipeTab}
                </h3>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-surface-400">
                {recipeSummary.summaryLine || '재현 파라미터와 핵심 실험 정보를 먼저 검토하세요.'}
              </p>
            </div>

            <RecipeCard
              recipe={recipe}
              loading={getPhaseStatus('recipe') === 'running'}
            />
          </div>
        )}

        {visibleTab === 'experiment' && (
          <div className="space-y-5">
            {recipeReady && paperId ? (
              <div className="border border-surface-700/45 bg-surface-900/40 px-4 py-4 [.light_&]:bg-white" style={{ borderRadius: 'var(--radius-surface)' }}>
                <div className="mb-3 flex items-center gap-2">
                  <AppIcon name="experiment" className="w-4 h-4 text-emerald-400" />
                  <span className="text-sm font-medium text-surface-200">
                    {S.workbench.experimentTab}
                  </span>
                </div>
                <ExperimentPlanTab
                  paperId={paperId}
                  recipeAvailable={recipeReady}
                />
              </div>
            ) : (
              <ContentState
                icon={(props) => <AppIcon name="experiment" {...props} />}
                title={S.workbench.experimentTab}
                description={S.workbench.experimentPending}
                tone="muted"
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
