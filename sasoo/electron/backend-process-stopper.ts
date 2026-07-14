import { type ChildProcess, exec } from 'child_process';

const GRACEFUL_EXIT_TIMEOUT_MS = 10_000;
const TERMINATE_EXIT_TIMEOUT_MS = 5_000;

type BackendShutdownConfig = {
  readonly port: number;
  readonly apiToken: string;
  readonly shutdownToken: string;
};

function hasExited(child: ChildProcess): boolean {
  return child.exitCode !== null || child.signalCode !== null;
}

async function waitForExit(
  exitPromise: Promise<void>,
  timeoutMs: number,
): Promise<boolean> {
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      exitPromise.then(() => true),
      new Promise<false>((resolve) => {
        timeout = setTimeout(() => resolve(false), timeoutMs);
      }),
    ]);
  } finally {
    if (timeout) {
      clearTimeout(timeout);
    }
  }
}

async function requestBackendShutdown(config: BackendShutdownConfig): Promise<void> {
  try {
    const response = await fetch(`http://127.0.0.1:${config.port}/shutdown`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${config.apiToken}`,
        'X-Shutdown-Token': config.shutdownToken,
      },
      signal: AbortSignal.timeout(3_000),
    });
    if (!response.ok) {
      console.warn(`[PythonManager] HTTP shutdown request was rejected with status ${response.status}`);
      return;
    }
    console.log('[PythonManager] Shutdown request sent via HTTP');
  } catch (error) {
    if (!(error instanceof Error)) {
      throw error;
    }
    console.warn('[PythonManager] HTTP shutdown request failed; force-kill fallback remains armed', error.message);
  }
}

async function forceKillWindowsTree(child: ChildProcess): Promise<void> {
  if (hasExited(child)) {
    return;
  }
  const pid = child.pid;
  if (!pid) {
    child.kill('SIGKILL');
    return;
  }

  await new Promise<void>((resolve) => {
    exec(`taskkill /T /F /PID ${pid}`, (error) => {
      if (error) {
        console.warn('[PythonManager] taskkill failed; killing the tracked process', error.message);
        child.kill('SIGKILL');
      }
      resolve();
    });
  });
}

export async function stopBackendProcess(
  child: ChildProcess,
  config: BackendShutdownConfig,
  platform: NodeJS.Platform = process.platform,
): Promise<void> {
  if (hasExited(child)) {
    return;
  }

  const exitPromise = new Promise<void>((resolve) => {
    child.once('exit', () => resolve());
  });

  await requestBackendShutdown(config);

  if (await waitForExit(exitPromise, GRACEFUL_EXIT_TIMEOUT_MS)) {
    return;
  }

  if (platform === 'win32') {
    if (hasExited(child)) {
      return;
    }
    console.warn('[PythonManager] Graceful shutdown timed out; force killing process tree');
    await forceKillWindowsTree(child);
    if (!await waitForExit(exitPromise, TERMINATE_EXIT_TIMEOUT_MS)) {
      console.error('[PythonManager] Backend did not report exit after taskkill');
    }
    return;
  }

  console.warn('[PythonManager] Graceful shutdown timed out; sending SIGTERM');
  child.kill('SIGTERM');
  if (await waitForExit(exitPromise, TERMINATE_EXIT_TIMEOUT_MS)) {
    return;
  }

  console.warn('[PythonManager] SIGTERM timed out; sending SIGKILL');
  child.kill('SIGKILL');
  if (!await waitForExit(exitPromise, TERMINATE_EXIT_TIMEOUT_MS)) {
    console.error('[PythonManager] Backend did not report exit after SIGKILL');
  }
}
