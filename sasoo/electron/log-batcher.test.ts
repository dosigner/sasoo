import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LogBatcher } from './log-batcher';

describe('LogBatcher', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('batches same-level lines within the interval into one send', () => {
    const send = vi.fn();
    const batcher = new LogBatcher(send, 100);

    batcher.push('info', 'GET /api/papers 200');
    batcher.push('info', 'GET /api/settings 200');
    expect(send).not.toHaveBeenCalled();

    vi.advanceTimersByTime(100);
    expect(send.mock.calls).toEqual([
      ['info', 'GET /api/papers 200\nGET /api/settings 200'],
    ]);
  });

  it('keeps ordering by splitting the batch only where the level changes', () => {
    const send = vi.fn();
    const batcher = new LogBatcher(send, 100);

    batcher.push('info', 'a');
    batcher.push('info', 'b');
    batcher.push('error', 'boom');
    batcher.push('info', 'c');

    vi.advanceTimersByTime(100);
    expect(send.mock.calls).toEqual([
      ['info', 'a\nb'],
      ['error', 'boom'],
      ['info', 'c'],
    ]);
  });

  it('flush sends immediately and the cancelled timer stays silent', () => {
    const send = vi.fn();
    const batcher = new LogBatcher(send, 100);

    batcher.push('error', 'traceback');
    batcher.flush();
    expect(send.mock.calls).toEqual([['error', 'traceback']]);

    vi.advanceTimersByTime(1000);
    expect(send).toHaveBeenCalledTimes(1);
  });

  it('flush with nothing pending sends nothing', () => {
    const send = vi.fn();
    const batcher = new LogBatcher(send, 100);

    batcher.flush();
    batcher.flush();
    vi.advanceTimersByTime(1000);

    expect(send).not.toHaveBeenCalled();
  });
});
