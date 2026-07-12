import { useEffect, useState, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getPapers, getCostSummary, type Paper } from '@/lib/api';
import { S } from '@/lib/strings';
import { AppIcon, type AppIconName } from '@/components/icons';
import UploadPanel from '@/components/home/UploadPanel';
import RecentPaperRow, { formatPaperDate } from '@/components/home/RecentPaperRow';

const QUICK_ACTIONS: { to: string; icon: AppIconName; title: string; desc: string }[] = [
  { to: '/agents', icon: 'agents', title: S.home.actionAgents, desc: S.home.actionAgentsDesc },
  { to: '/library', icon: 'library', title: S.home.actionLibrary, desc: S.home.actionLibraryDesc },
];

function todayLabel(): string {
  return new Date().toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  });
}

export default function Home() {
  const navigate = useNavigate();
  const [recentAnalyses, setRecentAnalyses] = useState<Paper[]>([]);
  const [recentLibrary, setRecentLibrary] = useState<Paper[]>([]);
  const [monthCost, setMonthCost] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    Promise.all([
      getPapers({ page: 1, page_size: 4, sort_by: 'analyzed_at', sort_order: 'desc' }),
      getPapers({ page: 1, page_size: 4, sort_by: 'created_at', sort_order: 'desc' }),
    ])
      .then(([analysisResponse, libraryResponse]) => {
        if (cancelled) return;
        setRecentAnalyses(analysisResponse.papers.filter((p) => p.analyzed_at).slice(0, 4));
        setRecentLibrary(libraryResponse.papers.slice(0, 4));
      })
      .catch(() => {
        if (cancelled) return;
        setRecentAnalyses([]);
        setRecentLibrary([]);
      });

    getCostSummary()
      .then((data) => {
        if (!cancelled) setMonthCost(data.current_month?.cost_usd ?? 0);
      })
      .catch(() => {
        if (!cancelled) setMonthCost(null);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleOpenRecent = useCallback(
    (id: string) => navigate(`/workbench/${id}`),
    [navigate]
  );

  return (
    <div className="page-container-compact">
      <section className="mb-6">
        <div className="text-2xs font-semibold uppercase tracking-[0.08em] text-fg-muted">
          {todayLabel()}
        </div>
        <h1 className="mt-1.5 text-[1.45rem] font-semibold tracking-[-0.03em] text-fg">
          {S.home.greeting}
        </h1>
        <p className="mt-1 text-sm text-fg-muted">{S.home.subGreeting}</p>
      </section>

      <UploadPanel />

      <section className="mt-6">
        <div className="text-2xs font-semibold uppercase tracking-[0.08em] text-fg-muted">
          {S.home.quickActions}
        </div>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          {QUICK_ACTIONS.map((action) => (
            <Link key={action.to} to={action.to} className="card-hover flex items-center gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-control border border-border bg-bg">
                <AppIcon name={action.icon} className="h-4 w-4 text-fg-secondary" />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-fg">{action.title}</span>
                <span className="mt-0.5 block truncate text-sm text-fg-muted">{action.desc}</span>
              </span>
            </Link>
          ))}
        </div>
      </section>

      <section className="mt-6 grid gap-4 xl:grid-cols-2">
        <div className="card">
          <div className="text-2xs font-semibold uppercase tracking-[0.08em] text-fg-muted">
            {S.home.recentAnalyses}
          </div>
          <div className="mt-3 grid gap-3">
            {recentAnalyses.length > 0 ? (
              recentAnalyses.map((paper) => (
                <RecentPaperRow
                  key={`recent-analysis-${paper.id}`}
                  paper={paper}
                  metaLabel={S.upload.lastAnalyzed}
                  metaValue={formatPaperDate(paper.analyzed_at)}
                  onOpen={handleOpenRecent}
                />
              ))
            ) : (
              <p className="py-4 text-sm leading-6 text-fg-muted">{S.home.recentEmpty}</p>
            )}
          </div>
        </div>

        <div className="card">
          <div className="text-2xs font-semibold uppercase tracking-[0.08em] text-fg-muted">
            {S.home.recentLibrary}
          </div>
          <div className="mt-3 grid gap-3">
            {recentLibrary.length > 0 ? (
              recentLibrary.map((paper) => (
                <RecentPaperRow
                  key={`recent-library-${paper.id}`}
                  paper={paper}
                  metaLabel={S.upload.addedLabel}
                  metaValue={formatPaperDate(paper.created_at)}
                  onOpen={handleOpenRecent}
                />
              ))
            ) : (
              <p className="py-4 text-sm leading-6 text-fg-muted">{S.home.recentEmpty}</p>
            )}
          </div>
        </div>
      </section>

      {monthCost !== null && (
        <section className="mt-4 card flex items-center justify-between gap-4">
          <div>
            <div className="text-2xs font-semibold uppercase tracking-[0.08em] text-fg-muted">
              {S.home.costTitle}
            </div>
            <div className="mt-1.5 font-mono text-lg text-fg">${monthCost.toFixed(2)}</div>
          </div>
          <Link
            to="/settings"
            className="shrink-0 text-sm text-accent transition-colors hover:text-accent-hover"
          >
            {S.home.costOpenSettings}
          </Link>
        </section>
      )}
    </div>
  );
}
