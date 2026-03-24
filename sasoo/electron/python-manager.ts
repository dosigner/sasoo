import { ChildProcess, spawn, exec } from 'child_process';
import * as crypto from 'crypto';
import * as path from 'path';
import * as fs from 'fs';

export interface PythonManagerConfig {
  backendPath: string;
  port: number;
  isDev: boolean;
  pythonPath?: string;
  maxRestartAttempts?: number;
  healthCheckIntervalMs?: number;
  healthCheckTimeoutMs?: number;
  startupTimeoutMs?: number;
}

export class PythonManager {
  private process: ChildProcess | null = null;
  private config: Required<PythonManagerConfig>;
  private restartCount: number = 0;
  private isShuttingDown: boolean = false;
  private healthCheckTimer: ReturnType<typeof setInterval> | null = null;
  private startupResolver: ((value: boolean) => void) | null = null;
  private usesBundledBackend: boolean = false;
  private shutdownToken: string = '';
  private logForwarder: ((level: string, message: string) => void) | null = null;

  /** Set a callback to forward backend logs to the renderer process. */
  setLogForwarder(fn: (level: string, message: string) => void): void {
    this.logForwarder = fn;
  }

  constructor(config: PythonManagerConfig) {
    this.config = {
      pythonPath: '',
      maxRestartAttempts: 5,
      healthCheckIntervalMs: 30000,
      healthCheckTimeoutMs: 5000,
      startupTimeoutMs: 30000,
      ...config,
    };
  }

  /**
   * Check if a bundled backend executable exists.
   * Returns the path to sasoo-backend.exe if found, null otherwise.
   */
  private getBundledBackendPath(): string | null {
    // In production, the bundled backend is in resources/backend/sasoo-backend/
    const possiblePaths = [
      // Windows production path
      path.join(this.config.backendPath, 'sasoo-backend', 'sasoo-backend.exe'),
      // macOS/Linux production path
      path.join(this.config.backendPath, 'sasoo-backend', 'sasoo-backend'),
    ];

    for (const exePath of possiblePaths) {
      if (fs.existsSync(exePath)) {
        console.log(`[PythonManager] Found bundled backend at: ${exePath}`);
        return exePath;
      }
    }

    return null;
  }

  /**
   * Resolve the path to the Python executable.
   * Checks for virtual environment first, then falls back to system python.
   */
  private resolvePythonPath(): string {
    if (this.config.pythonPath) {
      return this.config.pythonPath;
    }

    // Check for virtual environment in the backend directory
    const venvPaths = [
      path.join(this.config.backendPath, '.venv', 'bin', 'python'),
      path.join(this.config.backendPath, '.venv', 'Scripts', 'python.exe'),
      path.join(this.config.backendPath, 'venv', 'bin', 'python'),
      path.join(this.config.backendPath, 'venv', 'Scripts', 'python.exe'),
    ];

    for (const venvPath of venvPaths) {
      if (fs.existsSync(venvPath)) {
        console.log(`[PythonManager] Found venv python at: ${venvPath}`);
        return venvPath;
      }
    }

    // Fall back to system python
    const systemPython = process.platform === 'win32' ? 'python' : 'python3';
    console.log(`[PythonManager] Using system python: ${systemPython}`);
    return systemPython;
  }

  /**
   * Start the FastAPI backend server.
   * Uses bundled sasoo-backend.exe in production, uvicorn in development.
   */
  async start(): Promise<void> {
    if (this.process) {
      console.log('[PythonManager] Process already running');
      return;
    }

    this.isShuttingDown = false;
    this.shutdownToken = crypto.randomBytes(32).toString('hex');

    console.log('[PythonManager] Config:', JSON.stringify(this.config, null, 2));
    console.log('[PythonManager] Backend path:', this.config.backendPath);
    console.log('[PythonManager] isDev:', this.config.isDev);

    const existingBackendHealthy = await this.checkHealth();
    if (existingBackendHealthy) {
      console.log(`[PythonManager] Reusing healthy backend already running on port ${this.config.port}`);
      return;
    }

    // Check for bundled backend first (production mode)
    const bundledBackend = this.getBundledBackendPath();
    console.log('[PythonManager] Bundled backend path:', bundledBackend);

    if (bundledBackend && !this.config.isDev) {
      // Production: Use bundled executable
      this.usesBundledBackend = true;
      console.log(`[PythonManager] Starting bundled backend on port ${this.config.port}`);
      console.log(`[PythonManager] Executable: ${bundledBackend}`);

      const args = [
        '--host', '127.0.0.1',
        '--port', String(this.config.port),
      ];

      this.process = spawn(bundledBackend, args, {
        cwd: path.dirname(bundledBackend),
        stdio: ['pipe', 'pipe', 'pipe'],
        env: {
          ...process.env,
          PYTHONUTF8: '1',           // Force UTF-8 encoding (Korean Windows cp949 fix)
          PYTHONUNBUFFERED: '1',
          SASOO_PORT: String(this.config.port),
          SASOO_ENV: 'production',
          SASOO_SHUTDOWN_TOKEN: this.shutdownToken,
        },
      });
    } else {
      // Development: Use Python + uvicorn
      this.usesBundledBackend = false;
      const pythonPath = this.resolvePythonPath();

      console.log(`[PythonManager] Starting FastAPI server on port ${this.config.port}`);
      console.log(`[PythonManager] Python: ${pythonPath}`);
      console.log(`[PythonManager] Backend path: ${this.config.backendPath}`);

      const args = [
        '-m', 'uvicorn',
        'main:app',
        '--host', '127.0.0.1',
        '--port', String(this.config.port),
        '--log-level', this.config.isDev ? 'debug' : 'info',
      ];

      if (this.config.isDev) {
        args.push('--reload');
      }

      this.process = spawn(pythonPath, args, {
        cwd: this.config.backendPath,
        stdio: ['pipe', 'pipe', 'pipe'],
        env: {
          ...process.env,
          PYTHONUTF8: '1',           // Force UTF-8 encoding (Korean Windows cp949 fix)
          PYTHONUNBUFFERED: '1',
          SASOO_PORT: String(this.config.port),
          SASOO_ENV: this.config.isDev ? 'development' : 'production',
          SASOO_SHUTDOWN_TOKEN: this.shutdownToken,
        },
      });
    }

    // Log stdout — forward to renderer DevTools via IPC
    this.process.stdout?.on('data', (data: Buffer) => {
      const message = data.toString().trim();
      if (message) {
        console.log(`[FastAPI] ${message}`);
        this.logForwarder?.('info', message);
      }
    });

    // Log stderr — forward to renderer DevTools via IPC
    this.process.stderr?.on('data', (data: Buffer) => {
      const message = data.toString().trim();
      if (message) {
        console.error(`[FastAPI:err] ${message}`);
        this.logForwarder?.('error', message);
      }
    });

    // Handle process exit
    this.process.on('exit', (code, signal) => {
      console.log(`[PythonManager] Process exited with code ${code}, signal ${signal}`);
      this.process = null;
      this.handleUnexpectedExit(code);
    });

    this.process.on('error', (error) => {
      console.error(`[PythonManager] Process error:`, error);
      this.process = null;

      if (!this.isShuttingDown) {
        this.handleUnexpectedExit(1);
      }
    });

    // Wait for server to become healthy
    const started = await this.waitForStartup();
    if (!started) {
      throw new Error(`FastAPI server failed to start within ${this.config.startupTimeoutMs}ms`);
    }

    // Start periodic health checks
    this.startHealthChecks();
    this.restartCount = 0;

    console.log('[PythonManager] FastAPI server is ready');
  }

  /**
   * Wait for the server to respond to health checks.
   */
  private waitForStartup(): Promise<boolean> {
    return new Promise((resolve) => {
      const startTime = Date.now();

      const check = async () => {
        if (Date.now() - startTime > this.config.startupTimeoutMs) {
          console.error('[PythonManager] Startup timeout exceeded');
          resolve(false);
          return;
        }

        const healthy = await this.checkHealth();
        if (healthy) {
          resolve(true);
          return;
        }

        // Check if process is still alive
        if (!this.process) {
          resolve(false);
          return;
        }

        setTimeout(check, 500);
      };

      // Give the process a moment to start before first check
      setTimeout(check, 1000);
    });
  }

  /**
   * Check if the FastAPI server is responding.
   */
  async checkHealth(): Promise<boolean> {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), this.config.healthCheckTimeoutMs);

      const response = await fetch(`http://127.0.0.1:${this.config.port}/health`, {
        signal: controller.signal,
      });

      clearTimeout(timeout);
      return response.ok;
    } catch {
      return false;
    }
  }

  /**
   * Start periodic health monitoring.
   */
  private startHealthChecks(): void {
    this.stopHealthChecks();

    this.healthCheckTimer = setInterval(async () => {
      if (this.isShuttingDown) return;

      const healthy = await this.checkHealth();
      if (!healthy && this.process) {
        console.warn('[PythonManager] Health check failed');
        this.handleCrash();
      }
    }, this.config.healthCheckIntervalMs);
  }

  /**
   * Stop the periodic health check timer.
   */
  private stopHealthChecks(): void {
    if (this.healthCheckTimer) {
      clearInterval(this.healthCheckTimer);
      this.healthCheckTimer = null;
    }
  }

  private handleUnexpectedExit(code: number | null): void {
    if (this.isShuttingDown || code === 0) return;

    void (async () => {
      const healthy = await this.checkHealth();
      if (healthy) {
        console.log(`[PythonManager] Detected healthy backend on port ${this.config.port} after child exit; skipping restart loop`);
        this.restartCount = 0;
        return;
      }

      await this.handleCrash();
    })();
  }

  /**
   * Handle unexpected process termination with auto-restart.
   */
  private async handleCrash(): Promise<void> {
    if (this.isShuttingDown) return;

    this.restartCount++;
    console.warn(`[PythonManager] Crash detected (attempt ${this.restartCount}/${this.config.maxRestartAttempts})`);

    if (this.restartCount > this.config.maxRestartAttempts) {
      console.error('[PythonManager] Max restart attempts exceeded. Giving up.');
      this.stopHealthChecks();
      return;
    }

    // Exponential backoff: 1s, 2s, 4s, 8s, 16s
    const delay = Math.min(1000 * Math.pow(2, this.restartCount - 1), 16000);
    console.log(`[PythonManager] Restarting in ${delay}ms...`);

    await new Promise((resolve) => setTimeout(resolve, delay));

    if (this.isShuttingDown) return;

    try {
      await this.start();
      console.log('[PythonManager] Successfully restarted after crash');
    } catch (error) {
      console.error('[PythonManager] Restart failed:', error);
    }
  }

  /**
   * Gracefully stop the FastAPI server.
   * On Windows, SIGTERM causes immediate hard kill (no graceful shutdown).
   * Instead, we POST to /shutdown to let uvicorn shut down cleanly,
   * then fall back to SIGINT/SIGKILL if the process doesn't exit in time.
   */
  async stop(): Promise<void> {
    this.isShuttingDown = true;
    this.stopHealthChecks();

    if (!this.process) {
      console.log('[PythonManager] No process to stop');
      return;
    }

    console.log('[PythonManager] Stopping FastAPI server...');

    // Try graceful HTTP shutdown first
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 3000);
      await fetch(`http://127.0.0.1:${this.config.port}/shutdown`, {
        method: 'POST',
        headers: { 'X-Shutdown-Token': this.shutdownToken },
        signal: controller.signal,
      });
      clearTimeout(timeout);
      console.log('[PythonManager] Shutdown request sent via HTTP');
    } catch {
      console.warn('[PythonManager] HTTP shutdown request failed, falling back to signal');
    }

    return new Promise((resolve) => {
      const pid = this.process!.pid;

      const forceKillTimeout = setTimeout(() => {
        if (this.process) {
          console.warn('[PythonManager] Force killing process');
          if (process.platform === 'win32' && pid) {
            // Windows: taskkill /T kills entire process tree (prevents zombie children)
            exec(`taskkill /T /F /PID ${pid}`, (err) => {
              if (err) {
                console.warn('[PythonManager] taskkill failed:', err.message);
                try { this.process?.kill('SIGKILL'); } catch { /* already dead */ }
              }
              this.process = null;
              resolve();
            });
          } else {
            try { this.process.kill('SIGKILL'); } catch { /* already dead */ }
            this.process = null;
            resolve();
          }
        } else {
          resolve();
        }
      }, 5000);

      this.process!.on('exit', () => {
        clearTimeout(forceKillTimeout);
        this.process = null;
        console.log('[PythonManager] FastAPI server stopped');
        resolve();
      });

      // If HTTP shutdown didn't trigger exit, send signal as backup
      if (process.platform !== 'win32') {
        this.process!.kill('SIGINT');
      }
    });
  }

  /**
   * Restart the server.
   */
  async restart(): Promise<void> {
    await this.stop();
    this.isShuttingDown = false;
    this.restartCount = 0;
    await this.start();
  }

  /**
   * Check if the Python process is currently running.
   */
  isRunning(): boolean {
    return this.process !== null && !this.process.killed;
  }

  /**
   * Get the port the server is running on.
   */
  getPort(): number {
    return this.config.port;
  }
}
