import { useState, useEffect, useMemo } from 'react';
import {
  DollarSign,
  BarChart3,
  FileText,
  Cpu,
  ChevronDown,
} from 'lucide-react';
import { getCostSummary, type CostSummary } from '@/lib/api';
import { S } from '@/lib/strings';

// ---------------------------------------------------------------------------
// Local strings — CostDashboard C1 재구성 전용 신규 문자열.
// strings.ts가 다른 세션에서 편집 중(dirty)이라 여기 로컬로 둔다.
// TODO(strings.ts 이관 대상): L.subtitleThisMonth / L.subtitlePapersMid /
// L.deltaDown / L.deltaUp / L.deltaFlat / L.reviewQueueWaiting /
// L.callsSuffix / L.itemsSuffix
// ---------------------------------------------------------------------------

const L = {
  // 히어로 부제 텍스트 조각 — 논문 수·편당 평균 수치는 JSX에서
  // font-mono tabular-nums span으로 감싸 조립한다 (전체 표시 문구는
  // "이번 달 · 논문 N편 분석 · 편당 평균 $X.XX"로 기존과 동일).
  subtitleThisMonth: '이번 달 · 논문 ',
  subtitlePapersMid: '편 분석 · 편당 평균 ',
  deltaDown: (pct: number) => `▼ ${pct}% 지난달보다 적게`,
  deltaUp: (pct: number) => `▲ ${pct}% 지난달보다 많이`,
  deltaFlat: '지난달과 동일',
  reviewQueueWaiting: '표 검증 대기',
  callsSuffix: '회',
  itemsSuffix: '건',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatCurrency(amount: number): string {
  return `$${amount.toFixed(2)}`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function getBarHeight(value: number, maxValue: number): number {
  if (maxValue === 0) return 0;
  return Math.max(4, Math.round((value / maxValue) * 100));
}

function shortModelName(model: string): string {
  if (model.includes('gemini')) {
    if (model.includes('flash')) return 'Gemini Flash';
    if (model.includes('pro')) return 'Gemini Pro';
    return 'Gemini';
  }
  if (model.includes('claude') || model.includes('sonnet')) return 'Claude Sonnet';
  if (model.includes('haiku')) return 'Claude Haiku';
  return model.length > 20 ? model.slice(0, 20) + '...' : model;
}

type MonthlyCost = CostSummary['monthly_costs'][number];

// ---------------------------------------------------------------------------
// Sparkbar — 6개월 요약 막대. 현재 월만 accent, 과거는 뉴트럴.
// ---------------------------------------------------------------------------

interface MonthBarsProps {
  months: MonthlyCost[];
  currentMonthKey: string;
  maxHeightClass: string;
  barWidthClass: string;
  gapClass: string;
  showLabels?: boolean;
}

function MonthBars({
  months,
  currentMonthKey,
  maxHeightClass,
  barWidthClass,
  gapClass,
  showLabels = false,
}: MonthBarsProps) {
  const maxCost = Math.max(...months.map((m) => m.total_usd), 0.01);

  return (
    <div className={`flex items-end ${gapClass} ${maxHeightClass}`}>
      {months.map((month) => {
        const isCurrent = month.month === currentMonthKey;
        return (
          <div
            key={month.month}
            className={`group relative flex h-full flex-col items-center justify-end ${
              showLabels ? 'flex-1' : barWidthClass
            }`}
          >
            <div className="flex w-full flex-1 flex-col-reverse items-stretch">
              <div
                className={`w-full rounded-t transition-colors ${
                  isCurrent
                    ? 'bg-accent group-hover:bg-accent-hover'
                    : 'bg-fg-muted/30 group-hover:bg-fg-muted/50'
                }`}
                style={{ height: `${getBarHeight(month.total_usd, maxCost)}%` }}
              />
            </div>
            {showLabels && (
              <div className="mt-1 text-2xs text-fg-muted">
                {S.cost.monthLabel(month.month.slice(5))}
              </div>
            )}
            {/* Tooltip */}
            <div className="absolute bottom-full left-1/2 z-10 mb-1 hidden -translate-x-1/2 group-hover:block">
              <div className="whitespace-nowrap rounded border border-border bg-surface px-2 py-1 shadow-lg">
                <div className="text-2xs text-fg-muted">
                  {S.cost.monthLabel(month.month.slice(5))}
                </div>
                <div className="text-2xs font-mono tabular-nums text-fg-secondary">
                  {formatCurrency(month.total_usd)}
                </div>
                <div className="text-2xs text-fg-muted">
                  {S.cost.paperCount(month.papers_analyzed)}
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Accordion — 시맨틱 details/summary. 라이브러리 없이 키보드 접근 가능.
// ---------------------------------------------------------------------------

interface AccordionProps {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}

function Accordion({ icon, title, children }: AccordionProps) {
  return (
    <details className="card group/acc">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 [&::-webkit-details-marker]:hidden">
        <span className="flex items-center gap-2 text-xs font-semibold text-fg-secondary">
          {icon}
          {title}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-fg-muted transition-transform duration-200 group-open/acc:rotate-180" />
      </summary>
      <div className="mt-3 border-t border-border pt-3">{children}</div>
    </details>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface CostDashboardProps {
  refreshKey?: number;
}

export default function CostDashboard({ refreshKey }: CostDashboardProps) {
  const [costData, setCostData] = useState<CostSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchCosts() {
      setLoading(true);
      setError(null);
      try {
        const data = await getCostSummary();
        if (!cancelled) {
          setCostData(data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : S.settings.costLoadFailed
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchCosts();
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const monthlyChartData = useMemo(() => {
    if (!costData?.monthly_costs || costData.monthly_costs.length === 0)
      return { months: [] as MonthlyCost[] };
    return { months: costData.monthly_costs };
  }, [costData]);

  // Hero metrics: current-month cost, MoM delta (computed client-side from the
  // monthly array — backend is unchanged), and per-paper average this month.
  const hero = useMemo(() => {
    if (!costData) return null;
    const months = costData.monthly_costs ?? [];
    const currentMonthKey = costData.current_month.month;
    const currentIdx = months.findIndex((m) => m.month === currentMonthKey);
    const previousEntry = currentIdx > 0 ? months[currentIdx - 1] : null;

    const currentCost = costData.current_month.cost_usd;
    const papersThisMonth = costData.current_month.papers_analyzed;
    const avgThisMonth = papersThisMonth > 0 ? currentCost / papersThisMonth : 0;

    let deltaKind: 'down' | 'up' | 'flat' | null = null;
    let deltaPctAbs = 0;
    if (previousEntry && previousEntry.total_usd > 0) {
      const rawPct =
        ((currentCost - previousEntry.total_usd) / previousEntry.total_usd) * 100;
      const rounded = Math.round(rawPct);
      deltaPctAbs = Math.abs(rounded);
      deltaKind = rounded === 0 ? 'flat' : rounded < 0 ? 'down' : 'up';
    }

    return {
      currentMonthKey,
      currentCost,
      papersThisMonth,
      avgThisMonth,
      deltaKind,
      deltaPctAbs,
    };
  }, [costData]);

  if (loading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="card">
          <div className="mb-3 h-3 w-20 rounded bg-border" />
          <div className="mb-2 h-9 w-32 rounded bg-border" />
          <div className="h-3 w-48 rounded bg-border" />
        </div>
        <div className="h-10 rounded-surface bg-border/40" />
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="card h-10" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card flex flex-col items-center justify-center py-8 text-center">
        <DollarSign className="w-8 h-8 text-fg-muted mb-2" />
        <p className="text-sm text-fg-muted">{error}</p>
      </div>
    );
  }

  if (!costData || !hero) return null;

  const hasData = costData.totals.total_cost_usd > 0 || costData.totals.total_tokens_in > 0;

  if (!hasData) {
    return (
      <div className="card flex flex-col items-center justify-center py-10 text-center">
        <BarChart3 className="w-8 h-8 text-fg-muted mb-3" />
        <p className="text-sm text-fg-secondary font-medium">{S.cost.noData}</p>
        <p className="text-2xs text-fg-muted mt-1 max-w-xs">{S.cost.noDataDesc}</p>
      </div>
    );
  }

  const totalPhaseCalls = Object.values(costData.efficiency.phase_call_counts).reduce(
    (sum, n) => sum + n,
    0
  );

  return (
    <div className="space-y-4">
      {/* Hero line: this month's cost + MoM delta + 6-month sparkbar */}
      <div className="card">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-2xs uppercase tracking-wider text-fg-muted">
              {S.cost.thisMonth}
            </div>
            <div className="mt-1 flex items-baseline gap-2 flex-wrap">
              <span className="font-mono tabular-nums text-3xl font-semibold text-fg">
                {formatCurrency(hero.currentCost)}
              </span>
              {hero.deltaKind === 'down' && (
                <span className="text-xs font-mono tabular-nums text-success">
                  {L.deltaDown(hero.deltaPctAbs)}
                </span>
              )}
              {hero.deltaKind === 'up' && (
                <span className="text-xs font-mono tabular-nums text-fg-muted">
                  {L.deltaUp(hero.deltaPctAbs)}
                </span>
              )}
              {hero.deltaKind === 'flat' && (
                <span className="text-xs text-fg-muted">{L.deltaFlat}</span>
              )}
            </div>
            <div className="mt-1 text-xs text-fg-muted">
              {L.subtitleThisMonth}
              <span className="font-mono tabular-nums">{hero.papersThisMonth}</span>
              {L.subtitlePapersMid}
              <span className="font-mono tabular-nums">
                {formatCurrency(hero.avgThisMonth)}
              </span>
            </div>
          </div>

          {monthlyChartData.months.length > 0 && (
            <MonthBars
              months={monthlyChartData.months}
              currentMonthKey={hero.currentMonthKey}
              maxHeightClass="h-12"
              barWidthClass="w-3"
              gapClass="gap-1"
              showLabels={false}
            />
          )}
        </div>
      </div>

      {/* Savings & verification — single neutral line */}
      <div className="rounded-surface border border-border/60 bg-bg/40 px-4 py-3 text-xs text-fg-secondary">
        <span>{S.cost.cacheSavings} </span>
        <span className="font-mono tabular-nums text-fg">
          {formatCurrency(costData.efficiency.estimated_cached_cost_usd_saved)}
        </span>
        <span className="mx-1.5 text-fg-muted">·</span>
        <span>{S.cost.phaseCalls} </span>
        <span className="font-mono tabular-nums text-fg">{totalPhaseCalls}</span>
        <span>{L.callsSuffix}</span>
        <span className="mx-1.5 text-fg-muted">·</span>
        <span>{L.reviewQueueWaiting} </span>
        <span className="font-mono tabular-nums text-fg">
          {costData.efficiency.review_required_tables}
        </span>
        <span>{L.itemsSuffix}</span>
      </div>

      {/* Accordions — collapsed by default, state does not persist */}
      <div className="space-y-3">
        {costData.by_model && costData.by_model.length > 0 && (
          <Accordion
            icon={<Cpu className="w-3.5 h-3.5 text-accent" />}
            title={S.cost.modelBreakdown}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-2xs text-fg-muted uppercase tracking-wider border-b border-border">
                    <th className="text-left py-2 pr-2 font-medium">{S.cost.modelName}</th>
                    <th className="text-right py-2 px-2 font-medium">{S.cost.calls}</th>
                    <th className="text-right py-2 px-2 font-medium">{S.cost.tokensIn}</th>
                    <th className="text-right py-2 px-2 font-medium">{S.cost.tokensOut}</th>
                    <th className="text-right py-2 pl-2 font-medium">{S.cost.cost}</th>
                  </tr>
                </thead>
                <tbody>
                  {costData.by_model.map((m) => (
                    <tr key={m.model} className="border-b border-border last:border-0">
                      <td className="py-2 pr-2 text-fg-secondary">{shortModelName(m.model)}</td>
                      <td className="py-2 px-2 text-right text-fg-muted font-mono tabular-nums">{m.calls}</td>
                      <td className="py-2 px-2 text-right text-fg-muted font-mono tabular-nums">{formatTokens(m.tokens_in)}</td>
                      <td className="py-2 px-2 text-right text-fg-muted font-mono tabular-nums">{formatTokens(m.tokens_out)}</td>
                      <td className="py-2 pl-2 text-right text-fg font-mono tabular-nums font-semibold">{formatCurrency(m.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t border-border">
                    <td className="py-2 pr-2 text-fg-secondary font-semibold">Total</td>
                    <td className="py-2 px-2 text-right text-fg-secondary font-mono tabular-nums font-semibold">
                      {costData.by_model.reduce((s, m) => s + m.calls, 0)}
                    </td>
                    <td className="py-2 px-2 text-right text-fg-secondary font-mono tabular-nums font-semibold">
                      {formatTokens(costData.totals.total_tokens_in)}
                    </td>
                    <td className="py-2 px-2 text-right text-fg-secondary font-mono tabular-nums font-semibold">
                      {formatTokens(costData.totals.total_tokens_out)}
                    </td>
                    <td className="py-2 pl-2 text-right text-accent font-mono tabular-nums font-semibold">
                      {formatCurrency(costData.totals.total_cost_usd)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </Accordion>
        )}

        {costData.per_paper_costs.length > 0 && (
          <Accordion
            icon={<FileText className="w-3.5 h-3.5 text-accent" />}
            title={S.cost.perPaperCost}
          >
            <div className="space-y-2">
              {costData.per_paper_costs.slice(0, 10).map((paper) => (
                <div
                  key={paper.paper_id}
                  className="border-b border-border last:border-0 pb-2 last:pb-0"
                >
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-fg-secondary truncate flex-1 mr-2">
                      {paper.title}
                    </span>
                    <span className="text-fg font-mono tabular-nums font-semibold">
                      {formatCurrency(paper.total_usd)}
                    </span>
                  </div>
                  <div className="flex gap-2 flex-wrap">
                    {Object.entries(paper.phases).map(([phase, cost]) => (
                      <span
                        key={phase}
                        className="text-2xs text-fg-secondary bg-surface-hover px-1.5 py-0.5 rounded"
                      >
                        {phase}: {formatCurrency(cost)}
                      </span>
                    ))}
                    <span className="text-2xs text-fg-secondary bg-surface-hover px-1.5 py-0.5 rounded">
                      {formatTokens(paper.tokens_in + paper.tokens_out)} tokens
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </Accordion>
        )}

        {monthlyChartData.months.length > 0 && (
          <Accordion
            icon={<BarChart3 className="w-3.5 h-3.5 text-accent" />}
            title={S.cost.monthlyTrend}
          >
            <MonthBars
              months={monthlyChartData.months}
              currentMonthKey={hero.currentMonthKey}
              maxHeightClass="h-32"
              barWidthClass="flex-1"
              gapClass="gap-2"
              showLabels
            />
          </Accordion>
        )}
      </div>
    </div>
  );
}
