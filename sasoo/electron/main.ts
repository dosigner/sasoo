import { app, BrowserWindow, ipcMain, dialog, protocol } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import { PythonManager } from './python-manager';

const isDev = !app.isPackaged;
const VITE_DEV_SERVER_URL = 'http://localhost:5173';

let mainWindow: BrowserWindow | null = null;
let pythonManager: PythonManager | null = null;

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
    backgroundColor: '#0f172a',
    show: false,
    webPreferences: {
      preload: getPreloadPath(),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      webSecurity: true,
    },
  });

  mainWindow.on('ready-to-show', () => {
    mainWindow?.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  if (isDev) {
    await mainWindow.loadURL(VITE_DEV_SERVER_URL);
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

  // Get analysis status from backend
  ipcMain.handle('analysis:getStatus', async (_event, analysisId: string) => {
    try {
      const response = await fetch(`http://localhost:8000/api/analysis/${analysisId}/status`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      return { success: false, error: message };
    }
  });

  // Run analysis via backend
  ipcMain.handle('analysis:run', async (_event, payload: {
    paperId: string;
    analysisType: string;
    options?: Record<string, unknown>;
  }) => {
    try {
      const response = await fetch('http://localhost:8000/api/analysis/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      return { success: false, error: message };
    }
  });

  // Get papers list from backend
  ipcMain.handle('papers:getAll', async () => {
    try {
      const response = await fetch('http://localhost:8000/api/papers');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      return { success: false, error: message };
    }
  });

  // Get single paper
  ipcMain.handle('papers:get', async (_event, paperId: string) => {
    try {
      const response = await fetch(`http://localhost:8000/api/papers/${paperId}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      return { success: false, error: message };
    }
  });

  // Upload paper (PDF) to backend
  ipcMain.handle('papers:upload', async (_event, filePath: string) => {
    try {
      const fileBuffer = await fs.promises.readFile(filePath);
      const fileName = path.basename(filePath);

      const formData = new FormData();
      formData.append('file', new Blob([fileBuffer], { type: 'application/pdf' }), fileName);

      const response = await fetch('http://localhost:8000/api/papers/upload', {
        method: 'POST',
        body: formData,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      return { success: false, error: message };
    }
  });

  // Delete paper
  ipcMain.handle('papers:delete', async (_event, paperId: string) => {
    try {
      const response = await fetch(`http://localhost:8000/api/papers/${paperId}`, {
        method: 'DELETE',
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      return { success: false, error: message };
    }
  });

  // Get settings
  ipcMain.handle('settings:get', async () => {
    try {
      const response = await fetch('http://localhost:8000/api/settings');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      return { success: false, error: message };
    }
  });

  // Update settings
  ipcMain.handle('settings:update', async (_event, settings: Record<string, unknown>) => {
    try {
      const response = await fetch('http://localhost:8000/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
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
}

async function initialize(): Promise<void> {
  // Start Python backend
  pythonManager = new PythonManager({
    backendPath: getBackendPath(),
    port: 8000,
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

// Security: Prevent new window creation
app.on('web-contents-created', (_event, contents) => {
  contents.setWindowOpenHandler(() => {
    return { action: 'deny' };
  });
});
