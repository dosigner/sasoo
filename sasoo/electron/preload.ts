import { contextBridge, ipcRenderer } from 'electron';

const DEFAULT_BACKEND_PORT = 8000;

function readBundledBackendPort(): number {
  const prefix = '--sasoo-backend-port=';
  const raw = process.argv.find((arg) => arg.startsWith(prefix));
  const parsed = raw ? Number(raw.slice(prefix.length)) : NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_BACKEND_PORT;
}

const bundledBackendPort = readBundledBackendPort();

// Type definitions for the exposed API
export interface OpenDirectoryResult {
  canceled: boolean;
  directoryPath?: string;
}

export interface ElectronAPI {
  // File dialogs
  openDirectory: (options?: {
    title?: string;
    defaultPath?: string;
  }) => Promise<OpenDirectoryResult>;

  // Backend
  getBackendPort: () => number;
  getBackendAuthToken: () => Promise<string | null>;
  getBackendAssetToken: (requestPath: string) => string | null;

  // App
  getAppPath: (name: 'documents' | 'home') => Promise<string | null>;

  // Window controls
  minimizeWindow: () => Promise<void>;
  maximizeWindow: () => Promise<void>;
  closeWindow: () => Promise<void>;
  isMaximized: () => Promise<boolean>;

  // Theme (OS vibrancy 재질 동기화)
  setNativeTheme: (theme: 'dark' | 'light') => Promise<void>;

  // Updater
  downloadUpdate: () => Promise<{ success?: boolean; opened?: boolean; error?: string }>;
  installUpdate: () => Promise<void>;

  // Event listeners
  on: (channel: string, callback: (...args: unknown[]) => void) => () => void;
}

const electronAPI: ElectronAPI = {
  // File dialogs
  openDirectory: (options) => ipcRenderer.invoke('dialog:openDirectory', options),

  // Backend
  getBackendPort: () => bundledBackendPort,
  getBackendAuthToken: () => ipcRenderer.invoke('backend:getAuthToken'),
  getBackendAssetToken: (requestPath) => ipcRenderer.sendSync('backend:getAssetToken', requestPath),

  // App
  getAppPath: (name) => ipcRenderer.invoke('app:getPath', name),

  // Window controls
  minimizeWindow: () => ipcRenderer.invoke('window:minimize'),
  maximizeWindow: () => ipcRenderer.invoke('window:maximize'),
  closeWindow: () => ipcRenderer.invoke('window:close'),
  isMaximized: () => ipcRenderer.invoke('window:isMaximized'),

  // Theme
  setNativeTheme: (theme) => ipcRenderer.invoke('theme:set', theme),

  // Updater
  downloadUpdate: () => ipcRenderer.invoke('updater:download'),
  installUpdate: () => ipcRenderer.invoke('updater:install'),

  // Event listeners with cleanup
  on: (channel, callback) => {
    const allowedChannels = [
      'analysis:progress',
      'analysis:complete',
      'analysis:error',
      'backend:status',
      'backend:log',
      'app:update-available',
      'app:update-progress',
      'app:update-downloaded',
      'window:maximizeChanged',
    ];

    if (!allowedChannels.includes(channel)) {
      console.warn(`[Preload] Channel "${channel}" is not in the allowed list.`);
      return () => {};
    }

    const listener = (_event: Electron.IpcRendererEvent, ...args: unknown[]) => {
      callback(...args);
    };

    ipcRenderer.on(channel, listener);

    // Return unsubscribe function
    return () => {
      ipcRenderer.removeListener(channel, listener);
    };
  },
};

// Expose the API to the renderer process
contextBridge.exposeInMainWorld('electronAPI', electronAPI);

// Type augmentation for the window object (used in frontend)
declare global {
  interface Window {
    electronAPI: ElectronAPI;
  }
}
