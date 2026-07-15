import { app, BrowserWindow, ipcMain, dialog, shell } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import * as net from 'net';
import * as crypto from 'crypto';
import { registerGracefulBackendQuit } from './app-quit-handler';
import { installStdioEpipeGuard } from './stdio-epipe-guard';
import { PythonManager } from './python-manager';
import {
  BACKEND_FALLBACK_PORT_RANGE,
  BACKEND_FALLBACK_PORT_START,
  BACKEND_PORT,
  FRONTEND_DEV_URL,
} from './config';
import { initAutoUpdater } from './updater';

// Concurrently can close stdio before app shutdown finishes. Ignore EPIPE so
// the guarded quit path can stop the backend instead of leaving an orphan.
installStdioEpipeGuard();

const isDev = !app.isPackaged;
const hasSingleInstanceLock = app.requestSingleInstanceLock();

let mainWindow: BrowserWindow | null = null;
let pythonManager: PythonManager | null = null;
let currentBackendPort = BACKEND_PORT;

function getPreloadPath(): string {
  return path.join(__dirname, 'preload.js');
}

function getIconPath(): string | undefined {
  const iconName = process.platform === 'win32' ? 'icon.ico' : 'icon.png';
  const iconPath = path.join(__dirname, '..', 'build', iconName);
  return fs.existsSync(iconPath) ? iconPath : undefined;
}

async function createWindow(): Promise<void> {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 680,
    icon: getIconPath(),
    title: 'Sasoo',
    frame: false,
    backgroundColor: '#0a0a0b',
    show: false,
    ...(process.platform === 'darwin' ? { titleBarStyle: 'hiddenInset' } : {}),
    webPreferences: {
      preload: getPreloadPath(),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      additionalArguments: [
        `--sasoo-backend-port=${currentBackendPort}`,
      ],
    },
  });

  mainWindow.on('ready-to-show', () => {
    mainWindow?.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  mainWindow.on('maximize', () => {
    mainWindow?.webContents.send('window:maximizeChanged', true);
  });

  mainWindow.on('unmaximize', () => {
    mainWindow?.webContents.send('window:maximizeChanged', false);
  });

  if (isDev) {
    await mainWindow.loadURL(FRONTEND_DEV_URL);
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    const indexPath = path.join(__dirname, '..', 'frontend', 'dist', 'index.html');
    await mainWindow.loadFile(indexPath);
  }
}

function getBackendPath(): string {
  if (isDev) {
    return path.join(__dirname, '..', 'backend');
  }
  return path.join(process.resourcesPath, 'backend');
}

async function isPortAvailable(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer();

    server.once('error', () => {
      resolve(false);
    });

    server.once('listening', () => {
      server.close(() => resolve(true));
    });

    server.listen(port, '127.0.0.1');
  });
}

async function resolveBackendPort(): Promise<number> {
  if (isDev) {
    return BACKEND_PORT;
  }

  if (await isPortAvailable(BACKEND_PORT)) {
    return BACKEND_PORT;
  }

  for (let offset = 0; offset < BACKEND_FALLBACK_PORT_RANGE; offset += 1) {
    const candidate = BACKEND_FALLBACK_PORT_START + offset;
    if (await isPortAvailable(candidate)) {
      console.warn(`[Main] Preferred backend port ${BACKEND_PORT} is unavailable; using fallback port ${candidate}`);
      return candidate;
    }
  }

  console.warn(`[Main] No fallback backend port available; retrying preferred port ${BACKEND_PORT}`);
  return BACKEND_PORT;
}

function registerIpcHandlers(): void {
  const isMainWindowSender = (event: Electron.IpcMainInvokeEvent | Electron.IpcMainEvent): boolean =>
    event.sender === mainWindow?.webContents;

  // File dialog: Open directory (for library path selection)
  ipcMain.handle('dialog:openDirectory', async (_event, options?: {
    title?: string;
    defaultPath?: string;
  }) => {
    if (!mainWindow) return { canceled: true, directoryPath: undefined };

    const result = await dialog.showOpenDialog(mainWindow, {
      title: options?.title ?? 'Select Folder',
      defaultPath: options?.defaultPath,
      properties: ['openDirectory', 'createDirectory'],
    });

    if (result.canceled || result.filePaths.length === 0) {
      return { canceled: true, directoryPath: undefined };
    }

    return { canceled: false, directoryPath: result.filePaths[0] };
  });

  // Get user data path
  ipcMain.handle('app:getPath', (_event, name: 'documents' | 'home') => {
    if (name !== 'documents' && name !== 'home') {
      return null;
    }
    return app.getPath(name);
  });

  ipcMain.handle('backend:getAuthToken', (event) => {
    if (!isMainWindowSender(event)) return null;
    return pythonManager?.getApiToken() ?? null;
  });

  ipcMain.on('backend:getAssetToken', (event, requestPath: unknown) => {
    if (!isMainWindowSender(event) || typeof requestPath !== 'string') {
      event.returnValue = null;
      return;
    }

    const isStaticAsset = requestPath.startsWith('/static/library/');
    const paperPdfId = requestPath
      .replace(/^\/api\/papers\//, '')
      .replace(/\/pdf$/, '');
    const isPaperPdf = requestPath === `/api/papers/${paperPdfId}/pdf`
      && /^\d+$/.test(paperPdfId);
    const apiToken = pythonManager?.getApiToken();
    if ((!isStaticAsset && !isPaperPdf) || !apiToken) {
      event.returnValue = null;
      return;
    }

    event.returnValue = crypto
      .createHmac('sha256', apiToken)
      .update(`sasoo-asset-v1:${requestPath}`)
      .digest('hex');
  });

  // Window control handlers (for custom titlebar)
  ipcMain.handle('window:minimize', () => {
    mainWindow?.minimize();
  });

  ipcMain.handle('window:maximize', () => {
    if (mainWindow?.isMaximized()) {
      mainWindow.unmaximize();
    } else {
      mainWindow?.maximize();
    }
  });

  ipcMain.handle('window:close', () => {
    mainWindow?.close();
  });

  ipcMain.handle('window:isMaximized', () => {
    return mainWindow?.isMaximized() ?? false;
  });
}

async function initialize(): Promise<void> {
  currentBackendPort = await resolveBackendPort();
  console.log(`[Main] Selected backend port ${currentBackendPort}`);

  // Start Python backend
  pythonManager = new PythonManager({
    backendPath: getBackendPath(),
    port: currentBackendPort,
    isDev,
  });

  try {
    await pythonManager.start();
    console.log('[Main] Python backend started successfully');
  } catch (error) {
    console.error('[Main] Failed to start Python backend:', error);
    await pythonManager.stop();
    dialog.showErrorBox(
      'Sasoo를 시작할 수 없습니다',
      '내부 분석 서버를 안전하게 시작하지 못했습니다. 앱을 다시 실행해 주세요.',
    );
    app.quit();
    return;
  }

  registerIpcHandlers();
  await createWindow();

  // Forward Python backend logs to renderer DevTools console
  if (pythonManager && mainWindow) {
    pythonManager.setLogForwarder((level: string, message: string) => {
      mainWindow?.webContents.send('backend:log', level, message);
    });
  }

  // Auto-updater (production only)
  if (!isDev && mainWindow) {
    initAutoUpdater(mainWindow, async () => {
      if (pythonManager) {
        await pythonManager.stop();
      }
    });
  }
}

// App lifecycle
if (!hasSingleInstanceLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) {
      mainWindow.restore();
    }
    mainWindow.show();
    mainWindow.focus();
  });
  app.whenReady().then(initialize);
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', async () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    await createWindow();
  }
});

registerGracefulBackendQuit(app, () => pythonManager);

// Security: Handle external links and prevent unwanted window creation
app.on('web-contents-created', (_event, contents) => {
  contents.setWindowOpenHandler(({ url }) => {
    try {
      const target = new URL(url);
      if (target.protocol === 'https:' || target.protocol === 'http:') {
        void shell.openExternal(target.toString());
      }
    } catch {}
    return { action: 'deny' };
  });

  contents.on('will-navigate', (event, url) => {
    event.preventDefault();
    try {
      const target = new URL(url);
      if (target.protocol === 'https:' || target.protocol === 'http:') {
        void shell.openExternal(target.toString());
      }
    } catch {}
  });
});
