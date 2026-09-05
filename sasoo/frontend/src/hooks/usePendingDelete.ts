import { useCallback, useEffect, useRef, useState } from 'react';
import { createPendingDeleteScheduler } from '@/lib/pendingDelete';

const UNDO_WINDOW_MS = 6000;

/**
 * Delays paper deletion by UNDO_WINDOW_MS so Library.tsx can offer an undo
 * action. The scheduler in lib/pendingDelete.ts owns the actual timer; this
 * hook mirrors "is this id pending" into React state (so the list can hide
 * it) and flushes anything still pending when the owning component leaves.
 */
export function usePendingDelete() {
  const schedulerRef = useRef(createPendingDeleteScheduler());
  const [pendingIds, setPendingIds] = useState<ReadonlySet<string>>(() => new Set());

  const unmark = useCallback((id: string) => {
    setPendingIds((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }, []);

  const schedule = useCallback(
    (id: string, commit: () => Promise<void>) => {
      if (schedulerRef.current.has(id)) return; // 같은 논문에 대한 중복 삭제 요청은 무시
      setPendingIds((prev) => new Set(prev).add(id));
      schedulerRef.current.schedule(
        id,
        () => {
          void commit().finally(() => unmark(id));
        },
        UNDO_WINDOW_MS
      );
    },
    [unmark]
  );

  const cancel = useCallback(
    (id: string) => {
      if (schedulerRef.current.cancel(id)) unmark(id);
    },
    [unmark]
  );

  const flush = useCallback((id: string) => {
    schedulerRef.current.flush(id);
  }, []);

  useEffect(() => {
    const scheduler = schedulerRef.current;
    return () => {
      // 라우트 이동 등 컴포넌트 언마운트까지만 보장한다. 앱 자체가 그대로
      // 종료되면 이 타이머도 함께 사라져 예약된 삭제가 실행되지 못할 수 있다.
      scheduler.flushAll();
    };
  }, []);

  return {
    isPending: (id: string) => pendingIds.has(id),
    schedule,
    cancel,
    flush,
  };
}
