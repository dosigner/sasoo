import { type ChildProcess, spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

type BackendProcessLaunchConfig = {
  readonly backendPath: string;
  readonly port: number;
  readonly isDev: boolean;
  readonly pythonPath: string;
};

type BackendProcessCredentials = {
  readonly apiToken: string;
  readonly shutdownToken: string;
};

function getBundledBackendPath(backendPath: string): string | null {
  const possiblePaths = [
    path.join(backendPath, 'sasoo-backend', 'sasoo-backend.exe'),
    path.join(backendPath, 'sasoo-backend', 'sasoo-backend'),
  ];

  for (const exePath of possiblePaths) {
    if (fs.existsSync(exePath)) {
      console.log(`[PythonManager] Found bundled backend at: ${exePath}`);
      return exePath;
    }
  }

  return null;
}

function resolvePythonPath(config: BackendProcessLaunchConfig): string {
  if (config.pythonPath) {
    return config.pythonPath;
  }

  const venvPaths = [
    path.join(config.backendPath, '.venv', 'bin', 'python'),
    path.join(config.backendPath, '.venv', 'Scripts', 'python.exe'),
    path.join(config.backendPath, 'venv', 'bin', 'python'),
    path.join(config.backendPath, 'venv', 'Scripts', 'python.exe'),
  ];

  for (const venvPath of venvPaths) {
    if (fs.existsSync(venvPath)) {
      console.log(`[PythonManager] Found venv python at: ${venvPath}`);
      return venvPath;
    }
  }

  const systemPython = process.platform === 'win32' ? 'python' : 'python3';
  console.log(`[PythonManager] Using system python: ${systemPython}`);
  return systemPython;
}

export function launchBackendProcess(
  config: BackendProcessLaunchConfig,
  credentials: BackendProcessCredentials,
): ChildProcess {
  console.log('[PythonManager] Config:', JSON.stringify(config, null, 2));
  console.log('[PythonManager] Backend path:', config.backendPath);
  console.log('[PythonManager] isDev:', config.isDev);

  const bundledBackend = getBundledBackendPath(config.backendPath);
  console.log('[PythonManager] Bundled backend path:', bundledBackend);

  if (bundledBackend && !config.isDev) {
    console.log(`[PythonManager] Starting bundled backend on port ${config.port}`);
    console.log(`[PythonManager] Executable: ${bundledBackend}`);

    return spawn(bundledBackend, [
      '--host', '127.0.0.1',
      '--port', String(config.port),
    ], {
      cwd: path.dirname(bundledBackend),
      stdio: ['pipe', 'pipe', 'pipe'],
      env: {
        ...process.env,
        PYTHONUTF8: '1',
        PYTHONUNBUFFERED: '1',
        SASOO_PORT: String(config.port),
        SASOO_ENV: 'production',
        SASOO_API_TOKEN: credentials.apiToken,
        SASOO_SHUTDOWN_TOKEN: credentials.shutdownToken,
        SASOO_ANALYSIS_SUBPROCESS: '1',
      },
    });
  }

  const pythonPath = resolvePythonPath(config);
  console.log(`[PythonManager] Starting FastAPI server on port ${config.port}`);
  console.log(`[PythonManager] Python: ${pythonPath}`);
  console.log(`[PythonManager] Backend path: ${config.backendPath}`);

  const args = [
    'main.py',
    '--host', '127.0.0.1',
    '--port', String(config.port),
  ];

  return spawn(pythonPath, args, {
    cwd: config.backendPath,
    stdio: ['pipe', 'pipe', 'pipe'],
    env: {
      ...process.env,
      PYTHONUTF8: '1',
      PYTHONUNBUFFERED: '1',
      SASOO_PORT: String(config.port),
      SASOO_ENV: config.isDev ? 'development' : 'production',
      SASOO_API_TOKEN: credentials.apiToken,
      SASOO_SHUTDOWN_TOKEN: credentials.shutdownToken,
      SASOO_ANALYSIS_SUBPROCESS: '1',
    },
  });
}
