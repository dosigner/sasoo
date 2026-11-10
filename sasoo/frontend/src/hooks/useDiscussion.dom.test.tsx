// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { DiscussionRow } from '@/lib/api';

const api = vi.hoisted(() => ({
  getDiscussion: vi.fn(),
  resetDiscussion: vi.fn(),
  deleteDiscussion: vi.fn(),
  chatWithAgent: vi.fn(),
}));
vi.mock('@/lib/api', () => api);

import { hasActiveContext, hiddenBeforeReset, itemFromRow, useDiscussion } from './useDiscussion';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const row = (id: number, kind: DiscussionRow['kind'], extra: Partial<DiscussionRow> = {}): DiscussionRow => ({
  id, kind, content: kind === 'reset' ? '' : `${kind}-${id}`, status: 'complete',
  reset_reason: kind === 'reset' ? 'manual' : null, cost_usd: null, created_at: '2026-10-09 05:00:00', ...extra,
});

type Hook = ReturnType<typeof useDiscussion>;
let hook: Hook;
let root: ReturnType<typeof createRoot>;
let node: HTMLDivElement;

function Harness({ paperId = "7" }: { paperId?: string }) {
  hook = useDiscussion(paperId, true);
  return null;
}

beforeEach(async () => {
  vi.clearAllMocks();
  api.getDiscussion.mockResolvedValue({
    messages: [row(1, 'user'), row(2, 'sasoo', { cost_usd: 0.002 })],
    context: { budget: 260_000, context_tokens: 12_000, sources: [] },
  });
  node = document.createElement('div');
  document.body.appendChild(node);
  root = createRoot(node);
  await act(async () => root.render(<Harness />));
});

afterEach(() => {
  act(() => root.unmount());
  node.remove();
});

it('loads the saved discussion when the card opens', () => {
  expect(api.getDiscussion).toHaveBeenCalledWith('7');
  expect(hook.loadState).toBe('ready');
  expect(hook.items.map((item) => [item.kind, item.content, item.status])).toEqual([
    ['user', 'user-1', 'complete'], ['sasoo', 'sasoo-2', 'complete'],
  ]);
  expect(hook.context?.context_tokens).toBe(12_000);
});

it('places a reset from meta before the question and saves the answer as complete', async () => {
  api.chatWithAgent.mockImplementation(async (_id, _msg, _history, onToken, onDone, _signal, options) => {
    options.onMeta({ user_message_id: 4, reset: row(3, 'reset', { reset_reason: 'reanalysis' }) });
    onToken('새 ');
    onToken('답');
    onDone({ tokens_in: 9000, tokens_out: 10, cost_usd: 0.001, message_id: 5, context_tokens: 9000 });
  });
  await act(async () => hook.send('재분석 뒤 질문'));

  expect(api.chatWithAgent.mock.calls[0][6]).not.toHaveProperty('persist', false);
  expect(hook.items.map((item) => [item.kind, item.content, item.status, item.resetReason])).toEqual([
    ['user', 'user-1', 'complete', undefined],
    ['sasoo', 'sasoo-2', 'complete', undefined],
    ['reset', '', 'complete', 'reanalysis'],
    ['user', '재분석 뒤 질문', 'complete', undefined],
    ['sasoo', '새 답', 'complete', undefined],
  ]);
  expect(hook.context?.context_tokens).toBe(9000);
  expect(hook.busy).toBe(false);
});

it('marks the answer interrupted when the stream fails midway', async () => {
  api.chatWithAgent.mockImplementation(async (_id, _msg, _history, onToken) => {
    onToken('받은 데까지');
    throw new Error('stream boom');
  });
  await act(async () => hook.send('질문'));

  const answer = hook.items[hook.items.length - 1];
  expect([answer.kind, answer.content, answer.status, answer.error]).toEqual(['sasoo', '받은 데까지', 'interrupted', 'stream boom']);
  expect(hook.busy).toBe(false);
});

it('counts only conversation before the last reset as hidden', () => {
  const items = [row(1, 'user'), row(2, 'sasoo'), row(3, 'reset'), row(4, 'user'), row(5, 'sasoo'), row(6, 'reset')]
    .map(itemFromRow);
  expect(hiddenBeforeReset(items)).toBe(4);
  expect(hasActiveContext(items)).toBe(false);
  expect(hiddenBeforeReset(items.slice(0, 2))).toBe(0);

  const interruptedOnly = [...items, itemFromRow(row(7, 'sasoo', { status: 'interrupted' }))];
  expect(hasActiveContext(interruptedOnly)).toBe(false);
  expect(hasActiveContext([...interruptedOnly, itemFromRow(row(8, 'user'))])).toBe(true);
});

it('carries the selection separately and does not call the model on mount', async () => {
  expect(api.chatWithAgent).not.toHaveBeenCalled();
  const selected = { text: 'Raw selected sentence', page: 2, end_page: 3 };
  await act(async () => hook.send('Explain this', selected));
  expect(api.chatWithAgent.mock.calls[0][6].selection).toEqual(selected);
});

it('ignores late stream metadata and queued questions from the previous paper', async () => {
  let finish!: () => void;
  let lateMeta!: () => void;
  api.chatWithAgent.mockImplementation((_id, _msg, _history, onToken, onDone, _signal, options) => new Promise<void>((resolve) => {
    finish = resolve;
    lateMeta = () => {
      options.onMeta({ reset: row(99, 'reset') });
      onToken('OLD PAPER');
      onDone({ context_tokens: 99999 });
    };
  }));
  await act(async () => hook.send('Old question'));
  await act(async () => hook.send('Old queued question'));
  api.getDiscussion.mockResolvedValue({ messages: [], context: { context_tokens: 10, sources: [], budget: 260000 } });
  await act(async () => root.render(<Harness paperId="8" />));
  await act(async () => { lateMeta(); finish(); });
  expect(hook.items).toEqual([]);
  expect(hook.context?.context_tokens).toBe(10);
  expect(api.chatWithAgent).toHaveBeenCalledOnce();
});

for (const action of ['reset', 'remove'] as const) {
  it(`ignores a late ${action} response after switching papers`, async () => {
    let finish!: (value?: unknown) => void;
    const deferred = new Promise((resolve) => { finish = resolve; });
    (action === 'reset' ? api.resetDiscussion : api.deleteDiscussion).mockReturnValue(deferred);
    let pending!: Promise<void>;
    await act(async () => { pending = hook[action](); });
    api.getDiscussion.mockResolvedValue({ messages: [row(22, 'user', { content: 'NEW PAPER' })], context: { context_tokens: 25 } });
    await act(async () => root.render(<Harness paperId="8" />));
    await act(async () => { finish(action === 'reset' ? row(99, 'reset') : undefined); await pending; });
    expect(hook.items.map((item) => item.content)).toEqual(['NEW PAPER']);
    expect(hook.context?.context_tokens).toBe(25);
  });
}
