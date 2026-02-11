import { useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ChevronDown,
  ChevronRight,
  FileSearch,
  ImageIcon,
  FlaskConical,
  GitBranch,
  Check,
  Loader2,
  Circle,
  AlertCircle,
} from 'lucide-react';
import {
  getStaticUrl,
  type AnalysisResults,
  type AnalysisStatus,
  type FigureListResponse,
  type Recipe,
  type MermaidDiagram,
  type VisualizationPlan,
  type VisualizationItem,
  type PhaseStatusValue,
  type AnalysisPhase,
} from '@/lib/api';
import { getAgentMeta } from '@/lib/agents';
import FigureGallery from './FigureGallery';
import RecipeCard from './RecipeCard';
import MermaidRenderer from './MermaidRenderer';
import ProgressTracker from './ProgressTracker';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AnalysisPanelProps {
  status: AnalysisStatus | null;
  results: AnalysisResults | null;
  figures: FigureListResponse | null;
  recipe: Recipe | null;
  mermaid: MermaidDiagram | null;
  visualizations: VisualizationPlan | null;
  isRunning: boolean;
  agentName?: string;
  paperId?: string;
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
    icon: FileSearch,
    label: 'Phase 1: Deep Paper Analysis',
    description: 'Comprehensive understanding of methodology, results, and contributions',
    number: 1,
  },
  visual: {
    icon: ImageIcon,
    label: 'Phase 2: Figure & Data Extraction',
    description: 'Extract and interpret all figures, tables, and visual data',
    number: 2,
  },
  recipe: {
    icon: FlaskConical,
    label: 'Phase 3: Reproducibility Recipe',
    description: 'Extract experimental parameters and protocol details',
    number: 3,
  },
  deep_dive: {
    icon: GitBranch,
    label: 'Phase 4: Visualization & Synthesis',
    description: 'Generate process diagrams and visual summaries',
    number: 4,
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
        label: 'Complete',
        classes: 'text-emerald-400 bg-emerald-500/10',
      };
    case 'running':
      return {
        icon: <Loader2 className="w-4 h-4 animate-spin" />,
        label: 'Running',
        classes: 'text-primary-400 bg-primary-500/10',
      };
    case 'error':
      return {
        icon: <AlertCircle className="w-4 h-4" />,
        label: 'Error',
        classes: 'text-red-400 bg-red-500/10',
      };
    case 'pending':
    default:
      return {
        icon: <Circle className="w-4 h-4" />,
        label: 'Pending',
        classes: 'text-surface-500 bg-surface-700/50',
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
  children?: React.ReactNode;
}

function PhaseSection({
  phaseName,
  phaseStatus,
  content,
  defaultExpanded,
  children,
}: PhaseSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const meta = PHASE_META[phaseName];
  const statusInfo = getPhaseStatusInfo(phaseStatus);

  if (!meta) return null;

  const Icon = meta.icon;
  // Allow expanding if: there's content, children, currently running, OR already completed
  const hasContent = !!(content) || !!children || phaseStatus === 'running' || phaseStatus === 'completed';

  const toggleExpanded = useCallback(() => {
    if (hasContent) setExpanded((e) => !e);
  }, [hasContent]);

  return (
    <div
      className={`border rounded-xl overflow-hidden transition-all duration-300 ${
        phaseStatus === 'running'
          ? 'border-primary-500/30 bg-primary-500/5'
          : phaseStatus === 'completed'
            ? 'border-surface-700 bg-surface-800/50'
            : phaseStatus === 'error'
              ? 'border-red-500/20 bg-red-500/5'
              : 'border-surface-700/50 bg-surface-800/30'
      }`}
    >
      {/* Header */}
      <button
        onClick={toggleExpanded}
        className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors ${
          hasContent
            ? 'hover:bg-surface-700/30 cursor-pointer'
            : 'cursor-default opacity-60'
        }`}
        disabled={!hasContent}
        aria-expanded={expanded}
        aria-label={`${meta.label} ${expanded ? '닫기' : '열기'}`}
      >
        {/* Expand/collapse chevron */}
        <span className="text-surface-500 shrink-0">
          {expanded ? (
            <ChevronDown className="w-4 h-4" />
          ) : (
            <ChevronRight className="w-4 h-4" />
          )}
        </span>

        {/* Phase icon */}
        <Icon className="w-4 h-4 text-primary-400 shrink-0" />

        {/* Phase info */}
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-surface-200">
            {meta.label}
          </div>
          <div className="text-2xs text-surface-500 mt-0.5">
            {meta.description}
          </div>
        </div>

        {/* Status badge */}
        <span
          className={`badge text-2xs shrink-0 ${statusInfo.classes}`}
        >
          {statusInfo.icon}
          <span className="ml-1">{statusInfo.label}</span>
        </span>
      </button>

      {/* Content */}
      {expanded && hasContent && (
        <div className="px-4 pb-4 border-t border-surface-700/50">
          {/* Running state */}
          {phaseStatus === 'running' && !content && (
            <div className="flex items-center gap-3 py-6 justify-center" role="status" aria-busy="true">
              <Loader2 className="w-5 h-5 text-primary-400 animate-spin" />
              <span className="text-sm text-surface-400">
                Analyzing...
              </span>
            </div>
          )}

          {/* Completed but content not yet loaded */}
          {phaseStatus === 'completed' && !content && !children && (
            <div className="flex items-center gap-3 py-6 justify-center" role="status" aria-busy="true">
              <Loader2 className="w-5 h-5 text-surface-500 animate-spin" />
              <span className="text-sm text-surface-400">
                Loading results...
              </span>
            </div>
          )}

          {/* Markdown content */}
          {content && (
            <div className="analysis-content mt-4 fade-in-up">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {content}
              </ReactMarkdown>
            </div>
          )}

          {/* Embedded sub-components (figures, recipe, mermaid) */}
          {children && (
            <div className="mt-4 space-y-6 fade-in-up">
              {children}
            </div>
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
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    if (value.length === 0) return '_없음_';
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

  if (phase === 'screening') {
    if (data.summary) lines.push(`${data.summary}\n`);
    if (data.domain) lines.push(`**Domain:** ${data.domain}  `);
    if (data.relevance_score != null) lines.push(`**Relevance:** ${(Number(data.relevance_score) * 100).toFixed(0)}%  `);
    if (data.methodology_type) lines.push(`**Methodology:** ${data.methodology_type}  `);
    if (data.estimated_complexity) lines.push(`**Complexity:** ${data.estimated_complexity}  `);
    if (data.is_experimental != null) lines.push(`**Experimental:** ${data.is_experimental ? 'Yes' : 'No'}  `);
    if (data.has_figures != null) lines.push(`**Has Figures:** ${data.has_figures ? 'Yes' : 'No'}  `);
    if (data.agent_recommended) lines.push(`**Agent:** ${data.agent_recommended}  `);
    const topics = data.key_topics as string[] | undefined;
    if (topics?.length) {
      lines.push('\n**Key Topics:**');
      topics.forEach(t => lines.push(`- ${t}`));
    }
  } else if (phase === 'visual') {
    if (data.quality_summary) lines.push(`${data.quality_summary}\n`);
    if (data.figure_count != null) lines.push(`**Figures:** ${data.figure_count}`);
    if (data.tables_found != null) lines.push(`**Tables:** ${data.tables_found}`);
    if (data.equations_found != null) lines.push(`**Equations:** ${data.equations_found}`);
    const types = data.diagram_types as string[] | undefined;
    if (types?.length) lines.push(`**Diagram Types:** ${types.join(', ')}`);
    const findings = data.key_findings_from_visuals as string[] | undefined;
    if (findings?.length) {
      lines.push('\n**Key Findings:**');
      findings.forEach(f => lines.push(`- ${f}`));
    }
  } else if (phase === 'recipe') {
    if (data.title) lines.push(`### ${data.title}\n`);
    if (data.objective) lines.push(`${data.objective}\n`);

    // Scores as inline badges
    const scoreParts: string[] = [];
    if (data.confidence != null) scoreParts.push(`**Confidence:** ${(Number(data.confidence) * 100).toFixed(0)}%`);
    if (data.reproducibility_score != null) scoreParts.push(`**Reproducibility:** ${(Number(data.reproducibility_score) * 100).toFixed(0)}%`);
    if (scoreParts.length > 0) lines.push(scoreParts.join(' · ') + '\n');

    // ── Parameters as Markdown Table ──
    const params = data.parameters as Array<Record<string, unknown>> | undefined;
    if (params?.length) {
      lines.push('#### Parameters\n');
      lines.push('| # | Parameter | Value | Unit | Notes |');
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
      lines.push('#### Materials\n');
      materials.forEach(m => lines.push(`- ${m}`));
      lines.push('');
    }

    // ── Equipment ──
    const equipment = data.equipment as string[] | undefined;
    if (equipment?.length) {
      lines.push('#### Equipment\n');
      equipment.forEach(e => lines.push(`- ${e}`));
      lines.push('');
    }

    // ── Steps ──
    const steps = data.steps as string[] | undefined;
    if (steps?.length) {
      lines.push('#### Experimental Steps\n');
      steps.forEach((s, i) => lines.push(`${i + 1}. ${s}`));
      lines.push('');
    }

    // ── Critical Notes ──
    const notes = data.critical_notes as string[] | undefined;
    if (notes?.length) {
      lines.push('#### Critical Notes\n');
      notes.forEach(n => lines.push(`- ${n}`));
      lines.push('');
    }

    // ── Missing Info ──
    const missing = data.missing_info as string[] | undefined;
    if (missing?.length) {
      lines.push('#### Missing Information\n');
      missing.forEach(m => lines.push(`- ${m}`));
      lines.push('');
    }

    if (data.expected_results) lines.push(`**Expected Results:** ${data.expected_results}\n`);
    if (data.safety_notes) lines.push(`**Safety Notes:** ${data.safety_notes}\n`);
  } else if (phase === 'deep_dive') {
    if (data.detailed_analysis) lines.push(`${data.detailed_analysis}\n`);
    if (data.novelty_assessment) lines.push(`**Novelty:** ${data.novelty_assessment}\n`);
    if (data.comparison_to_prior_work) lines.push(`**Comparison to Prior Work:** ${data.comparison_to_prior_work}\n`);
    const sections: [string, string][] = [
      ['strengths', '✅ Strengths'],
      ['weaknesses', '⚠️ Weaknesses'],
      ['suggested_improvements', '💡 Suggested Improvements'],
      ['practical_applications', '🔧 Practical Applications'],
      ['follow_up_questions', '❓ Follow-up Questions'],
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
        <p className="text-sm text-red-300">Failed to generate illustration</p>
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
          <GitBranch className="w-4 h-4 text-primary-400" />
          <span className="text-sm font-semibold text-surface-200">
            Visualizations
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
              <p className="text-2xs text-surface-500 leading-relaxed">
                {item.description}
              </p>
            )}
            {item.tool === 'mermaid' && item.mermaid_code ? (
              <MermaidRenderer
                diagram={{
                  paper_id: visualizations.paper_id,
                  mermaid_code: item.mermaid_code,
                  diagram_type: item.diagram_type,
                  description: item.description,
                }}
                loading={false}
              />
            ) : item.tool === 'paperbanana' ? (
              <PaperBananaViewer item={item} />
            ) : item.status === 'error' ? (
              <div className="text-sm text-red-400 py-2">
                {item.error_message || 'Generation failed'}
              </div>
            ) : (
              <div className="flex items-center gap-2 py-4 justify-center" role="status" aria-busy="true">
                <Loader2 className="w-4 h-4 text-primary-400 animate-spin" />
                <span className="text-xs text-surface-400">Generating...</span>
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
          <GitBranch className="w-4 h-4 text-primary-400" />
          Visualizations
        </h3>
        <div className="card flex flex-col items-center justify-center py-8 text-center">
          <Loader2 className="w-6 h-6 text-primary-400 animate-spin mb-2" />
          <p className="text-sm text-surface-400">
            Generating visualizations...
          </p>
          <p className="text-2xs text-surface-500 mt-1">
            This may take 1-2 minutes
          </p>
        </div>
      </div>
    );
  }

  // Fallback: legacy single mermaid diagram
  return (
    <MermaidRenderer
      diagram={legacyMermaid}
      loading={loading}
    />
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function AnalysisPanel({
  status,
  results,
  figures,
  recipe,
  mermaid: mermaidDiagram,
  visualizations,
  isRunning,
  agentName,
  paperId,
}: AnalysisPanelProps) {
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
      <div className="flex flex-col items-center justify-center h-full text-center px-8">
        <div className="w-16 h-16 rounded-2xl bg-surface-800 border border-surface-700 flex items-center justify-center mb-4">
          <FileSearch className="w-8 h-8 text-surface-500" />
        </div>
        <h3 className="text-lg font-semibold text-surface-200 mb-2">
          No Analysis Results
        </h3>
        <p className="text-sm text-surface-400 max-w-sm">
          Start an analysis to see AI-powered insights about this paper,
          including figure extraction, reproducibility parameters, and
          process diagrams.
        </p>
      </div>
    );
  }

  const agentMeta = getAgentMeta(agentName);

  return (
    <div className="space-y-3 py-4 px-4 overflow-y-auto flex-1 min-h-0">
      {/* Agent badge */}
      {agentMeta && (
        <div className="mb-3">
          <span className={`inline-flex items-center gap-2 px-2.5 py-1.5 rounded-lg ${agentMeta.bgColor} ${agentMeta.color} text-xs font-medium border ${agentMeta.borderColor}`}>
            <img
              src={agentMeta.image}
              alt={agentMeta.name}
              className="w-6 h-6 rounded-md object-cover"
            />
            <span>{agentMeta.name}</span>
            <span className="text-surface-500 font-normal">{agentMeta.personality}</span>
          </span>
        </div>
      )}

      {/* Progress tracker (scrolls with content) */}
      {status && status.overall_status !== 'pending' && (
        <ProgressTracker
          phases={status.phases}
          overallProgress={status.progress_pct}
        />
      )}

      {/* Phase 1: Screening */}
      <PhaseSection
        phaseName="screening"
        phaseStatus={getPhaseStatus('screening')}
        content={getPhaseContent('screening')}
        defaultExpanded={true}
      />

      {/* Phase 2: Visual */}
      <PhaseSection
        phaseName="visual"
        phaseStatus={getPhaseStatus('visual')}
        content={getPhaseContent('visual')}
        defaultExpanded={getPhaseStatus('visual') === 'completed'}
      >
        <FigureGallery
          figures={figures?.figures ?? []}
          paperId={paperId ?? ''}
          loading={getPhaseStatus('visual') === 'running'}
        />
      </PhaseSection>

      {/* Phase 3: Recipe (rendered by RecipeCard, no markdown content) */}
      <PhaseSection
        phaseName="recipe"
        phaseStatus={getPhaseStatus('recipe')}
        content={null}
        defaultExpanded={getPhaseStatus('recipe') === 'completed'}
      >
        <RecipeCard
          recipe={recipe}
          loading={getPhaseStatus('recipe') === 'running'}
        />
      </PhaseSection>

      {/* Phase 4: Deep Dive + Visualizations */}
      <PhaseSection
        phaseName="deep_dive"
        phaseStatus={getPhaseStatus('deep_dive')}
        content={getPhaseContent('deep_dive')}
        defaultExpanded={getPhaseStatus('deep_dive') === 'completed'}
      >
        <VisualizationGallery
          visualizations={visualizations}
          legacyMermaid={mermaidDiagram}
          loading={getPhaseStatus('deep_dive') === 'running'}
        />
      </PhaseSection>
    </div>
  );
}
