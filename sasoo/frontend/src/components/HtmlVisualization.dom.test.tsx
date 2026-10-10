// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { VisualizationItem } from '@/lib/api';
import { HTML_CHECK_TIMEOUT_MS, HtmlVisualization, htmlVisualizationDocument, readHtmlCheck } from './HtmlVisualization';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.innerHTML = '';
  vi.useRealTimers();
});

const item = {
  id: 1, title: '관계', tool: 'html', diagram_type: 'interactive', description: '', category: '',
  mermaid_code: null, image_url: null, image_path: null, status: 'completed', error_message: null, block: null,
  html_code: '<input type="range"><output>2</output><script>console.assert(true)</script>',
} as VisualizationItem;

function render(onCheck = vi.fn()) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root!.render(<HtmlVisualization item={item} onCheck={onCheck} />));
  const frame = container.querySelector('iframe')!;
  const nonce = /const N=("[^"]+")/.exec(frame.getAttribute('srcdoc')!)![1];
  return { container, frame, nonce: JSON.parse(nonce) as string, onCheck };
}

function post(source: Window | null, data: unknown) {
  act(() => window.dispatchEvent(new MessageEvent('message', { source, data })));
}

it('accepts only its own frame, nonce and status values', () => {
  const frame = document.createElement('iframe');
  document.body.appendChild(frame);
  const ok = { type: 'sasoo-html-check', nonce: 'n', status: 'failed', issues: ['x'.repeat(300), 3], probed: 2 };
  const event = (source: Window | null, data: unknown) => new MessageEvent('message', { source, data });
  expect(readHtmlCheck(event(frame.contentWindow, ok), frame.contentWindow, 'n'))
    .toEqual({ status: 'failed', issues: ['x'.repeat(200)], probed: 2 });
  expect(readHtmlCheck(event(window, ok), frame.contentWindow, 'n')).toBeNull();
  expect(readHtmlCheck(event(frame.contentWindow, { ...ok, nonce: 'other' }), frame.contentWindow, 'n')).toBeNull();
  expect(readHtmlCheck(event(frame.contentWindow, { ...ok, status: 'verified' }), frame.contentWindow, 'n')).toBeNull();
  expect(readHtmlCheck(event(frame.contentWindow, 'passed'), frame.contentWindow, 'n')).toBeNull();
});

it('runs the check script first and hides the nonce from the generated code', () => {
  const doc = new DOMParser().parseFromString(htmlVisualizationDocument('<p>code</p>', 'NONCE-1'), 'text/html');
  const script = doc.head.querySelector('script')!.textContent!;
  expect(script).toContain('"NONCE-1"');
  expect(script).toContain('document.currentScript.remove()');
  expect(doc.body.innerHTML).toBe('<p>code</p>');
});

it('shows execution status without claiming a check against the paper', () => {
  const { container, frame, nonce, onCheck } = render();
  expect(container.textContent).toContain('실행을 점검하고 있어요');

  post(window, { type: 'sasoo-html-check', nonce, status: 'passed', issues: [], probed: 1 });
  expect(container.textContent).toContain('실행을 점검하고 있어요');

  post(frame.contentWindow, { type: 'sasoo-html-check', nonce, status: 'passed', issues: [], probed: 1 });
  expect(container.textContent).toContain('입력 1개를 범위 끝까지 움직여도 오류 없이');
  expect(container.textContent).toContain('수치는 원문 기준으로 검산하지 않았어요');

  post(frame.contentWindow, { type: 'sasoo-html-check', nonce, status: 'failed', issues: ['assertion failed: y=2x'], probed: 1 });
  expect(container.textContent).toContain('실행 점검에서 오류가 나왔어요');
  expect(container.textContent).toContain('assertion failed: y=2x');
  expect(onCheck).toHaveBeenLastCalledWith({ status: 'failed', issues: ['assertion failed: y=2x'], probed: 1 });
});

it('stops a frame that never answers and offers a rerun', () => {
  vi.useFakeTimers();
  const { container, onCheck } = render();
  act(() => vi.advanceTimersByTime(HTML_CHECK_TIMEOUT_MS + 1));
  expect(container.querySelector('iframe')).toBeNull();
  expect(container.textContent).toContain('응답이 없어 실행을 멈췄어요');
  expect(onCheck).toHaveBeenCalledWith({ status: 'timeout', issues: [], probed: 0 });
  act(() => (container.querySelector('button') as HTMLButtonElement).click());
  expect(container.querySelector('iframe')).not.toBeNull();
});
