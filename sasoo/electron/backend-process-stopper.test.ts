import { ChildProcess } from 'child_process';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { stopBackendProcess } from './backend-process-stopper';

describe('backend process stopper', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it.each(['darwin', 'linux', 'win32'] as const)(
    'uses authenticated HTTP shutdown on %s without sending a process signal',
    async (platform) => {
      // Given
      const child = new ChildProcess();
      const kill = vi.spyOn(child, 'kill').mockImplementation(() => {
        queueMicrotask(() => child.emit('exit', 0, null));
        return true;
      });
      const fetchMock = vi.fn(async () => {
        queueMicrotask(() => child.emit('exit', 0, null));
        return new Response(null, { status: 200 });
      });
      vi.stubGlobal('fetch', fetchMock);

      // When
      await stopBackendProcess(child, {
        port: 8765,
        apiToken: 'api-token',
        shutdownToken: 'shutdown-token',
      }, platform);

      // Then
      expect(fetchMock).toHaveBeenCalledWith(
        'http://127.0.0.1:8765/shutdown',
        expect.objectContaining({
          method: 'POST',
          headers: {
            Authorization: 'Bearer api-token',
            'X-Shutdown-Token': 'shutdown-token',
          },
        }),
      );
      expect(kill).not.toHaveBeenCalled();
    },
  );

  it.each(['darwin', 'win32'] as const)(
    'returns immediately when the backend already exited on %s',
    async (platform) => {
      const child = new ChildProcess();
      Object.defineProperty(child, 'exitCode', { value: 0, configurable: true });
      const kill = vi.spyOn(child, 'kill').mockReturnValue(false);
      const fetchMock = vi.fn(async () => {
        queueMicrotask(() => child.emit('exit', 0, null));
        return new Response(null, { status: 200 });
      });
      vi.stubGlobal('fetch', fetchMock);

      await stopBackendProcess(child, {
        port: 8765,
        apiToken: 'api-token',
        shutdownToken: 'shutdown-token',
      }, platform);

      expect(fetchMock).not.toHaveBeenCalled();
      expect(kill).not.toHaveBeenCalled();
    },
  );

  it('waits for process exit after the final POSIX kill', async () => {
    vi.useFakeTimers();
    const child = new ChildProcess();
    vi.spyOn(child, 'kill').mockImplementation((signal) => {
      if (signal === 'SIGKILL') {
        setTimeout(() => child.emit('exit', null, signal), 100);
      }
      return true;
    });
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('connection refused')));

    let settled = false;
    const stopping = stopBackendProcess(child, {
      port: 8765,
      apiToken: 'api-token',
      shutdownToken: 'shutdown-token',
    }, 'darwin').then(() => {
      settled = true;
    });

    await vi.advanceTimersByTimeAsync(15_000);
    expect(settled).toBe(false);

    await vi.advanceTimersByTimeAsync(100);
    await stopping;
    expect(settled).toBe(true);
  });
});
