// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { VisualizationItem, VisualizationPlan } from '@/lib/api';

const api = vi.hoisted(() => ({
  regenerateVisualization: vi.fn(),
  repairMermaid: vi.fn(),
}));
vi.mock('@/lib/api', async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

const { useVisualizationActions } = await import('./VisualizationGallery');

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount());
  root = null;
  vi.clearAllMocks();
});

const item = (title: string): VisualizationItem => ({
  id: 1, title, tool: 'html', diagram_type: 'interactive', description: '', category: '',
  mermaid_code: null, image_url: null, image_path: null, html_code: title, status: 'completed',
  error_message: null, block: null,
});
const plan = (runId: number, title: string): VisualizationPlan => ({
  paper_id: 7, items: [item(title)], total_count: 1, model_used: 'm', planned_at: null, run_id: runId,
});

let actions: ReturnType<typeof useVisualizationActions>;
function Probe({ visualizations }: { visualizations: VisualizationPlan }) {
  actions = useVisualizationActions(visualizations);
  const shown = visualizations.items.map((it) => actions.itemOverrides[it.id] ?? it);
  return <p data-title>{shown[0].title}</p>;
}

function render(p: VisualizationPlan) {
  const container = document.createElement('div');
  root ??= createRoot(container);
  act(() => root!.render(<Probe visualizations={p} />));
  return container;
}

it('shows the new run after regenerate then reanalysis of the same paper', async () => {
  api.regenerateVisualization.mockResolvedValue(item('regenerated old plan'));
  const container = render(plan(10, 'old plan'));

  await act(() => actions.handleRegenerate(7, 1));
  expect(container.textContent).toBe('regenerated old plan');
  expect(api.regenerateVisualization).toHaveBeenCalledWith(7, 1, 10);

  render(plan(11, 'new backend plan'));
  expect(container.textContent).toBe('new backend plan');
});

it('drops a regeneration that finishes after a new run arrived', async () => {
  let finish: (value: VisualizationItem) => void = () => {};
  api.regenerateVisualization.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
  const container = render(plan(10, 'old plan'));

  let pending: Promise<void> = Promise.resolve();
  act(() => { pending = actions.handleRegenerate(7, 1); });
  expect(actions.regeneratingIds[1]).toBe(true);
  render(plan(11, 'new backend plan'));
  expect(actions.regeneratingIds[1]).toBeFalsy();
  await act(async () => { finish(item('late old result')); await pending; });

  expect(container.textContent).toBe('new backend plan');
  expect(actions.regenerateErrors[1]).toBeFalsy();
});
