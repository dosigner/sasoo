import { afterEach, beforeEach, expect, it, vi } from 'vitest';

// Run effects and rerenders in Node without adding a DOM dependency.
const hooks = vi.hoisted(() => {
  let cells = [], cursor = 0, effects = [], render, value;
  const slot = (init) => {
    const index = cursor++;
    if (!(index in cells)) cells[index] = init();
    return cells[index];
  };
  const changed = (a, b) => !a || a.some((item, i) => !Object.is(item, b[i]));
  return {
    useState(initial) {
      const cell = slot(() => ({ value: initial }));
      return [cell.value, (next) => {
        const updated = typeof next === 'function' ? next(cell.value) : next;
        if (!Object.is(updated, cell.value)) { cell.value = updated; effects.push(() => render()); }
      }];
    },
    useRef(initial) { return slot(() => ({ current: initial })); },
    useCallback(callback, deps) {
      const cell = slot(() => ({}));
      if (changed(cell.deps, deps)) { cell.deps = deps; cell.callback = callback; }
      return cell.callback;
    },
    useEffect(effect, deps) {
      const cell = slot(() => ({}));
      if (changed(cell.deps, deps)) {
        cell.deps = deps;
        effects.push(() => { cell.cleanup?.(); cell.cleanup = effect(); });
      }
    },
    mount(callback) { render = () => { cursor = 0; value = callback(); }; render(); },
    async flush() {
      for (let i = 0; i < 40; i++) {
        const pending = effects; effects = [];
        pending.forEach((effect) => effect());
        await Promise.resolve();
      }
      return value;
    },
    reset() { cells.forEach((cell) => cell.cleanup?.()); cells = []; effects = []; cursor = 0; },
  };
});
vi.mock('react', () => hooks);
vi.mock('@/lib/api', () => ({
  ApiError: class extends Error {},
  getPapers: vi.fn(), getPaper: vi.fn(), deletePaper: vi.fn(), updatePaper: vi.fn(),
  runAnalysis: vi.fn(), getAnalysisStatus: vi.fn(), getAnalysisResults: vi.fn(),
  getFigures: vi.fn(), getTables: vi.fn(), getRecipe: vi.fn(), getMermaid: vi.fn(), getVisualizations: vi.fn(),
}));
import * as api from '@/lib/api';
import { useAnalysis } from './useAnalysis';
import { usePapers } from './usePapers';

const status = (completed = ['screening'], overall = 'running') => ({
  paper_id: 1, overall_status: overall,
  phases: completed.map((phase) => ({ phase, status: 'completed', completed_at: '2026-09-06' })),
});
const list = (total) => ({ papers: [], total, completed_count: 4 });
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};
beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
  api.getAnalysisStatus.mockResolvedValue(status());
  api.getAnalysisResults.mockResolvedValue({ paper_id: 1 });
  api.getFigures.mockResolvedValue({ figures: [], visual_state: 'ready' });
  api.getTables.mockResolvedValue({ tables: [], visual_state: 'ready' });
  api.getVisualizations.mockResolvedValue({ items: [] });
  api.getPapers.mockResolvedValue(list(10));
});
afterEach(() => { hooks.reset(); vi.useRealTimers(); });

it('fetches results once while thirty status polls report unchanged completion', async () => {
  hooks.mount(() => useAnalysis('1'));
  await hooks.flush();
  for (let i = 0; i < 30; i++) { await vi.advanceTimersByTimeAsync(2000); await hooks.flush(); }
  expect(api.getAnalysisStatus).toHaveBeenCalledTimes(31);
  expect(api.getAnalysisResults).toHaveBeenCalledTimes(1);
});
it('fetches one result update when a new phase completes', async () => {
  hooks.mount(() => useAnalysis('1'));
  await hooks.flush();
  api.getAnalysisStatus.mockResolvedValue(status(['screening', 'citation']));
  await vi.advanceTimersByTimeAsync(4000); await hooks.flush();
  expect(api.getAnalysisResults).toHaveBeenCalledTimes(2);
});
it('retries failed results at the next poll', async () => {
  api.getAnalysisResults.mockRejectedValueOnce(new Error('offline'));
  hooks.mount(() => useAnalysis('1'));
  await hooks.flush();
  await vi.advanceTimersByTimeAsync(4000); await hooks.flush();
  expect(api.getAnalysisResults).toHaveBeenCalledTimes(2);
});
it('refetches unchanged completed phases for manual refresh and a new analysis session', async () => {
  hooks.mount(() => useAnalysis('1'));
  const analysis = await hooks.flush();
  await analysis.refresh(); await hooks.flush();
  expect(api.getAnalysisResults).toHaveBeenCalledTimes(2);
  await analysis.startAnalysis(); await hooks.flush();
  expect(api.getAnalysisResults).toHaveBeenCalledTimes(3);
});
it('continues refreshing visualization progress without refetching results', async () => {
  api.getAnalysisStatus.mockResolvedValue(status(['screening', 'deep_dive']));
  hooks.mount(() => useAnalysis('1'));
  await hooks.flush();
  await vi.advanceTimersByTimeAsync(6000); await hooks.flush();
  expect(api.getAnalysisResults).toHaveBeenCalledTimes(1);
  expect(api.getVisualizations).toHaveBeenCalledTimes(4);
});
it('fetches a list only once on mount including the aggregate', async () => {
  hooks.mount(() => usePapers());
  const papers = await hooks.flush();
  expect(api.getPapers).toHaveBeenCalledTimes(1);
  expect(papers.completedTotal).toBe(4);
});
it('keeps the newest list when older search responses arrive last', async () => {
  hooks.mount(() => usePapers());
  let papers = await hooks.flush();
  const older = deferred();
  api.getPapers.mockReturnValueOnce(older.promise).mockResolvedValue(list(20));
  papers.setSearch('old'); await hooks.flush();
  await vi.advanceTimersByTimeAsync(300); papers = await hooks.flush();
  papers.setSearch('new'); await hooks.flush();
  await vi.advanceTimersByTimeAsync(300); await hooks.flush();
  older.resolve(list(99)); papers = await hooks.flush();
  expect(papers.total).toBe(20);
  expect(papers.completedTotal).toBeNull();
});

it('retries a failed final result before stopping polling', async () => {
  api.getAnalysisStatus.mockResolvedValue(status(['screening'], 'completed'));
  api.getAnalysisResults.mockRejectedValueOnce(new Error('offline'));
  hooks.mount(() => useAnalysis('1'));
  await hooks.flush();
  await vi.advanceTimersByTimeAsync(2000); await hooks.flush();
  await vi.advanceTimersByTimeAsync(4000);
  expect(api.getAnalysisResults).toHaveBeenCalledTimes(2);
  expect(api.getAnalysisStatus).toHaveBeenCalledTimes(2);
});
it('ignores an old status response that arrives after a newer poll', async () => {
  hooks.mount(() => useAnalysis('1'));
  await hooks.flush();
  const old = deferred();
  api.getAnalysisStatus.mockReturnValueOnce(old.promise).mockResolvedValue(status(['screening', 'citation']));
  await vi.advanceTimersByTimeAsync(4000); await hooks.flush();
  old.resolve(status());
  const analysis = await hooks.flush();
  expect(analysis.status.phases).toHaveLength(2);
  expect(api.getAnalysisResults).toHaveBeenCalledTimes(2);
});
it('ignores results from a paper that was replaced during an in-flight request', async () => {
  const old = deferred();
  api.getAnalysisResults.mockReturnValueOnce(old.promise).mockResolvedValue({ paper_id: 2 });
  let paper = '1';
  hooks.mount(() => useAnalysis(paper)); await hooks.flush();
  paper = '2';
  hooks.mount(() => useAnalysis(paper)); await hooks.flush();
  old.resolve({ paper_id: 1 });
  const analysis = await hooks.flush();
  expect(analysis.results.paper_id).toBe(2);
});
it('performs a manual refresh requested during a result load', async () => {
  const first = deferred();
  api.getAnalysisResults.mockReturnValueOnce(first.promise);
  hooks.mount(() => useAnalysis('1'));
  const analysis = await hooks.flush();
  const refresh = analysis.refresh();
  first.resolve({ paper_id: 1 });
  await refresh; await hooks.flush();
  expect(api.getAnalysisResults).toHaveBeenCalledTimes(2);
});
it('clears aggregate statistics on a failed list refresh', async () => {
  hooks.mount(() => usePapers());
  const papers = await hooks.flush();
  api.getPapers.mockRejectedValueOnce(new Error('offline'));
  await papers.refresh();
  const updated = await hooks.flush();
  expect(updated.completedTotal).toBeNull();
  expect(updated.error).not.toBeNull();
});
it('does not restart polling when a new analysis immediately completes', async () => {
  hooks.mount(() => useAnalysis('1'));
  const analysis = await hooks.flush();
  api.getAnalysisStatus.mockResolvedValue(status(['screening'], 'completed'));
  await analysis.startAnalysis(); await hooks.flush();
  const requests = api.getAnalysisStatus.mock.calls.length;
  await vi.advanceTimersByTimeAsync(6000);
  expect(api.getAnalysisStatus).toHaveBeenCalledTimes(requests);
});
it('retries a failed manual result refresh on a completed paper', async () => {
  api.getAnalysisStatus.mockResolvedValue(status(['screening'], 'completed'));
  hooks.mount(() => useAnalysis('1'));
  const analysis = await hooks.flush();
  api.getAnalysisResults.mockRejectedValueOnce(new Error('offline'));
  await analysis.refresh(); await hooks.flush();
  await vi.advanceTimersByTimeAsync(4000); await hooks.flush();
  expect(api.getAnalysisResults).toHaveBeenCalledTimes(3);
  expect(api.getAnalysisStatus).toHaveBeenCalledTimes(3);
});
