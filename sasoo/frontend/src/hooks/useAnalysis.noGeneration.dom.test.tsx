// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { useAnalysis } from './useAnalysis';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount());
  root = null;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it.each(['empty', 'failed'])('does not send generation requests when visualizations are %s', async (state) => {
  const requests: Array<{ url: string; method: string }> = [];
  const fetchMock = vi.fn(async (url: string | URL | Request, options?: RequestInit) => {
    const path = String(url);
    requests.push({ url: path, method: (options?.method ?? 'GET').toUpperCase() });
    const payload: Record<string, unknown> = {
      '/api/analysis/1/status': { paper_id: 1, overall_status: 'completed', phases: [{ phase: 'deep_dive', status: 'completed', completed_at: '2026-01-01' }] },
      '/api/analysis/1/results': { paper_id: 1, deep_dive: { detailed_analysis: 'saved summary' } },
      '/api/analysis/1/figures': { figures: [], visual_state: 'ready' },
      '/api/analysis/1/tables': { tables: [], visual_state: 'ready' },
      '/api/analysis/1/synthesis': null,
      '/api/analysis/1/visualizations': { items: [] },
    };
    if (!(path in payload)) throw new Error(`Unexpected request: ${path}`);
    const failed = path.endsWith('/visualizations') && state === 'failed';
    return { ok: !failed, status: failed ? 503 : 200, json: async () => failed ? { detail: 'offline' } : payload[path] };
  });
  vi.stubGlobal('fetch', fetchMock);
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  let summary = '';
  function Probe() {
    const analysis = useAnalysis('1');
    summary = String(analysis.results?.deep_dive?.detailed_analysis ?? '');
    return null;
  }
  root = createRoot(document.createElement('div'));
  await act(async () => { root?.render(<Probe />); });
  await vi.waitFor(() => {
    expect(requests.some(({ url }) => url.endsWith('/visualizations'))).toBe(true);
    expect(summary).toBe('saved summary');
  });
  expect(requests.filter(({ url, method }) => url.endsWith('/mermaid') && method === 'GET')).toEqual([]);
  expect(requests.filter(({ url, method }) => url.endsWith('/run') && method === 'POST')).toEqual([]);
});
