import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createTokenBuffer } from './tokenBuffer';

describe('createTokenBuffer', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('batches tokens pushed within the interval into one flush', () => {
    const flush = vi.fn();
    const buffer = createTokenBuffer(flush, 40);

    buffer.push('안');
    buffer.push('녕');
    buffer.push('!');
    expect(flush).not.toHaveBeenCalled();

    vi.advanceTimersByTime(40);
    expect(flush).toHaveBeenCalledTimes(1);
    expect(flush).toHaveBeenCalledWith('안녕!');
  });

  it('starts a new batch after each flush', () => {
    const flush = vi.fn();
    const buffer = createTokenBuffer(flush, 40);

    buffer.push('a');
    vi.advanceTimersByTime(40);
    buffer.push('b');
    vi.advanceTimersByTime(40);

    expect(flush.mock.calls).toEqual([['a'], ['b']]);
  });

  it('flushes pending tokens immediately on end', () => {
    const flush = vi.fn();
    const buffer = createTokenBuffer(flush, 40);

    buffer.push('마지막');
    buffer.end();

    expect(flush).toHaveBeenCalledTimes(1);
    expect(flush).toHaveBeenCalledWith('마지막');

    // The cancelled timer must not fire a second, empty flush.
    vi.advanceTimersByTime(1000);
    expect(flush).toHaveBeenCalledTimes(1);
  });

  it('end is idempotent and never flushes empty chunks', () => {
    const flush = vi.fn();
    const buffer = createTokenBuffer(flush, 40);

    buffer.end();
    buffer.end();
    vi.advanceTimersByTime(1000);

    expect(flush).not.toHaveBeenCalled();
  });
});
