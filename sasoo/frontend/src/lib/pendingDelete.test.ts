import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createPendingDeleteScheduler } from './pendingDelete';

describe('createPendingDeleteScheduler', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('cancels a pending delete before it commits (undo)', () => {
    const commit = vi.fn();
    const scheduler = createPendingDeleteScheduler();

    scheduler.schedule('p1', commit, 6000);
    expect(scheduler.cancel('p1')).toBe(true);

    vi.advanceTimersByTime(6000);
    expect(commit).not.toHaveBeenCalled();
    expect(scheduler.has('p1')).toBe(false);
  });

  it('commits once the delay elapses', () => {
    const commit = vi.fn();
    const scheduler = createPendingDeleteScheduler();

    scheduler.schedule('p1', commit, 6000);
    vi.advanceTimersByTime(5999);
    expect(commit).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(commit).toHaveBeenCalledTimes(1);
    expect(scheduler.has('p1')).toBe(false);
  });

  it('flush runs the commit immediately and cancels the timer', () => {
    const commit = vi.fn();
    const scheduler = createPendingDeleteScheduler();

    scheduler.schedule('p1', commit, 6000);
    scheduler.flush('p1');
    expect(commit).toHaveBeenCalledTimes(1);

    // The original timer must not fire a second commit.
    vi.advanceTimersByTime(6000);
    expect(commit).toHaveBeenCalledTimes(1);
  });

  it('ignores a duplicate schedule for the same id while one is pending', () => {
    const firstCommit = vi.fn();
    const secondCommit = vi.fn();
    const scheduler = createPendingDeleteScheduler();

    scheduler.schedule('p1', firstCommit, 6000);
    scheduler.schedule('p1', secondCommit, 6000); // duplicate request, ignored

    vi.advanceTimersByTime(6000);
    expect(firstCommit).toHaveBeenCalledTimes(1);
    expect(secondCommit).not.toHaveBeenCalled();
  });

  it('tracks independent timers per id', () => {
    const commitA = vi.fn();
    const commitB = vi.fn();
    const scheduler = createPendingDeleteScheduler();

    scheduler.schedule('a', commitA, 6000);
    scheduler.schedule('b', commitB, 6000);
    scheduler.cancel('a');

    vi.advanceTimersByTime(6000);
    expect(commitA).not.toHaveBeenCalled();
    expect(commitB).toHaveBeenCalledTimes(1);
  });
});
