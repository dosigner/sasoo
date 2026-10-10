// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { CostSummary } from '@/lib/api';

const api = vi.hoisted(() => ({ getCostSummary: vi.fn() }));
vi.mock('@/lib/api', async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));
const { default: CostDashboard } = await import('./CostDashboard');

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.innerHTML = '';
});

function summary(unknown: number): CostSummary {
  return {
    monthly_costs: [{ month: '2026-10', total_usd: 0, unknown_cost_count: unknown, papers_analyzed: 1, tokens_in: 0, tokens_out: 0, by_model: {} }],
    per_paper_costs: [{ paper_id: 7, title: '검증 논문', total_usd: 0, unknown_cost_count: unknown, tokens_in: 0, tokens_out: 0, phases: { visualization: 0 } }],
    by_model: [{ model: 'gpt-image-2.5-flare', calls: 1, cost_usd: 0, unknown_cost_count: unknown, tokens_in: 0, tokens_out: 0 }],
    current_month: { month: '2026-10', cost_usd: 0, unknown_cost_count: unknown, tokens_in: 0, tokens_out: 0, papers_analyzed: 1 },
    totals: { total_papers: 1, total_cost_usd: 0, unknown_cost_count: unknown, avg_cost_per_paper: 0, total_tokens_in: 0, total_tokens_out: 0 },
    efficiency: { phase_call_counts: {}, estimated_cached_calls_saved: 0, estimated_cached_cost_usd_saved: 0, uncertain_table_repair_calls: 0, review_required_tables: 0 },
  };
}

async function render(data: CostSummary) {
  api.getCostSummary.mockResolvedValue(data);
  const container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root!.render(<CostDashboard refreshKey={0} />));
  for (const details of container.querySelectorAll('button')) act(() => details.click());
  return container;
}

it('marks a total that leaves out requests with unknown usage instead of a plain $0.00', async () => {
  const container = await render(summary(2));
  expect(container.textContent).toContain('$0.00');
  expect(container.textContent).toContain('사용량을 확인하지 못한 요청 2건은 합계에서 빠졌어요');
  expect(container.textContent).toContain('미확인 2건');
});

it('shows no notice when every request was priced', async () => {
  const container = await render({ ...summary(0), totals: { ...summary(0).totals, total_cost_usd: 0.5 } });
  expect(container.textContent).not.toContain('미확인');
});
