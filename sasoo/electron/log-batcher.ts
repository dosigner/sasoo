export type LogLevel = 'info' | 'error';

/**
 * Batches backend stdout/stderr lines before they cross the IPC boundary.
 *
 * The Python backend logs one line per request (more under load), and each
 * line used to become its own `webContents.send` — main-to-renderer traffic
 * that grows with request volume. Collecting lines for a short interval and
 * joining consecutive same-level ones keeps the `(level, message)` contract
 * and ordering while capping IPC to ~10 messages/second.
 */
export class LogBatcher {
  private pending: Array<{ level: LogLevel; message: string }> = [];
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly send: (level: LogLevel, message: string) => void,
    private readonly intervalMs = 100,
  ) {}

  push(level: LogLevel, message: string): void {
    this.pending.push({ level, message });
    if (this.timer === null) {
      this.timer = setTimeout(() => this.flush(), this.intervalMs);
      // A pending log line must never keep the app process alive.
      this.timer.unref?.();
    }
  }

  /** Send everything pending now, preserving order across level changes. */
  flush(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.pending.length === 0) return;

    const batch = this.pending;
    this.pending = [];

    let level = batch[0].level;
    let lines: string[] = [];
    for (const entry of batch) {
      if (entry.level !== level) {
        this.send(level, lines.join('\n'));
        level = entry.level;
        lines = [];
      }
      lines.push(entry.message);
    }
    this.send(level, lines.join('\n'));
  }
}
