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
export interface FileInfo {
  path: string;
  name: string;
  size: number;
  lastModified: string;
}

export interface OpenFileResult {
  canceled: boolean;
  filePaths: string[];
  files?: FileInfo[];
}

export interface SaveFileResult {
  canceled: boolean;
  filePath?: string;
}

export interface OpenDirectoryResult {
  canceled: boolean;
  directoryPath?: string;
}

export interface FileReadResult {
  success: boolean;
  data?: string;
  size?: number;
  error?: string;
}

export interface ApiResult<T = unknown> {
  success?: boolean;
  error?: string;
  data?: T;
  [key: string]: unknown;
}

export interface AppInfo {
  version: string;
  name: string;
  isDev: boolean;
  platform: string;
  arch: string;
  electronVersion: string;
  nodeVersion: string;
  backendPort: number;
}

export interface ElectronAPI {
  // File dialogs
  openFile: (options?: {
    title?: string;
    filters?: { name: string; extensions: string[] }[];
    multiSelections?: boolean;
  }) => Promise<OpenFileResult>;
  saveFile: (options?: {
    title?: string;
    defaultPath?: string;
    filters?: { name: string; extensions: string[] }[];
  }) => Promise<SaveFileResult>;
  openDirectory: (options?: {
    title?: string;
    defaultPath?: string;
  }) => Promise<OpenDirectoryResult>;

  // File operations
  readFile: (filePath: string) => Promise<FileReadResult>;
  readFileText: (filePath: string) => Promise<FileReadResult>;
  writeFile: (filePath: string, data: string) => Promise<ApiResult>;

  // Backend
  checkBackendHealth: () => Promise<{ healthy: boolean; error?: string }>;
  getBackendPort: () => number;

  // App
  getAppInfo: () => Promise<AppInfo>;
  getAppPath: (name: string) => Promise<string | null>;

  // Window controls
  minimizeWindow: () => Promise<void>;
  maximizeWindow: () => Promise<void>;
  closeWindow: () => Promise<void>;
  isMaximized: () => Promise<boolean>;

  // Updater
  checkForUpdate: () => Promise<{ updateAvailable: boolean }>;
  downloadUpdate: () => Promise<{ success?: boolean; opened?: boolean; error?: string }>;
  installUpdate: () => Promise<void>;

  // Event listeners
  on: (channel: string, callback: (...args: unknown[]) => void) => () => void;
}

const electronAPI: ElectronAPI = {
  // File dialogs
  openFile: (options) => ipcRenderer.invoke('dialog:openFile', options),
  saveFile: (options) => ipcRenderer.invoke('dialog:saveFile', options),
  openDirectory: (options) => ipcRenderer.invoke('dialog:openDirectory', options),

  // File operations
  readFile: (filePath) => ipcRenderer.invoke('file:read', filePath),
  readFileText: (filePath) => ipcRenderer.invoke('file:readText', filePath),
  writeFile: (filePath, data) => ipcRenderer.invoke('file:write', filePath, data),

  // Backend
  checkBackendHealth: () => ipcRenderer.invoke('backend:health'),
  getBackendPort: () => bundledBackendPort,

  // App
  getAppInfo: () => ipcRenderer.invoke('app:getInfo'),
  getAppPath: (name) => ipcRenderer.invoke('app:getPath', name),

  // Window controls
  minimizeWindow: () => ipcRenderer.invoke('window:minimize'),
  maximizeWindow: () => ipcRenderer.invoke('window:maximize'),
  closeWindow: () => ipcRenderer.invoke('window:close'),
  isMaximized: () => ipcRenderer.invoke('window:isMaximized'),

  // Updater
  checkForUpdate: () => ipcRenderer.invoke('updater:check'),
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
