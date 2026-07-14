import { ChildProcess } from 'child_process';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { launchBackendProcess } from './backend-process-launcher';
import { PythonManager } from './python-manager';

vi.mock('./backend-process-launcher', () => ({
  launchBackendProcess: vi.fn(),
}));

describe('PythonManager shutdown', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.mocked(launchBackendProcess).mockReset();
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
        if (signal === 'SIGKILL') {
          queueMicrotask(() => child.emit('exit', null, signal));
        }
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

  it('ignores a stale child exit after a replacement process is installed', async () => {
    vi.useFakeTimers();
    const oldChild = new ChildProcess();
    const replacement = new ChildProcess();
    vi.mocked(launchBackendProcess).mockReturnValue(oldChild);
    const manager = new PythonManager({
      backendPath: '/tmp/sasoo-backend',
      port: 8000,
      isDev: false,
    });
    vi.spyOn(manager, 'checkHealth').mockResolvedValue(true);

    const starting = manager.start();
    await vi.advanceTimersByTimeAsync(1_000);
    await starting;
    manager['process'] = replacement;

    oldChild.emit('exit', 1, null);

    expect(manager['process']).toBe(replacement);
  });

  it('ignores a stale health result after the backend is replaced', async () => {
    vi.useFakeTimers();
    const oldChild = new ChildProcess();
    const replacement = new ChildProcess();
    const oldKill = vi.spyOn(oldChild, 'kill');
    const replacementKill = vi.spyOn(replacement, 'kill');
    let resolveHealth: ((healthy: boolean) => void) | undefined;
    const manager = new PythonManager({
      backendPath: '/tmp/sasoo-backend',
      port: 8000,
      isDev: false,
      healthCheckIntervalMs: 1_000,
    });
    vi.spyOn(manager, 'checkHealth').mockImplementation(
      () => new Promise((resolve) => {
        resolveHealth = resolve;
      }),
    );
    manager['process'] = oldChild;
    manager['startHealthChecks']();

    await vi.advanceTimersByTimeAsync(1_000);
    manager['process'] = replacement;
    resolveHealth?.(false);
    await vi.runAllTicks();
    manager['stopHealthChecks']();

    expect(oldKill).not.toHaveBeenCalled();
    expect(replacementKill).not.toHaveBeenCalled();
  });

  it('stops the crashed backend health timer before starting its replacement', async () => {
    vi.useFakeTimers();
    const crashedChild = new ChildProcess();
    const replacement = new ChildProcess();
    const replacementKill = vi.spyOn(replacement, 'kill').mockReturnValue(true);
    vi.mocked(launchBackendProcess)
      .mockReturnValueOnce(crashedChild)
      .mockReturnValueOnce(replacement);
    const manager = new PythonManager({
      backendPath: '/tmp/sasoo-backend',
      port: 8000,
      isDev: false,
      healthCheckIntervalMs: 1_500,
    });
    vi.spyOn(manager, 'checkHealth')
      .mockResolvedValueOnce(true)
      .mockResolvedValue(false);

    const firstStart = manager.start();
    await vi.advanceTimersByTimeAsync(1_000);
    await firstStart;
    crashedChild.emit('exit', 1, null);

    await vi.advanceTimersByTimeAsync(1_500);

    expect(manager['process']).toBe(replacement);
    expect(replacementKill).not.toHaveBeenCalled();
  });

  it('rejects startup when the launched child is no longer tracked', async () => {
    vi.useFakeTimers();
    const child = new ChildProcess();
    vi.mocked(launchBackendProcess).mockReturnValue(child);
    const manager = new PythonManager({
      backendPath: '/tmp/sasoo-backend',
      port: 8000,
      isDev: false,
    });
    let resolveHealth: ((healthy: boolean) => void) | undefined;
    vi.spyOn(manager, 'checkHealth').mockImplementation(
      () => new Promise((resolve) => {
        resolveHealth = resolve;
      }),
    );

    const starting = manager.start().then(
      () => ({ kind: 'resolved' as const }),
      (error: unknown) => ({ kind: 'rejected' as const, error }),
    );
    await vi.advanceTimersByTimeAsync(1_000);
    manager['process'] = null;
    resolveHealth?.(true);
    await vi.runAllTicks();

    await expect(starting).resolves.toMatchObject({
      kind: 'rejected',
      error: expect.objectContaining({
        message: expect.stringContaining('failed to start'),
      }),
    });
  });

  it('uses a new API token for each backend launch', async () => {
    vi.useFakeTimers();
    const firstChild = new ChildProcess();
    const secondChild = new ChildProcess();
    vi.mocked(launchBackendProcess)
      .mockReturnValueOnce(firstChild)
      .mockReturnValueOnce(secondChild);
    const manager = new PythonManager({
      backendPath: '/tmp/sasoo-backend',
      port: 8000,
      isDev: false,
    });
    vi.spyOn(manager, 'checkHealth').mockResolvedValue(true);

    const firstStart = manager.start();
    await vi.advanceTimersByTimeAsync(1_000);
    await firstStart;
    const firstToken = manager.getApiToken();
    firstChild.emit('exit', 0, null);

    const secondStart = manager.start();
    await vi.advanceTimersByTimeAsync(1_000);
    await secondStart;

    expect(manager.getApiToken()).not.toBe(firstToken);
  });
});
