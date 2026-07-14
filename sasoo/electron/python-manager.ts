import type { ChildProcess } from 'child_process';
import * as crypto from 'crypto';

import { launchBackendProcess } from './backend-process-launcher';
import { stopBackendProcess } from './backend-process-stopper';
import { LogBatcher } from './log-batcher';

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
  private shutdownToken: string = '';
  private apiToken: string;
  private logForwarder: ((level: string, message: string) => void) | null = null;
  // One IPC message per backend log line scales with request volume, so lines
  // are batched before crossing to the renderer.
  private logBatcher = new LogBatcher((level, message) => {
    this.logForwarder?.(level, message);
  });

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
    this.apiToken = crypto.randomBytes(32).toString('hex');
  }

  getApiToken(): string {
    return this.apiToken;
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

    const child = launchBackendProcess(this.config, {
      apiToken: this.apiToken,
      shutdownToken: this.shutdownToken,
    });
    this.process = child;

    // Log stdout — forward to renderer DevTools via IPC (batched)
    child.stdout?.on('data', (data: Buffer) => {
      const message = data.toString().trim();
      if (message) {
        console.log(`[FastAPI] ${message}`);
        this.logBatcher.push('info', message);
      }
    });

    // Log stderr — forward to renderer DevTools via IPC (batched)
    child.stderr?.on('data', (data: Buffer) => {
      const message = data.toString().trim();
      if (message) {
        console.error(`[FastAPI:err] ${message}`);
        this.logBatcher.push('error', message);
      }
    });

    // Handle process exit
    child.on('exit', (code, signal) => {
      console.log(`[PythonManager] Process exited with code ${code}, signal ${signal}`);
      // The lines just before death (tracebacks) must reach the renderer now,
      // not one batch interval later.
      this.logBatcher.flush();
      if (this.process !== child) {
        return;
      }
      this.process = null;
      this.handleUnexpectedExit(code);
    });

    child.on('error', (error) => {
      console.error(`[PythonManager] Process error:`, error);
      if (this.process !== child) {
        return;
      }
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
      if (!response.ok || !this.apiToken) {
        return false;
      }

      const body = await response.json() as { instance_proof?: unknown };
      const expectedProof = crypto
        .createHmac('sha256', this.apiToken)
        .update('sasoo-health-v1')
        .digest('hex');
      const actualProof = typeof body.instance_proof === 'string' ? body.instance_proof : '';
      if (actualProof.length !== expectedProof.length) {
        return false;
      }
      return crypto.timingSafeEqual(
        Buffer.from(actualProof, 'utf8'),
        Buffer.from(expectedProof, 'utf8'),
      );
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

      const checkedProcess = this.process;
      if (!checkedProcess) return;
      const healthy = await this.checkHealth();
      if (!healthy && !this.isShuttingDown && this.process === checkedProcess) {
        console.warn('[PythonManager] Health check failed');
        checkedProcess.kill('SIGTERM');
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
    void this.handleCrash();
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

  /** Gracefully stop the FastAPI server, escalating only after bounded waits. */
  async stop(): Promise<void> {
    this.isShuttingDown = true;
    this.stopHealthChecks();
    this.logBatcher.flush();

    if (!this.process) {
      console.log('[PythonManager] No process to stop');
      return;
    }

    console.log('[PythonManager] Stopping FastAPI server...');
    const child = this.process;
    await stopBackendProcess(child, {
      port: this.config.port,
      apiToken: this.apiToken,
      shutdownToken: this.shutdownToken,
    });
    if (this.process === child) {
      this.process = null;
    }
    console.log('[PythonManager] FastAPI server stopped');
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

}
