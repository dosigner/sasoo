import type { Paper } from '@/lib/api';
import { getAgentMeta } from '@/lib/agents';
import { S } from '@/lib/strings';
import { AppIcon } from '@/components/icons';

export function formatPaperDate(dateStr: string | null): string {
  if (!dateStr) return S.upload.noTimestamp;

  return new Date(dateStr).toLocaleDateString('ko-KR', {
    month: 'short',
    day: 'numeric',
  });
}

function paperStatusLabel(status: Paper['status']): string {
  switch (status) {
    case 'completed':
      return S.status.analyzed;
    case 'analyzing':
      return S.status.analyzing;
    case 'error':
      return S.status.error;
    case 'pending':
    default:
      return S.status.pending;
  }
}

function paperStatusClass(status: Paper['status']): string {
  switch (status) {
    case 'completed':
      return 'border-success/20 bg-success/10 text-success';
    case 'analyzing':
      return 'border-accent/20 bg-accent/10 text-accent';
    case 'error':
      return 'border-danger/20 bg-danger/10 text-danger';
    case 'pending':
    default:
      return 'border-warning/20 bg-warning/10 text-warning';
  }
}

export default function RecentPaperRow({
  paper,
  metaLabel,
  metaValue,
  onOpen,
}: {
  paper: Paper;
  metaLabel: string;
  metaValue: string;
  onOpen: (id: string) => void;
}) {
  const agent = getAgentMeta(paper.agent_used);

  return (
    <button
      type="button"
      onClick={() => onOpen(String(paper.id))}
      className="group w-full rounded-surface bg-surface/30 px-4 py-3.5 text-left transition-all duration-200 hover:bg-surface/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
      aria-label={`${paper.title} 워크벤치 열기`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-2xs ${paperStatusClass(paper.status)}`}>
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            {paperStatusLabel(paper.status)}
          </div>
          <h3 className="mt-3 line-clamp-2 text-base font-semibold leading-6 text-fg transition-colors group-hover:text-fg">
            {paper.title}
          </h3>
          <p className="mt-1.5 line-clamp-1 text-sm leading-5 text-fg-muted">
            {paper.authors || paper.journal || paper.domain}
          </p>
        </div>
        <span className="mt-0.5 shrink-0 rounded-full bg-surface/70 p-2 text-fg-muted transition-colors group-hover:text-fg">
          <AppIcon name="arrow-right" className="h-3.5 w-3.5" />
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm leading-5 text-fg-muted">
        <span>{metaLabel} {metaValue}</span>
        <span className="h-1 w-1 rounded-full bg-border" />
        <span>{paper.domain}</span>
        {agent && (
          <>
            <span className="h-1 w-1 rounded-full bg-border" />
            <span>{agent.nameKo}</span>
          </>
        )}
      </div>
    </button>
  );
}
