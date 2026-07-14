import { ChildProcess, spawn } from 'child_process';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { launchBackendProcess } from './backend-process-launcher';

vi.mock('child_process', async (importOriginal) => {
  const original = await importOriginal<typeof import('child_process')>();
  return {
    ...original,
    spawn: vi.fn(),
  };
});

describe('backend process launcher', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('starts main.py so development uses the authenticated shutdown server', () => {
    const child = new ChildProcess();
    vi.mocked(spawn).mockReturnValue(child);

    launchBackendProcess({
      backendPath: '/tmp/sasoo-backend',
      port: 8765,
      isDev: true,
      pythonPath: '/usr/bin/python3',
    }, {
      apiToken: 'api-token',
      shutdownToken: 'shutdown-token',
    });

    expect(spawn).toHaveBeenCalledWith(
      '/usr/bin/python3',
      ['main.py', '--host', '127.0.0.1', '--port', '8765'],
      expect.objectContaining({
        cwd: '/tmp/sasoo-backend',
        env: expect.objectContaining({
          SASOO_ENV: 'development',
          SASOO_API_TOKEN: 'api-token',
          SASOO_SHUTDOWN_TOKEN: 'shutdown-token',
        }),
      }),
    );
  });
});
