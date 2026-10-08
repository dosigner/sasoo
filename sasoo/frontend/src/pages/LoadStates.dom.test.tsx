// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { S } from '@/lib/strings';
import Home from './Home';
import Library from './Library';
import Profile from './Profile';
import Settings from './Settings';

const mocks = vi.hoisted(() => ({
  getPapers: vi.fn(), getSettings: vi.fn(), usePapers: vi.fn(), refresh: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));
vi.mock('@/lib/api', async (actual) => ({
  ...await actual<typeof import('@/lib/api')>(),
  getPapers: mocks.getPapers, getSettings: mocks.getSettings,
  getCostSummary: vi.fn().mockResolvedValue({ current_month: null }),
}));
vi.mock('@/hooks/usePapers', () => ({ usePapers: mocks.usePapers }));
vi.mock('@/hooks/usePendingDelete', () => ({ usePendingDelete: () => ({ isPending: () => false }) }));
vi.mock('@/components/Toast', () => ({ useToast: () => ({ toast: mocks.toast }) }));
vi.mock('@/components/home/UploadPanel', () => ({ default: () => null }));
vi.mock('@/components/settings/CostDashboard', () => ({ default: () => null }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root | null = null;
let container: HTMLDivElement;
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('localStorage', { getItem: () => null, setItem: vi.fn() });
  mocks.getPapers.mockRejectedValue(new Error('offline'));
  mocks.getSettings.mockRejectedValue(new Error('offline'));
  mocks.usePapers.mockReturnValue({
    papers: [], total: 0, completedTotal: null, page: 1, totalPages: 0,
    loading: false, error: null, filters: {}, availableTags: [],
    setFilters: vi.fn(), setSearch: vi.fn(), refresh: mocks.refresh,
  });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root?.unmount());
  document.body.innerHTML = '';
});
async function render(page: React.ReactNode) {
  await act(async () => root!.render(<MemoryRouter>{page}</MemoryRouter>));
}
it('shows a retry instead of an empty library after a failed list request', async () => {
  mocks.usePapers.mockReturnValue({ ...mocks.usePapers(), error: S.error.loadPapersFailed });
  await render(<Library />);
  expect(container.textContent).not.toContain(S.library.noPapers);
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(S.error.loadPapersFailed);
  const retry = [...container.querySelectorAll('button')].find(b => b.textContent === '다시 시도');
  expect(retry).toBeDefined();
  act(() => retry!.click());
  expect(mocks.refresh).toHaveBeenCalledOnce();
});
it('treats a search with no matches as a filtered result', async () => {
  mocks.usePapers.mockReturnValue({ ...mocks.usePapers(), filters: { search: 'unknown' } });
  await render(<Library />);
  expect(container.textContent).toContain(S.library.noMatch);
  expect(container.textContent).not.toContain(S.library.noPapers);
  expect(container.textContent).toContain(S.library.clearFilters);
});
it('keeps Home fetch failures separate from its empty state and lets users retry', async () => {
  await render(<Home />);
  expect(container.textContent).not.toContain(S.home.recentEmpty);
  expect(container.querySelector('[role="alert"]')).not.toBeNull();
  mocks.getPapers.mockResolvedValue({ papers: [], total: 0 });
  const retry = [...container.querySelectorAll('button')].find(b => b.textContent === '다시 시도');
  await act(async () => retry!.click());
  expect(container.textContent).toContain(S.home.recentEmpty);
});
it.each([['Profile', Profile], ['Settings', Settings]] as const)(
  'keeps %s defaults from becoming editable after its initial load fails', async (_name, Page) => {
    await render(<Page />);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(S.settings.loadFailed);
    expect(container.querySelector('input, textarea')).toBeNull();
  },
);
