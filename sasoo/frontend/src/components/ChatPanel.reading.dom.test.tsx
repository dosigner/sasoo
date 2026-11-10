// @vitest-environment jsdom
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ChatPanel from './ChatPanel';
import { buildChatStarterPrompts } from '@/lib/workbenchSummaries';

const api = vi.hoisted(() => ({
  getDiscussion: vi.fn(), chatWithAgent: vi.fn(), resetDiscussion: vi.fn(), deleteDiscussion: vi.fn(),
}));
vi.mock('@/lib/api', () => api);
vi.mock('@/components/Markdown', () => ({ Markdown: ({ children }: { children: string }) => <p>{children}</p> }));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root;
let container: HTMLDivElement;

function Harness({ ready = true }: { ready?: boolean }) {
  const [draft, setDraft] = useState('');
  return <ChatPanel paperId="7" open ready={ready} readyMessage="PDF 텍스트 준비 중"
    draft={draft} onDraftChange={setDraft} onToggleOpen={() => {}}
    starters={buildChatStarterPrompts({ results: null, figures: [], recipe: null })} />;
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getDiscussion.mockResolvedValue({ messages: [], context: { budget: 260000, context_tokens: null, sources: [] } });
  api.chatWithAgent.mockImplementation(async (_id, _text, _history, onToken, onDone) => {
    onToken('논문의 연구 목적을 설명합니다.');
    onDone({ tokens_in: 50, tokens_out: 10, cost_usd: 0.001 });
  });
  vi.stubGlobal('requestAnimationFrame', () => 1);
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

it('offers reading questions and sends only after the user submits', async () => {
  await act(async () => root.render(<Harness />));
  expect(container.textContent).toContain('분석 전에도 질문할 수 있어요');
  const starter = [...container.querySelectorAll('button')].find((button) => button.textContent?.includes('무슨 문제를'))!;
  await act(async () => starter.click());
  expect(container.querySelector('textarea')?.value).toBe('무슨 문제를 해결하는 논문이야?');
  expect(api.chatWithAgent).not.toHaveBeenCalled();
  await act(async () => container.querySelector('textarea')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
  expect(api.chatWithAgent).toHaveBeenCalledOnce();
  expect(api.chatWithAgent.mock.calls[0][1]).toBe('무슨 문제를 해결하는 논문이야?');
  expect(container.textContent).toContain('논문의 연구 목적을 설명합니다.');
});

it('waits for PDF text rather than allowing an ungrounded first message', async () => {
  await act(async () => root.render(<Harness ready={false} />));
  expect(container.textContent).toContain('PDF 텍스트 준비 중');
  expect(container.querySelector('textarea')).toBeNull();
  expect(api.chatWithAgent).not.toHaveBeenCalled();
});
