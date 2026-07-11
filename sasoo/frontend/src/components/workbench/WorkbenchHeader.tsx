import { AppIcon } from '@/components/icons';
import type { WorkbenchSplitPreset } from '@/hooks/useWorkbenchLayout';

function rgbaFromHex(color: string, alpha: number): string {
  const cleaned = color.replace('#', '');
  if (cleaned.length !== 6) return color;

  const r = parseInt(cleaned.slice(0, 2), 16);
  const g = parseInt(cleaned.slice(2, 4), 16);
  const b = parseInt(cleaned.slice(4, 6), 16);

  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function buildAgentPillStyle(color?: string | null): React.CSSProperties | undefined {
  if (!color) return undefined;

  return {
    color,
    borderColor: rgbaFromHex(color, 0.24),
    backgroundColor: rgbaFromHex(color, 0.1),
  };
}

interface WorkbenchHeaderProps {
  title: string;
  domain?: string | null;
  agentLabel?: string | null;
  agentColor?: string | null;
  pdfCollapsed: boolean;
  activeSplitPreset: WorkbenchSplitPreset | null;
  runStateLabel: string;
  trustStateLabel: string;
  analysisError?: string | null;
  canStartAnalysis: boolean;
  isRunning: boolean;
  primaryActionLabel: string;
  onBack: () => void;
  onTogglePdf: () => void;
  onSplitPresetChange: (preset: WorkbenchSplitPreset) => void;
  onStartAnalysis: () => void;
  onCancelAnalysis: () => void;
}

export default function WorkbenchHeader({
  title,
  domain,
  agentLabel,
  agentColor,
  pdfCollapsed,
  activeSplitPreset,
  runStateLabel,
  trustStateLabel,
  analysisError,
  canStartAnalysis,
  isRunning,
  primaryActionLabel,
  onBack,
  onTogglePdf,
  onSplitPresetChange,
  onStartAnalysis,
  onCancelAnalysis,
}: WorkbenchHeaderProps) {
  const splitPresets: Array<{ label: string; value: WorkbenchSplitPreset }> = [
    { label: '1:2', value: '1:2' },
    { label: '중앙', value: 'center' },
    { label: '2:1', value: '2:1' },
  ];

  return (
    <div className="shrink-0 border-b border-border/45 bg-surface/95 px-4 py-3 backdrop-blur">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-2.5">
          <button
            type="button"
            onClick={onBack}
            title="라이브러리"
            aria-label="라이브러리"
            className="btn-icon-subtle mt-0.5"
          >
            <AppIcon name="back" className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={onTogglePdf}
            title={pdfCollapsed ? 'PDF 표시' : 'PDF 숨기기'}
            aria-label={pdfCollapsed ? 'PDF 표시' : 'PDF 숨기기'}
            className="btn-icon-subtle mt-0.5"
          >
            {pdfCollapsed ? (
              <AppIcon name="panel-open" className="w-4 h-4" />
            ) : (
              <AppIcon name="panel-close" className="w-4 h-4" />
            )}
          </button>

          <div className="min-w-0">
            <h1 className="truncate text-sm font-semibold text-fg tracking-apple-body">
              {title}
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-2xs text-fg-muted">
              {domain && <span className="status-pill border-accent/20 bg-accent/10 text-accent">{domain}</span>}
              {agentLabel && (
                <span
                  className={agentColor ? 'status-pill' : 'status-pill border-border/50 bg-surface/80 text-fg-secondary'}
                  style={buildAgentPillStyle(agentColor)}
                >
                  {agentColor && (
                    <span
                      className="h-1.5 w-1.5 rounded-full"
                      style={{ backgroundColor: agentColor }}
                    />
                  )}
                  {agentLabel}
                </span>
              )}
              <span className="status-pill border-border/50 bg-surface/80 text-fg-secondary">
                {runStateLabel}
              </span>
              <span className="status-pill border-success/20 bg-success/10 text-success">
                {trustStateLabel}
              </span>
            </div>
          </div>
        </div>

        <div className="flex shrink-0 items-start gap-2">
          <div className="flex items-center gap-2">
            {analysisError && (
              <span className="flex items-center gap-1 text-2xs text-danger">
                <AppIcon name="error" className="w-3 h-3" />
                {analysisError}
              </span>
            )}

            <div className="inline-flex items-center rounded-full border border-border/60 bg-surface p-1">
              {splitPresets.map((preset) => {
                const isActive = activeSplitPreset === preset.value;
                return (
                  <button
                    key={preset.value}
                    type="button"
                    onClick={() => onSplitPresetChange(preset.value)}
                    disabled={pdfCollapsed}
                    aria-pressed={isActive}
                    className={`rounded-full px-3 py-1.5 text-2xs font-medium transition-colors ${
                      isActive
                        ? 'bg-accent text-accent-fg'
                        : 'text-fg-muted hover:bg-surface-hover/80 hover:text-fg'
                    } disabled:cursor-not-allowed disabled:opacity-40`}
                  >
                    {preset.label}
                  </button>
                );
              })}
            </div>

            {canStartAnalysis && (
              <button
                onClick={onStartAnalysis}
                className="btn-primary px-4 py-2 text-xs shadow-none"
              >
                <AppIcon name="play" className="w-3.5 h-3.5" />
                {primaryActionLabel}
              </button>
            )}

            {isRunning && (
              <button
                onClick={onCancelAnalysis}
                className="btn-secondary border-danger/20 px-3 py-2 text-xs text-danger hover:bg-danger/10"
                title="분석 취소"
              >
                <AppIcon name="stop" className="w-3 h-3" />
                취소
              </button>
            )}

            {isRunning && (
              <span className="flex items-center gap-1 text-xs text-accent">
                <AppIcon name="spinner" className="w-4 h-4 animate-spin" />
                실행 중
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
