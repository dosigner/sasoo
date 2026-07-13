/**
 * Batches SSE tokens so the chat UI re-renders per interval, not per token.
 *
 * Streaming answers arrive as dozens of tokens per second; pushing each one
 * straight into React state re-renders the whole message list every time.
 * Collecting them here and flushing on a short timer caps that at ~25
 * commits/second regardless of token rate.
 */
export interface TokenBuffer {
  push(token: string): void;
  /** Flush whatever is pending and cancel the timer. Safe to call again. */
  end(): void;
}

export function createTokenBuffer(
  onFlush: (chunk: string) => void,
  intervalMs = 40,
): TokenBuffer {
  let pending = '';
  let timer: ReturnType<typeof setTimeout> | null = null;

  const flush = () => {
    timer = null;
    if (!pending) return;
    const chunk = pending;
    pending = '';
    onFlush(chunk);
  };

  return {
    push(token: string) {
      pending += token;
      if (timer === null) {
        timer = setTimeout(flush, intervalMs);
      }
    },
    end() {
      if (timer !== null) {
        clearTimeout(timer);
      }
      flush();
    },
  };
}
