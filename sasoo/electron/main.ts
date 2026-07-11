import { app, BrowserWindow, ipcMain, dialog, shell } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import * as net from 'net';
import { PythonManager } from './python-manager';
import {
  BACKEND_FALLBACK_PORT_RANGE,
  BACKEND_FALLBACK_PORT_START,
  BACKEND_PORT,
  FRONTEND_DEV_URL,
} from './config';
import { initAutoUpdater } from './updater';

const isDev = !app.isPackaged;

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
      sandbox: false,
      webSecurity: true,
      additionalArguments: [`--sasoo-backend-port=${currentBackendPort}`],
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

async function isHealthyBackendOnPort(port: number): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 1200);
    const response = await fetch(`http://127.0.0.1:${port}/health`, {
      signal: controller.signal,
    });
    clearTimeout(timeout);
    return response.ok;
  } catch {
    return false;
  }
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

  if (await isHealthyBackendOnPort(BACKEND_PORT)) {
    console.log(`[Main] Reusing healthy backend already listening on preferred port ${BACKEND_PORT}`);
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
  // File dialog: Open PDF files
  ipcMain.handle('dialog:openFile', async (_event, options?: {
    title?: string;
    filters?: Electron.FileFilter[];
    multiSelections?: boolean;
  }) => {
    if (!mainWindow) return { canceled: true, filePaths: [] };

    const defaultFilters: Electron.FileFilter[] = [
      { name: 'PDF Documents', extensions: ['pdf'] },
      { name: 'All Files', extensions: ['*'] },
    ];

    const result = await dialog.showOpenDialog(mainWindow, {
      title: options?.title ?? 'Select PDF File',
      filters: options?.filters ?? defaultFilters,
      properties: [
        'openFile',
        ...(options?.multiSelections ? ['multiSelections' as const] : []),
      ],
    });

    if (result.canceled) {
      return { canceled: true, filePaths: [] };
    }

    // Read file metadata for each selected file
    const files = await Promise.all(
      result.filePaths.map(async (filePath) => {
        const stat = await fs.promises.stat(filePath);
        return {
          path: filePath,
          name: path.basename(filePath),
          size: stat.size,
          lastModified: stat.mtime.toISOString(),
        };
      })
    );

    return { canceled: false, filePaths: result.filePaths, files };
  });

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

  // File dialog: Save file
  ipcMain.handle('dialog:saveFile', async (_event, options?: {
    title?: string;
    defaultPath?: string;
    filters?: Electron.FileFilter[];
  }) => {
    if (!mainWindow) return { canceled: true, filePath: undefined };

    const result = await dialog.showSaveDialog(mainWindow, {
      title: options?.title ?? 'Save File',
      defaultPath: options?.defaultPath,
      filters: options?.filters ?? [
        { name: 'All Files', extensions: ['*'] },
      ],
    });

    return result;
  });

  // Read file as buffer (for PDF upload to backend)
  ipcMain.handle('file:read', async (_event, filePath: string) => {
    try {
      const buffer = await fs.promises.readFile(filePath);
      return { success: true, data: buffer.toString('base64'), size: buffer.length };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      return { success: false, error: message };
    }
  });

  // Read file as text
  ipcMain.handle('file:readText', async (_event, filePath: string) => {
    try {
      const content = await fs.promises.readFile(filePath, 'utf-8');
      return { success: true, data: content };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      return { success: false, error: message };
    }
  });

  // Write file
  ipcMain.handle('file:write', async (_event, filePath: string, data: string) => {
    try {
      await fs.promises.writeFile(filePath, data, 'utf-8');
      return { success: true };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      return { success: false, error: message };
    }
  });

  // Backend health check
  ipcMain.handle('backend:health', async () => {
    if (!pythonManager) return { healthy: false, error: 'Python manager not initialized' };
    const healthy = await pythonManager.checkHealth();
    return { healthy };
  });

  // App info
  ipcMain.handle('app:getInfo', () => {
    return {
      version: app.getVersion(),
      name: app.getName(),
      isDev,
      platform: process.platform,
      arch: process.arch,
      electronVersion: process.versions.electron,
      nodeVersion: process.versions.node,
      backendPort: currentBackendPort,
    };
  });

  // Get user data path
  ipcMain.handle('app:getPath', (_event, name: string) => {
    try {
      return app.getPath(name as any);
    } catch {
      return null;
    }
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
    // Continue without backend - frontend will show connection error
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
app.whenReady().then(initialize);

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

app.on('before-quit', async () => {
  if (pythonManager) {
    await pythonManager.stop();
  }
});

// Security: Handle external links and prevent unwanted window creation
app.on('web-contents-created', (_event, contents) => {
  // Handle window.open() - open external URLs in system browser
  contents.setWindowOpenHandler(({ url }) => {
    // Allow external URLs to open in system browser
    if (url.startsWith('https://') || url.startsWith('http://')) {
      shell.openExternal(url);
    }
    return { action: 'deny' };
  });

  // Handle <a target="_blank"> clicks - open in system browser
  contents.on('will-navigate', (event, url) => {
    // Allow navigation within the app (file:// or localhost)
    if (url.startsWith('file://') || url.includes('localhost')) {
      return;
    }
    // Open external URLs in system browser
    event.preventDefault();
    shell.openExternal(url);
  });
});
