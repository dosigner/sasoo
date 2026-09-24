// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import ReportExport from './ReportExport';
import { getAnalysisReport } from '@/lib/api';
import { downloadReport } from '@/lib/reportExport';

vi.mock('@/lib/api', () => ({ getAnalysisReport: vi.fn() }));
vi.mock('@/lib/reportExport', () => ({ downloadReport: vi.fn() }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root | null = null;

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.innerHTML = '';
  vi.resetAllMocks();
});

function renderExport() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const mounted = createRoot(container);
  root = mounted;
  act(() => mounted.render(<ReportExport paperId="7" />));
  return container;
}

it('reads the report only on explicit export and passes the chosen format to download', async () => {
  const report = { title: 'fixture', markdown: '질문과 답' };
  vi.mocked(getAnalysisReport).mockResolvedValue(report);
  const container = renderExport();
  expect(getAnalysisReport).not.toHaveBeenCalled();
  const select = container.querySelector('select');
  if (!select) throw new Error('Missing format control');
  act(() => {
    select.value = 'html';
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await act(async () => container.querySelector('button')?.click());
  expect(getAnalysisReport).toHaveBeenCalledExactlyOnceWith('7');
  expect(downloadReport).toHaveBeenCalledExactlyOnceWith(report, 'html');
  expect(container.querySelector('[role="status"]')?.textContent).toContain('다운로드를 시작했어요');
});

it('reports an export failure without starting a download', async () => {
  vi.mocked(getAnalysisReport).mockRejectedValue(new Error('No saved report'));
  const container = renderExport();
  await act(async () => container.querySelector('button')?.click());
  expect(downloadReport).not.toHaveBeenCalled();
  expect(container.querySelector('[role="status"]')?.textContent).toContain('내보내지 못했어요');
  expect(container.querySelector('button')?.disabled).toBe(false);
});
