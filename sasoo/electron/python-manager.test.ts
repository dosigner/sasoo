import { ChildProcess } from 'child_process';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PythonManager } from './python-manager';

describe('PythonManager shutdown', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it.runIf(process.platform !== 'win32')(
    'waits for authenticated HTTP shutdown on POSIX without sending a signal',
    async () => {
      // Given
      const manager = new PythonManager({
        backendPath: '/tmp/sasoo-backend',
        port: 8000,
        isDev: false,
      });
      const child = new ChildProcess();
      const signals: Array<NodeJS.Signals | number | undefined> = [];
      vi.spyOn(child, 'kill').mockImplementation((signal) => {
        signals.push(signal);
        return true;
      });
      const fetchMock = vi.fn(async () => {
        queueMicrotask(() => child.emit('exit', 0, null));
        return new Response(null, { status: 200 });
      });
      vi.stubGlobal('fetch', fetchMock);
      manager['process'] = child;

      // When
      await manager.stop();

      // Then
      expect(fetchMock).toHaveBeenCalledWith(
        'http://127.0.0.1:8000/shutdown',
        expect.objectContaining({ method: 'POST' }),
      );
      expect(signals).toEqual([]);
    },
  );

  it.runIf(process.platform !== 'win32')(
    'allows a grace period before SIGTERM and uses SIGKILL only as the last resort',
    async () => {
      // Given
      vi.useFakeTimers();
      const manager = new PythonManager({
        backendPath: '/tmp/sasoo-backend',
        port: 8000,
        isDev: false,
      });
      const child = new ChildProcess();
      const signals: Array<NodeJS.Signals | number | undefined> = [];
      vi.spyOn(child, 'kill').mockImplementation((signal) => {
        signals.push(signal);
        return true;
      });
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('connection refused')));
      manager['process'] = child;

      // When
      const stopping = manager.stop();
      await vi.advanceTimersByTimeAsync(9_999);

      // Then
      expect(signals).toEqual([]);

      // When
      await vi.advanceTimersByTimeAsync(1);

      // Then
      expect(signals).toEqual(['SIGTERM']);

      // When
      await vi.advanceTimersByTimeAsync(5_000);
      await stopping;

      // Then
      expect(signals).toEqual(['SIGTERM', 'SIGKILL']);
    },
  );
});
