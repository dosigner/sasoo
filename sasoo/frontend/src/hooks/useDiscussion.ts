import { useCallback, useEffect, useRef, useState } from 'react';
import {
  chatWithAgent,
  deleteDiscussion,
  getDiscussion,
  resetDiscussion,
  type DiscussionContext,
  type DiscussionResetReason,
  type DiscussionRow,
} from '@/lib/api';
import { createTokenBuffer } from '@/lib/tokenBuffer';

// 토의 한 줄. 서버 행(discussion_messages)과 아직 저장 전인 대기 질문을 같은 모양으로 둔다.
// user: pending(대기) → complete, sasoo: streaming → complete | interrupted, reset: complete.
export interface DiscussionItem {
  id: string;
  kind: DiscussionRow['kind'];
  content: string;
  status: 'pending' | 'streaming' | 'complete' | 'interrupted';
  error?: string;
  resetReason?: DiscussionResetReason;
  createdAt?: string;
  costUsd?: number;
}

let itemSeq = 0;
const nextItemId = () => `local-${(itemSeq += 1)}`;

export function itemFromRow(row: DiscussionRow): DiscussionItem {
  return {
    id: `db-${row.id}`,
    kind: row.kind,
    content: row.content,
    status: row.status,
    resetReason: row.reset_reason ?? undefined,
    createdAt: row.created_at,
    costUsd: row.cost_usd ?? undefined,
  };
}

export function lastResetIndex(items: DiscussionItem[]): number {
  return items.map((item) => item.kind).lastIndexOf('reset');
}

/** 마지막 맥락 초기화 앞의 대화 수. 접힌 "이전 맥락의 대화 n개"의 n이다. */
export function hiddenBeforeReset(items: DiscussionItem[]): number {
  return items.slice(0, Math.max(lastResetIndex(items), 0)).filter((item) => item.kind !== 'reset').length;
}

/** 사수에게 맥락으로 가는 대화가 있는지. 없으면 "새 맥락"이 의미가 없다. */
export function hasActiveContext(items: DiscussionItem[]): boolean {
  return items
    .slice(lastResetIndex(items) + 1)
    .some((item) => item.kind === 'user' || (item.kind === 'sasoo' && item.status === 'complete'));
}

type LoadState = 'loading' | 'ready' | 'error';

export function useDiscussion(paperId: string, open: boolean) {
  const [items, setItems] = useState<DiscussionItem[]>([]);
  const [context, setContext] = useState<DiscussionContext | null>(null);
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [error, setError] = useState<string | null>(null);
  // Aborts the turn currently on the wire; queued turns have not started yet.
  const abortRef = useRef<AbortController | null>(null);
  const runningRef = useRef(false);
  // 불러오기 도중 보내기, 초기화, 삭제, 논문 전환이 일어나면 늦게 온 기록을 버린다.
  const loadSeqRef = useRef(0);

  const busy = items.some((item) => item.status === 'pending' || item.status === 'streaming');
  const busyRef = useRef(busy);
  busyRef.current = busy;

  useEffect(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    runningRef.current = false;
    loadSeqRef.current += 1;
    setItems([]);
    setContext(null);
    setLoadState('loading');
    setError(null);
  }, [paperId]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const refresh = useCallback(async () => {
    if (busyRef.current) return;
    const seq = (loadSeqRef.current += 1);
    try {
      const data = await getDiscussion(paperId);
      if (seq !== loadSeqRef.current) return;
      setItems(data.messages.map(itemFromRow));
      setContext(data.context);
      setLoadState('ready');
      setError(null);
    } catch (err) {
      if (seq !== loadSeqRef.current) return;
      setLoadState('error');
      setError(err instanceof Error ? err.message : '토의 기록을 불러오지 못했어요.');
    }
  }, [paperId]);

  // 카드를 열 때마다 기록을 다시 읽는다. 재분석으로 생긴 맥락 초기화도 이때 보인다.
  useEffect(() => {
    if (open) void refresh();
  }, [open, refresh]);

  // Runs one queued question to completion. Turns are serialized so each one
  // sees the previous answer, which the backend now reads from the saved discussion.
  const runTurn = useCallback(async (pending: DiscussionItem) => {
    runningRef.current = true;
    const answerId = nextItemId();
    const controller = new AbortController();
    abortRef.current = controller;

    // 답은 질문 바로 뒤에 둔다. 뒤에 대기 중인 질문이 있어도 저장 순서(질문, 답)와 같다.
    setItems((prev) => {
      const at = prev.findIndex((item) => item.id === pending.id);
      const next = prev.map((item) => (item.id === pending.id ? { ...item, status: 'complete' as const } : item));
      next.splice(at + 1, 0, { id: answerId, kind: 'sasoo', content: '', status: 'streaming' });
      return next;
    });

    // Tokens are batched so each SSE token doesn't re-render the whole
    // message list; the buffer is drained before any status transition so a
    // bubble never turns 'complete' or 'interrupted' with text still in flight.
    const tokenBuffer = createTokenBuffer((chunk) => {
      setItems((prev) =>
        prev.map((item) => (item.id === answerId ? { ...item, content: item.content + chunk } : item)),
      );
    });
    const setAnswer = (patch: Partial<DiscussionItem>) =>
      setItems((prev) => prev.map((item) => (item.id === answerId ? { ...item, ...patch } : item)));

    try {
      await chatWithAgent(
        paperId,
        pending.content,
        [],
        (token) => tokenBuffer.push(token),
        (meta) => {
          tokenBuffer.end();
          setAnswer({ status: 'complete', costUsd: meta.cost_usd });
          const tokens = meta.context_tokens;
          if (tokens != null) setContext((prev) => (prev ? { ...prev, context_tokens: tokens } : prev));
        },
        controller.signal,
        {
          onMeta: ({ reset }) => {
            if (!reset) return;
            setItems((prev) => {
              const at = prev.findIndex((item) => item.id === pending.id);
              const next = [...prev];
              next.splice(at, 0, itemFromRow(reset));
              return next;
            });
            setContext((prev) => (prev ? { ...prev, context_tokens: null } : prev));
          },
        },
      );
    } catch (err) {
      tokenBuffer.end();
      // 중지도 서버에는 받은 데까지 "중단됨"으로 남는다. 화면도 같게 보인다.
      const stopped = controller.signal.aborted;
      setAnswer({
        status: 'interrupted',
        error: stopped ? undefined : err instanceof Error ? err.message : '답변을 받지 못했어요.',
      });
    } finally {
      tokenBuffer.end();
      // A stream that ends without a `done` frame would otherwise stay
      // 'streaming' forever and wedge the queue.
      setItems((prev) =>
        prev.map((item) =>
          item.id === answerId && item.status === 'streaming'
            ? { ...item, status: 'interrupted' as const, error: '응답이 중간에 끊겼어요.' }
            : item,
        ),
      );
      if (abortRef.current === controller) abortRef.current = null;
      runningRef.current = false;
    }
  }, [paperId]);

  // Drains the queue: picks up the next pending question whenever one is idle.
  useEffect(() => {
    if (runningRef.current) return;
    const pending = items.find((item) => item.kind === 'user' && item.status === 'pending');
    if (pending) void runTurn(pending);
  }, [items, runTurn]);

  const send = useCallback((text: string) => {
    loadSeqRef.current += 1;
    setItems((prev) => [...prev, { id: nextItemId(), kind: 'user', content: text, status: 'pending' }]);
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const reset = useCallback(async () => {
    loadSeqRef.current += 1;
    try {
      const row = await resetDiscussion(paperId);
      setItems((prev) => [...prev, itemFromRow(row)]);
      setContext((prev) => (prev ? { ...prev, context_tokens: null } : prev));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '맥락을 새로 시작하지 못했어요.');
    }
  }, [paperId]);

  const remove = useCallback(async () => {
    loadSeqRef.current += 1;
    try {
      await deleteDiscussion(paperId);
      setItems([]);
      setContext((prev) => (prev ? { ...prev, context_tokens: null } : prev));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '토의를 삭제하지 못했어요.');
    }
  }, [paperId]);

  return { items, context, loadState, error, busy, refresh, send, stop, reset, remove };
}
