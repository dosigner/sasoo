import { expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';

const state = vi.hoisted(() => ({
  handlers: new Map<string, (...args: any[]) => void>(),
  contents: { send: vi.fn(), openDevTools: vi.fn() },
}));

vi.mock('electron', () => {
  class Window {
    static getAllWindows() { return []; }
    webContents = state.contents;
    on() { return this; }
    setVibrancy() {}
    loadURL() { return Promise.resolve(); }
    loadFile() { return Promise.resolve(); }
  }
  return {
    app: { isPackaged: false, requestSingleInstanceLock: () => true, on: vi.fn(), whenReady: () => Promise.resolve(), quit: vi.fn() },
    BrowserWindow: Window,
    ipcMain: { on: (name: string, callback: (...args: any[]) => void) => state.handlers.set(name, callback), handle: vi.fn() },
    nativeTheme: { on: vi.fn(), prefersReducedTransparency: false },
    dialog: {}, shell: {},
  };
});
vi.mock('./python-manager', () => ({ PythonManager: class {
  start() { return Promise.resolve(); }
  stop() { return Promise.resolve(); }
  getApiToken() { return 'contract-token'; }
  setLogForwarder() {}
} }));
vi.mock('./app-quit-handler', () => ({ registerGracefulBackendQuit: vi.fn() }));
vi.mock('./stdio-epipe-guard', () => ({ installStdioEpipeGuard: vi.fn() }));
vi.mock('./updater', () => ({ initAutoUpdater: vi.fn() }));

it('issues the shared asset proofs from the registered IPC handler', async () => {
  const vectors = JSON.parse(readFileSync('contract-fixtures/hmac-vectors.json', 'utf8')) as {
    assets: Record<string, string>;
  };
  await import('./main');
  await vi.waitFor(() => expect(state.handlers.has('backend:getAssetToken')).toBe(true));
  const handler = state.handlers.get('backend:getAssetToken')!;
  for (const [path, expected] of Object.entries(vectors.assets)) {
    const event: { sender: unknown; returnValue?: unknown } = { sender: state.contents };
    handler(event, path);
    expect(event.returnValue).toBe(expected);
  }
  const rejected: { sender: unknown; returnValue?: unknown } = { sender: {} };
  handler(rejected, '/static/library/paper/example.png');
  expect(rejected.returnValue).toBeNull();
});
