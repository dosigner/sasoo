import { useEffect, useId, useRef, useState } from 'react';
import { AppIcon } from '@/components/icons';
import AgentAvatar from '@/components/AgentAvatar';
import type { AgentMeta } from '@/lib/agents';
import type { WorkbenchSplitPreset } from '@/hooks/useWorkbenchLayout';
import { S } from '@/lib/strings';
import { DOMAIN_LABELS, type WorkbenchStatusTone } from '@/lib/workbenchSummaries';

const STATUS_TONE_CLASS: Record<WorkbenchStatusTone, string> = {
  accent: 'chip-tint',
  success: 'chip-tint chip-tint-success',
  danger: 'chip-tint chip-tint-danger',
};

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

// ---------------------------------------------------------------------------
// Persona badge dropdown — 담당 에이전트 변경
// ---------------------------------------------------------------------------

interface AgentBadgeDropdownProps {
  agentLabel: string;
  agentColor?: string | null;
  agents: AgentMeta[];
  currentAgentKey?: string | null;
  changing?: boolean;
  onSelect: (agent: AgentMeta) => void;
}

function AgentBadgeDropdown({
  agentLabel,
  agentColor,
  agents,
  currentAgentKey,
  changing = false,
  onSelect,
}: AgentBadgeDropdownProps) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listboxId = useId();

  const selectedIndex = agents.findIndex(
    (a) => a.key.toLowerCase() === (currentAgentKey ?? '').toLowerCase(),
  );

  // 열릴 때 현재 선택 항목으로 활성 인덱스 초기화 + 리스트 포커스
  useEffect(() => {
    if (open) {
      setActiveIndex(selectedIndex >= 0 ? selectedIndex : 0);
      listRef.current?.focus();
    }
  }, [open, selectedIndex]);

  // 바깥 클릭 시 닫기
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [open]);

  function commit(index: number) {
    const agent = agents[index];
    if (agent) onSelect(agent);
    setOpen(false);
    triggerRef.current?.focus();
  }

  function handleListKeyDown(e: React.KeyboardEvent) {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setActiveIndex((i) => Math.min(agents.length - 1, i + 1));
        break;
      case 'ArrowUp':
        e.preventDefault();
        setActiveIndex((i) => Math.max(0, i - 1));
        break;
      case 'Home':
        e.preventDefault();
        setActiveIndex(0);
        break;
      case 'End':
        e.preventDefault();
        setActiveIndex(agents.length - 1);
        break;
      case 'Enter':
      case ' ':
        e.preventDefault();
        commit(activeIndex);
        break;
      case 'Escape':
      case 'Tab':
        setOpen(false);
        triggerRef.current?.focus();
        break;
      default:
        break;
    }
  }

  const canOpen = agents.length > 0 && !changing;

  return (
    <div ref={containerRef} className="relative inline-flex">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => canOpen && setOpen((o) => !o)}
        disabled={!canOpen}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`담당 에이전트: ${agentLabel}. 변경하려면 여세요`}
        className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 text-2xs font-medium text-fg-secondary transition-colors duration-150 hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-60"
        style={agentColor ? { color: agentColor } : undefined}
      >
        {changing ? (
          <AppIcon name="spinner" className="h-3 w-3 animate-spin" />
        ) : agentColor ? (
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: agentColor }} />
        ) : null}
        {agentLabel}
        {canOpen && <AppIcon name="chevron-down" className="h-3 w-3 opacity-70" />}
      </button>

      {open && (
        <ul
          ref={listRef}
          id={listboxId}
          role="listbox"
          tabIndex={-1}
          aria-label="담당 에이전트 선택"
          aria-activedescendant={`${listboxId}-opt-${activeIndex}`}
          onKeyDown={handleListKeyDown}
          className="absolute left-0 top-full z-50 mt-1.5 max-h-72 w-56 overflow-y-auto rounded-lg border border-border bg-surface p-1 shadow-lg backdrop-blur-sm focus:outline-hidden"
        >
          {agents.map((agent, index) => {
            const isSelected = index === selectedIndex;
            const isActive = index === activeIndex;
            return (
              <li
                key={agent.key}
                id={`${listboxId}-opt-${index}`}
                role="option"
                aria-selected={isSelected}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => commit(index)}
                className={`flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs ${
                  isActive
                    ? 'bg-surface-hover text-fg'
                    : 'text-fg-secondary'
                }`}
              >
                <AgentAvatar name={agent.nameKo || agent.name} color={agent.color} size="sm" />
                <span className="min-w-0 flex-1 truncate">{agent.nameKo || agent.name}</span>
                {isSelected && <AppIcon name="success" className="h-3.5 w-3.5 text-accent" />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

interface WorkbenchHeaderProps {
  title: string;
  domain?: string | null;
  agentLabel?: string | null;
  agentColor?: string | null;
  agents?: AgentMeta[];
  currentAgentKey?: string | null;
  agentChanging?: boolean;
  onSelectAgent?: (agent: AgentMeta) => void;
  pdfCollapsed: boolean;
  activeSplitPreset: WorkbenchSplitPreset | null;
  statusLabel: string;
  statusTone: WorkbenchStatusTone;
  analysisError?: string | null;
  canStartAnalysis: boolean;
  isRunning: boolean;
  primaryActionLabel: string;
  /** 완료된 phase 결과가 현재 설정과 다른 모델로 만들어졌으면 그 모델명(스펙 §D). */
  staleModel?: string | null;
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
  agents,
  currentAgentKey,
  agentChanging,
  onSelectAgent,
  pdfCollapsed,
  activeSplitPreset,
  statusLabel,
  statusTone,
  analysisError,
  canStartAnalysis,
  isRunning,
  primaryActionLabel,
  staleModel,
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
    <div className="relative z-40 shrink-0 border-b border-border/45 bg-surface/95 px-4 py-3 backdrop-blur-sm">
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
              {domain && <span className="chip-tint">{DOMAIN_LABELS[domain] ?? domain}</span>}
              {agentLabel && (
                onSelectAgent && agents && agents.length > 0 ? (
                  <AgentBadgeDropdown
                    agentLabel={agentLabel}
                    agentColor={agentColor}
                    agents={agents}
                    currentAgentKey={currentAgentKey}
                    changing={agentChanging}
                    onSelect={onSelectAgent}
                  />
                ) : (
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
                )
              )}
              <span className={STATUS_TONE_CLASS[statusTone]}>
                {statusLabel}
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

            {canStartAnalysis && staleModel && (
              <span
                className="status-pill border-warning/20 bg-warning/10 text-warning"
                title={S.workbench.staleModelHint}
              >
                <AppIcon name="warning" className="w-3 h-3" />
                {S.workbench.staleModelBadge(staleModel)}
              </span>
            )}

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
