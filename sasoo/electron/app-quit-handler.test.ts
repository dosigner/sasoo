import { describe, expect, it, vi } from 'vitest';

import { registerGracefulBackendQuit } from './app-quit-handler';

describe('graceful Electron quit', () => {
  it('blocks app quit until backend shutdown completes', async () => {
    // Given
    let beforeQuit: ((event: { preventDefault(): void }) => void) | null = null;
    let finishStop = (): void => undefined;
    const stop = vi.fn(() => new Promise<void>((resolve) => {
      finishStop = resolve;
    }));
    const quit = vi.fn();
    const app = {
      on: vi.fn((_event: 'before-quit', listener: typeof beforeQuit) => {
        beforeQuit = listener;
      }),
      quit,
    };
    registerGracefulBackendQuit(app, () => ({ stop }));
    const preventDefault = vi.fn();

    // When
    beforeQuit?.({ preventDefault });

    // Then
    expect(preventDefault).toHaveBeenCalledOnce();
    expect(stop).toHaveBeenCalledOnce();
    expect(quit).not.toHaveBeenCalled();

    // When
    finishStop();
    await Promise.resolve();
    await Promise.resolve();

    // Then
    expect(quit).toHaveBeenCalledOnce();
  });

  it('coalesces repeated quit events while backend shutdown is pending', () => {
    // Given
    let beforeQuit: ((event: { preventDefault(): void }) => void) | null = null;
    const stop = vi.fn(() => new Promise<void>(() => undefined));
    const app = {
      on: vi.fn((_event: 'before-quit', listener: typeof beforeQuit) => {
        beforeQuit = listener;
      }),
      quit: vi.fn(),
    };
    registerGracefulBackendQuit(app, () => ({ stop }));
    const preventDefault = vi.fn();

    // When
    beforeQuit?.({ preventDefault });
    beforeQuit?.({ preventDefault });

    // Then
    expect(preventDefault).toHaveBeenCalledTimes(2);
    expect(stop).toHaveBeenCalledOnce();
  });

  it('keeps quit blocked after shutdown fails and retries on the next quit request', async () => {
    // Given
    let beforeQuit: ((event: { preventDefault(): void }) => void) | null = null;
    const stop = vi.fn()
      .mockRejectedValueOnce(new Error('backend still running'))
      .mockResolvedValueOnce(undefined);
    const quit = vi.fn();
    const app = {
      on: vi.fn((_event: 'before-quit', listener: typeof beforeQuit) => {
        beforeQuit = listener;
      }),
      quit,
    };
    registerGracefulBackendQuit(app, () => ({ stop }));
    const firstPreventDefault = vi.fn();

    // When
    beforeQuit?.({ preventDefault: firstPreventDefault });
    await Promise.resolve();
    await Promise.resolve();

    // Then
    expect(firstPreventDefault).toHaveBeenCalledOnce();
    expect(stop).toHaveBeenCalledOnce();
    expect(quit).not.toHaveBeenCalled();

    // When
    const retryPreventDefault = vi.fn();
    beforeQuit?.({ preventDefault: retryPreventDefault });
    await Promise.resolve();
    await Promise.resolve();

    // Then
    expect(retryPreventDefault).toHaveBeenCalledOnce();
    expect(stop).toHaveBeenCalledTimes(2);
    expect(quit).toHaveBeenCalledOnce();
  });

  it('automatically retries quit after backend shutdown fails', async () => {
    vi.useFakeTimers();
    let beforeQuit: ((event: { preventDefault(): void }) => void) | null = null;
    const stop = vi.fn()
      .mockRejectedValueOnce(new Error('backend still running'))
      .mockResolvedValueOnce(undefined);
    const preventDefault = vi.fn();
    const quit = vi.fn(() => {
      beforeQuit?.({ preventDefault });
    });
    const app = {
      on: vi.fn((_event: 'before-quit', listener: typeof beforeQuit) => {
        beforeQuit = listener;
      }),
      quit,
    };
    registerGracefulBackendQuit(app, () => ({ stop }));

    beforeQuit?.({ preventDefault });
    await vi.runAllTicks();
    await vi.advanceTimersByTimeAsync(1_000);
    await vi.runAllTicks();

    expect(stop).toHaveBeenCalledTimes(2);
    expect(quit).toHaveBeenCalledTimes(2);
  });

  it('allows app quit after repeated backend shutdown failures', async () => {
    vi.useFakeTimers();
    try {
      let beforeQuit: ((event: { preventDefault(): void }) => void) | null = null;
      const stop = vi.fn().mockRejectedValue(new Error('backend still running'));
      const preventDefault = vi.fn();
      const quit = vi.fn(() => {
        beforeQuit?.({ preventDefault });
      });
      const app = {
        on: vi.fn((_event: 'before-quit', listener: typeof beforeQuit) => {
          beforeQuit = listener;
        }),
        quit,
      };
      registerGracefulBackendQuit(app, () => ({ stop }));

      beforeQuit?.({ preventDefault });
      await vi.advanceTimersByTimeAsync(3_000);

      expect(stop).toHaveBeenCalledTimes(3);
      expect(preventDefault).toHaveBeenCalledTimes(3);
      expect(quit).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });
});
