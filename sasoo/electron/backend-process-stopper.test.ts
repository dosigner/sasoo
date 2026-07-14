import { ChildProcess } from 'child_process';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { stopBackendProcess } from './backend-process-stopper';

describe('backend process stopper', () => {
  afterEach(() => {
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
});
