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
    'sends one SIGINT without an HTTP shutdown request on POSIX',
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
        queueMicrotask(() => child.emit('exit', 0, signal ?? null));
        return true;
      });
      const fetchMock = vi.fn();
      vi.stubGlobal('fetch', fetchMock);
      manager['process'] = child;

      // When
      await manager.stop();

      // Then
      expect(fetchMock).not.toHaveBeenCalled();
      expect(signals).toEqual(['SIGINT']);
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
      manager['process'] = child;

      // When
      const stopping = manager.stop();
      await vi.advanceTimersByTimeAsync(9_999);

      // Then
      expect(signals).toEqual(['SIGINT']);

      // When
      await vi.advanceTimersByTimeAsync(1);

      // Then
      expect(signals).toEqual(['SIGINT', 'SIGTERM']);

      // When
      await vi.advanceTimersByTimeAsync(5_000);
      await stopping;

      // Then
      expect(signals).toEqual(['SIGINT', 'SIGTERM', 'SIGKILL']);
    },
  );
});
