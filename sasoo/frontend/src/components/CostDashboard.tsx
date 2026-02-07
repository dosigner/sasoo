import { useState, useEffect, useMemo } from 'react';
import {
  DollarSign,
  TrendingUp,
  BarChart3,
  AlertTriangle,
  FileText,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MonthlyCost {
  month: string;
  total_usd: number;
  papers_analyzed: number;
  by_model: Record<string, number>;
}

interface PerPaperCost {
  paper_id: number;
  title: string;
  total_usd: number;
  phases: Record<string, number>;
}

interface BudgetInfo {
  monthly_limit_usd: number;
  current_month_usd: number;
  remaining_usd: number;
  warning_threshold: number;
}

interface Totals {
  total_papers: number;
  total_cost_usd: number;
  avg_cost_per_paper: number;
}

interface EnhancedCostData {
  monthly_costs: MonthlyCost[];
  per_paper_costs: PerPaperCost[];
  budget: BudgetInfo;
  totals: Totals;
}

interface CostDashboardProps {
  /** Optional refresh trigger */
  refreshKey?: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatCurrency(amount: number): string {
  return `$${amount.toFixed(2)}`;
}

function getBarHeight(value: number, maxValue: number): number {
  if (maxValue === 0) return 0;
  return Math.max(4, Math.round((value / maxValue) * 100));
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CostDashboard({ refreshKey }: CostDashboardProps) {
  const [costData, setCostData] = useState<EnhancedCostData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchCosts() {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch('/api/settings/cost');
        if (!response.ok) {
          throw new Error('Failed to fetch cost data');
        }
        const data = await response.json();
        if (!cancelled) {
          setCostData(data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : 'Failed to load cost data'
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

  // Calculate monthly chart data
  const monthlyChartData = useMemo(() => {
    if (!costData?.monthly_costs || costData.monthly_costs.length === 0)
      return { months: [], maxCost: 0 };

    const months = costData.monthly_costs;
    const maxCost = Math.max(...months.map((m) => m.total_usd), 0.01);

    return { months, maxCost };
  }, [costData]);

  const budgetPercentage = useMemo(() => {
    if (!costData?.budget) return 0;
    return Math.min(
      100,
      (costData.budget.current_month_usd / costData.budget.monthly_limit_usd) *
        100
    );
  }, [costData]);

  const isOverBudget = budgetPercentage >= 80;

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

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3">
        {/* Monthly total */}
        <div className="card">
          <div className="flex items-center gap-1.5 mb-2">
            <DollarSign className="w-3.5 h-3.5 text-primary-400" />
            <span className="text-2xs text-surface-400 uppercase tracking-wider">
              이번 달 비용
            </span>
          </div>
          <div className="text-lg font-bold text-surface-100 font-mono tabular-nums">
            {formatCurrency(costData.budget.current_month_usd)}
          </div>
        </div>

        {/* Average per paper */}
        <div className="card">
          <div className="flex items-center gap-1.5 mb-2">
            <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-2xs text-surface-400 uppercase tracking-wider">
              논문당 평균
            </span>
          </div>
          <div className="text-lg font-bold text-surface-100 font-mono tabular-nums">
            {formatCurrency(costData.totals.avg_cost_per_paper)}
          </div>
          <div className="text-2xs text-surface-500 mt-1">
            총 {costData.totals.total_papers}개 논문 분석
          </div>
        </div>

        {/* Budget */}
        <div className="card">
          <div className="flex items-center gap-1.5 mb-2">
            {isOverBudget ? (
              <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
            ) : (
              <BarChart3 className="w-3.5 h-3.5 text-surface-400" />
            )}
            <span className="text-2xs text-surface-400 uppercase tracking-wider">
              예산 현황
            </span>
          </div>
          <div className="h-2 bg-surface-700 rounded-full overflow-hidden mb-1.5">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${budgetPercentage}%`,
                background:
                  budgetPercentage >= 80
                    ? '#ef4444'
                    : budgetPercentage >= 60
                      ? '#f59e0b'
                      : '#10b981',
              }}
            />
          </div>
          <div className="flex items-center justify-between text-2xs">
            <span className="text-surface-400">
              {formatCurrency(costData.budget.current_month_usd)}
            </span>
            <span className="text-surface-500">
              / {formatCurrency(costData.budget.monthly_limit_usd)}
            </span>
          </div>
        </div>
      </div>

      {/* Monthly cost trend chart */}
      <div className="card">
        <h4 className="text-xs font-semibold text-surface-300 mb-3 flex items-center gap-2">
          <BarChart3 className="w-3.5 h-3.5 text-primary-400" />
          월별 추이 (최근 6개월)
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
                {month.month.slice(5)}월
              </div>
              {/* Tooltip */}
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block z-10">
                <div className="bg-surface-900 border border-surface-700 rounded px-2 py-1 shadow-lg whitespace-nowrap">
                  <div className="text-2xs text-surface-300 font-mono">
                    {formatCurrency(month.total_usd)}
                  </div>
                  <div className="text-2xs text-surface-500">
                    {month.papers_analyzed}개 논문
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Per-paper costs table */}
      {costData.per_paper_costs.length > 0 && (
        <div className="card">
          <h4 className="text-xs font-semibold text-surface-300 mb-3 flex items-center gap-2">
            <FileText className="w-3.5 h-3.5 text-primary-400" />
            논문별 비용 (상위 10개)
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
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
