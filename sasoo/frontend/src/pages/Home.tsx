import { useEffect, useState, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getPapers, getCostSummary, type Paper } from '@/lib/api';
import { S } from '@/lib/strings';
import UploadPanel from '@/components/home/UploadPanel';
import RecentPaperRow, { formatPaperDate } from '@/components/home/RecentPaperRow';

function todayLabel(): string {
  return new Date().toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  });
}

interface CostTileData {
  costUsd: number;
  papersAnalyzed: number;
  // 지난달 비용이 있을 때만 채워지는 부호 포함 증감률 문자열 (예: "+12%", "-8%")
  delta: string | null;
}

function prevMonthKey(month: string): string {
  const [y, m] = month.split('-').map(Number);
  if (!y || !m) return '';
  return m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, '0')}`;
}

export default function Home() {
  const navigate = useNavigate();
  const [recentPapers, setRecentPapers] = useState<Paper[]>([]);
  const [papersTotal, setPapersTotal] = useState<number | null>(null);
  const [cost, setCost] = useState<CostTileData | null>(null);

  useEffect(() => {
    let cancelled = false;

    // 분석했으면 분석 시각, 아니면 추가 시각 — 마지막 활동 기준으로 정렬한다.
    getPapers({ page: 1, page_size: 8, sort_by: 'created_at', sort_order: 'desc' })
      .then((response) => {
        if (cancelled) return;
        const lastActivity = (p: Paper) => p.analyzed_at ?? p.created_at ?? '';
        const sorted = [...response.papers].sort((a, b) =>
          lastActivity(b).localeCompare(lastActivity(a))
        );
        setRecentPapers(sorted.slice(0, 5));
        setPapersTotal(response.total);
      })
      .catch(() => {
        if (cancelled) return;
        setRecentPapers([]);
        setPapersTotal(null);
      });

    getCostSummary()
      .then((data) => {
        if (cancelled) return;
        const current = data.current_month;
        const prev = data.monthly_costs?.find(
          (mc) => mc.month === prevMonthKey(current?.month ?? '')
        );
        let delta: string | null = null;
        if (current && prev && prev.total_usd > 0) {
          const pct = ((current.cost_usd - prev.total_usd) / prev.total_usd) * 100;
          delta = `${pct >= 0 ? '+' : '-'}${Math.abs(pct).toFixed(0)}%`;
        }
        setCost({
          costUsd: current?.cost_usd ?? 0,
          papersAnalyzed: current?.papers_analyzed ?? 0,
          delta,
        });
      })
      .catch(() => {
        if (!cancelled) setCost(null);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleOpenRecent = useCallback(
    (id: string) => navigate(`/workbench/${id}`),
    [navigate]
  );

  const costMetaLine = cost
    ? cost.papersAnalyzed > 0
      ? [S.home.costMeta(cost.papersAnalyzed), cost.delta ? S.home.costDelta(cost.delta) : null]
          .filter(Boolean)
          .join(' · ')
      : S.home.costEmptyMeta
    : null;

  return (
    <div className="page-container-compact">
      <div className="home-stagger">
        <section className="mb-5">
          <div className="text-2xs font-semibold uppercase tracking-[0.08em] text-fg-muted">
            {todayLabel()}
          </div>
          <h1 className="mt-1.5 text-[1.45rem] font-semibold tracking-[-0.03em] text-fg">
            {S.home.greeting}
          </h1>
          <p className="mt-1 text-sm text-fg-muted">{S.home.subGreeting}</p>
        </section>

        <UploadPanel />

        <div className="mt-4 grid items-start gap-4 lg:grid-cols-3">
          <section className="card lg:col-span-2">
            <div className="flex items-center justify-between gap-3">
              <div className="text-2xs font-semibold uppercase tracking-[0.08em] text-fg-muted">
                {S.home.recentPapers}
              </div>
              {recentPapers.length > 0 && (
                <Link
                  to="/library"
                  className="text-sm text-accent transition-colors hover:text-accent-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
                >
                  {S.home.viewAll}
                </Link>
              )}
            </div>
            <div className="mt-3 grid gap-3">
              {recentPapers.length > 0 ? (
                recentPapers.map((paper) => (
                  <RecentPaperRow
                    key={`recent-${paper.id}`}
                    paper={paper}
                    metaLabel={paper.analyzed_at ? S.upload.lastAnalyzed : S.upload.addedLabel}
                    metaValue={formatPaperDate(paper.analyzed_at ?? paper.created_at)}
                    onOpen={handleOpenRecent}
                  />
                ))
              ) : (
                <p className="py-4 text-sm leading-6 text-fg-muted">{S.home.recentEmpty}</p>
              )}
            </div>
          </section>

          <div className="grid gap-4">
            {cost !== null && (
              <section className="card">
                <div className="text-2xs font-semibold uppercase tracking-[0.08em] text-fg-muted">
                  {S.home.costTitle}
                </div>
                <div className="mt-2 font-mono text-[1.7rem] leading-none tracking-[-0.01em] text-fg tabular-nums">
                  ${cost.costUsd.toFixed(2)}
                </div>
                {costMetaLine && (
                  <p className="mt-2 text-sm leading-5 text-fg-muted">{costMetaLine}</p>
                )}
                <Link
                  to="/settings#cost"
                  className="mt-3 inline-flex text-sm text-accent transition-colors hover:text-accent-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
                >
                  {S.home.costOpenSettings}
                </Link>
              </section>
            )}

            {papersTotal !== null && (
              <section className="card">
                <div className="text-2xs font-semibold uppercase tracking-[0.08em] text-fg-muted">
                  {S.home.libraryTitle}
                </div>
                <div className="mt-2 text-[1.7rem] font-semibold leading-none tracking-[-0.01em] text-fg tabular-nums">
                  {papersTotal}
                  <span className="ml-1 text-base font-normal text-fg-muted">
                    {S.home.libraryUnit}
                  </span>
                </div>
                <Link
                  to="/library"
                  className="mt-3 inline-flex text-sm text-accent transition-colors hover:text-accent-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
                >
                  {S.home.libraryOpen}
                </Link>
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
