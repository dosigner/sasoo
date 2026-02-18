import { useState, useEffect, useMemo } from 'react';
import {
  DollarSign,
  TrendingUp,
  BarChart3,
  FileText,
  Cpu,
  Zap,
} from 'lucide-react';
import { getCostSummary, type CostSummary } from '@/lib/api';
import { S } from '@/lib/strings';

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
      return { months: [], maxCost: 0 };

    const months = costData.monthly_costs;
    const maxCost = Math.max(...months.map((m) => m.total_usd), 0.01);

    return { months, maxCost };
  }, [costData]);

  if (loading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="grid grid-cols-3 gap-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="card">
              <div className="h-3 bg-surface-700 rounded w-20 mb-2" />
              <div className="h-6 bg-surface-700 rounded w-16" />
            </div>
          ))}
        </div>
        <div className="card h-40" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="card flex flex-col items-center justify-center py-8 text-center">
        <DollarSign className="w-8 h-8 text-surface-600 mb-2" />
        <p className="text-sm text-surface-400">{error}</p>
      </div>
    );
  }

  if (!costData) return null;

  const hasData = costData.totals.total_cost_usd > 0 || costData.totals.total_tokens_in > 0;

  if (!hasData) {
    return (
      <div className="card flex flex-col items-center justify-center py-10 text-center">
        <BarChart3 className="w-8 h-8 text-surface-600 mb-3" />
        <p className="text-sm text-surface-300 font-medium">{S.cost.noData}</p>
        <p className="text-2xs text-surface-500 mt-1 max-w-xs">{S.cost.noDataDesc}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3">
        {/* This month cost */}
        <div className="card">
          <div className="flex items-center gap-1.5 mb-2">
            <DollarSign className="w-3.5 h-3.5 text-primary-400" />
            <span className="text-2xs text-surface-400 uppercase tracking-wider">
              {S.cost.thisMonth}
            </span>
          </div>
          <div className="text-lg font-bold text-surface-100 font-mono tabular-nums">
            {formatCurrency(costData.current_month.cost_usd)}
          </div>
          <div className="text-2xs text-surface-500 mt-1">
            {S.cost.paperCount(costData.current_month.papers_analyzed)}
          </div>
        </div>

        {/* Total tokens */}
        <div className="card">
          <div className="flex items-center gap-1.5 mb-2">
            <Zap className="w-3.5 h-3.5 text-amber-400" />
            <span className="text-2xs text-surface-400 uppercase tracking-wider">
              {S.cost.totalTokens}
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <div className="text-lg font-bold text-surface-100 font-mono tabular-nums">
              {formatTokens(costData.totals.total_tokens_in + costData.totals.total_tokens_out)}
            </div>
          </div>
          <div className="flex gap-2 mt-1 text-2xs text-surface-500">
            <span>{S.cost.tokensIn} {formatTokens(costData.totals.total_tokens_in)}</span>
            <span className="text-surface-700">|</span>
            <span>{S.cost.tokensOut} {formatTokens(costData.totals.total_tokens_out)}</span>
          </div>
        </div>

        {/* Average per paper */}
        <div className="card">
          <div className="flex items-center gap-1.5 mb-2">
            <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-2xs text-surface-400 uppercase tracking-wider">
              {S.cost.avgPerPaper}
            </span>
          </div>
          <div className="text-lg font-bold text-surface-100 font-mono tabular-nums">
            {formatCurrency(costData.totals.avg_cost_per_paper)}
          </div>
          <div className="text-2xs text-surface-500 mt-1">
            {S.cost.totalPapers(costData.totals.total_papers)}
          </div>
        </div>
      </div>

      {/* Model breakdown */}
      {costData.by_model && costData.by_model.length > 0 && (
        <div className="card">
          <h4 className="text-xs font-semibold text-surface-300 mb-3 flex items-center gap-2">
            <Cpu className="w-3.5 h-3.5 text-primary-400" />
            {S.cost.modelBreakdown}
          </h4>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-2xs text-surface-500 uppercase tracking-wider border-b border-surface-700">
                  <th className="text-left py-2 pr-2 font-medium">{S.cost.modelName}</th>
                  <th className="text-right py-2 px-2 font-medium">{S.cost.calls}</th>
                  <th className="text-right py-2 px-2 font-medium">{S.cost.tokensIn}</th>
                  <th className="text-right py-2 px-2 font-medium">{S.cost.tokensOut}</th>
                  <th className="text-right py-2 pl-2 font-medium">{S.cost.cost}</th>
                </tr>
              </thead>
              <tbody>
                {costData.by_model.map((m) => (
                  <tr key={m.model} className="border-b border-surface-800 last:border-0">
                    <td className="py-2 pr-2 text-surface-300">{shortModelName(m.model)}</td>
                    <td className="py-2 px-2 text-right text-surface-400 font-mono tabular-nums">{m.calls}</td>
                    <td className="py-2 px-2 text-right text-surface-400 font-mono tabular-nums">{formatTokens(m.tokens_in)}</td>
                    <td className="py-2 px-2 text-right text-surface-400 font-mono tabular-nums">{formatTokens(m.tokens_out)}</td>
                    <td className="py-2 pl-2 text-right text-surface-100 font-mono tabular-nums font-semibold">{formatCurrency(m.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-surface-600">
                  <td className="py-2 pr-2 text-surface-300 font-semibold">Total</td>
                  <td className="py-2 px-2 text-right text-surface-300 font-mono tabular-nums font-semibold">
                    {costData.by_model.reduce((s, m) => s + m.calls, 0)}
                  </td>
                  <td className="py-2 px-2 text-right text-surface-300 font-mono tabular-nums font-semibold">
                    {formatTokens(costData.totals.total_tokens_in)}
                  </td>
                  <td className="py-2 px-2 text-right text-surface-300 font-mono tabular-nums font-semibold">
                    {formatTokens(costData.totals.total_tokens_out)}
                  </td>
                  <td className="py-2 pl-2 text-right text-primary-400 font-mono tabular-nums font-semibold">
                    {formatCurrency(costData.totals.total_cost_usd)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}

      {/* Monthly cost trend chart */}
      {monthlyChartData.months.length > 0 && (
        <div className="card">
          <h4 className="text-xs font-semibold text-surface-300 mb-3 flex items-center gap-2">
            <BarChart3 className="w-3.5 h-3.5 text-primary-400" />
            {S.cost.monthlyTrend}
          </h4>
          <div className="flex items-end gap-2 h-32">
            {monthlyChartData.months.map((month) => (
              <div
                key={month.month}
                className="flex-1 group relative flex flex-col items-center"
              >
                {/* Bar */}
                <div className="w-full flex flex-col-reverse items-stretch flex-1">
                  <div
                    className="w-full bg-primary-500 hover:bg-primary-400 transition-colors rounded-t"
                    style={{
                      height: `${getBarHeight(month.total_usd, monthlyChartData.maxCost)}%`,
                    }}
                  />
                </div>
                {/* Month label */}
                <div className="text-2xs text-surface-500 mt-1">
                  {S.cost.monthLabel(month.month.slice(5))}
                </div>
                {/* Tooltip */}
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block z-10">
                  <div className="bg-surface-900 border border-surface-700 rounded px-2 py-1 shadow-lg whitespace-nowrap">
                    <div className="text-2xs text-surface-300 font-mono">
                      {formatCurrency(month.total_usd)}
                    </div>
                    <div className="text-2xs text-surface-500">
                      {S.cost.paperCount(month.papers_analyzed)}
                    </div>
                    <div className="text-2xs text-surface-500">
                      {formatTokens(month.tokens_in + month.tokens_out)} tokens
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Per-paper costs table */}
      {costData.per_paper_costs.length > 0 && (
        <div className="card">
          <h4 className="text-xs font-semibold text-surface-300 mb-3 flex items-center gap-2">
            <FileText className="w-3.5 h-3.5 text-primary-400" />
            {S.cost.perPaperCost}
          </h4>
          <div className="space-y-2">
            {costData.per_paper_costs.slice(0, 10).map((paper) => (
              <div
                key={paper.paper_id}
                className="border-b border-surface-700 last:border-0 pb-2 last:pb-0"
              >
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-surface-300 truncate flex-1 mr-2">
                    {paper.title}
                  </span>
                  <span className="text-surface-100 font-mono tabular-nums font-semibold">
                    {formatCurrency(paper.total_usd)}
                  </span>
                </div>
                <div className="flex gap-2 flex-wrap">
                  {Object.entries(paper.phases).map(([phase, cost]) => (
                    <span
                      key={phase}
                      className="text-2xs text-surface-500 bg-surface-800 px-1.5 py-0.5 rounded"
                    >
                      {phase}: {formatCurrency(cost)}
                    </span>
                  ))}
                  <span className="text-2xs text-surface-600 bg-surface-800/50 px-1.5 py-0.5 rounded">
                    {formatTokens(paper.tokens_in + paper.tokens_out)} tokens
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
