/**
 * Delays a "delete" action by a grace window so the caller can offer undo.
 *
 * Library.tsx hides a paper the instant the user confirms delete, then
 * schedules the real API call here instead of firing it immediately. If
 * nothing cancels it, `commit` runs once `delayMs` elapses. A caller can
 * also `flush` it early (e.g. the undo toast closed without being clicked)
 * or `cancel` it (undo was clicked). Everything is keyed by `id`, so
 * multiple deletes can be pending at once with independent timers.
 */
export interface PendingDeleteScheduler {
  /** Schedule a delete. A second call for the same id while one is already
   *  pending is ignored — the request already in flight wins. */
  schedule(id: string, commit: () => void, delayMs: number): void;
  /** Cancel a pending delete. Returns true if one was actually pending. */
  cancel(id: string): boolean;
  /** Run `commit` immediately and clear the timer. No-op if not pending. */
  flush(id: string): void;
  /** Flush every pending delete (e.g. the owning component unmounted). */
  flushAll(): void;
  has(id: string): boolean;
}

export function createPendingDeleteScheduler(): PendingDeleteScheduler {
  const pending = new Map<string, { timer: ReturnType<typeof setTimeout>; commit: () => void }>();

  function cancel(id: string): boolean {
    const entry = pending.get(id);
    if (!entry) return false;
    clearTimeout(entry.timer);
    pending.delete(id);
    return true;
  }

  function flush(id: string): void {
    const entry = pending.get(id);
    if (!entry) return;
    clearTimeout(entry.timer);
    pending.delete(id);
    entry.commit();
  }

  return {
    schedule(id, commit, delayMs) {
      if (pending.has(id)) return;
      const timer = setTimeout(() => {
        pending.delete(id);
        commit();
      }, delayMs);
      pending.set(id, { timer, commit });
    },
    cancel,
    flush,
    flushAll() {
      Array.from(pending.keys()).forEach(flush);
    },
    has: (id) => pending.has(id),
  };
}
