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

  // App
  getAppPath: (name: string) => Promise<string | null>;

  // Window controls
  minimizeWindow: () => Promise<void>;
  maximizeWindow: () => Promise<void>;
  closeWindow: () => Promise<void>;
  isMaximized: () => Promise<boolean>;

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

  // App
  getAppPath: (name) => ipcRenderer.invoke('app:getPath', name),

  // Window controls
  minimizeWindow: () => ipcRenderer.invoke('window:minimize'),
  maximizeWindow: () => ipcRenderer.invoke('window:maximize'),
  closeWindow: () => ipcRenderer.invoke('window:close'),
  isMaximized: () => ipcRenderer.invoke('window:isMaximized'),

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
