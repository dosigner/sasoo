import { autoUpdater, UpdateInfo } from 'electron-updater';
import { BrowserWindow, ipcMain, shell } from 'electron';
import { app } from 'electron';

const CHECK_INTERVAL_MS = 4 * 60 * 60 * 1000; // 4 hours
const INITIAL_DELAY_MS = 5000; // 5 seconds after launch
const isMac = process.platform === 'darwin';

let mainWin: BrowserWindow | null = null;

export function initAutoUpdater(win: BrowserWindow): void {
  mainWin = win;

  // Don't auto-download — let user decide
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;

  // --- Events → renderer ---------------------------------------------------

  autoUpdater.on('update-available', (info: UpdateInfo) => {
    mainWin?.webContents.send('app:update-available', {
      version: info.version,
      releaseNotes: info.releaseNotes,
    });
  });

  autoUpdater.on('download-progress', (progress: { percent: number; bytesPerSecond: number; transferred: number; total: number }) => {
    mainWin?.webContents.send('app:update-progress', {
      percent: progress.percent,
      bytesPerSecond: progress.bytesPerSecond,
      transferred: progress.transferred,
      total: progress.total,
    });
  });

  autoUpdater.on('update-downloaded', () => {
    mainWin?.webContents.send('app:update-downloaded');
  });

  autoUpdater.on('error', (err: Error) => {
    // Silently log — don't bother the user (offline, rate-limited, etc.)
    console.log('[Updater] Error checking for updates:', err?.message ?? err);
  });

  // --- IPC handlers ---------------------------------------------------------

  ipcMain.handle('updater:check', async () => {
    try {
      const result = await autoUpdater.checkForUpdates();
      return { updateAvailable: !!result?.updateInfo };
    } catch {
      return { updateAvailable: false };
    }
  });

  ipcMain.handle('updater:download', async () => {
    if (isMac) {
      // No code signing → open GitHub Releases page in browser
      const repo = 'https://github.com/dosigner/sasoo/releases/latest';
      shell.openExternal(repo);
      return { opened: true };
    }
    try {
      await autoUpdater.downloadUpdate();
      return { success: true };
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Download failed';
      return { success: false, error: message };
    }
  });

  ipcMain.handle('updater:install', () => {
    autoUpdater.quitAndInstall(false, true);
  });

  // --- Scheduled checks -----------------------------------------------------

  const checkSilently = () => {
    autoUpdater.checkForUpdates().catch(() => {});
  };

  setTimeout(checkSilently, INITIAL_DELAY_MS);
  setInterval(checkSilently, CHECK_INTERVAL_MS);
}
