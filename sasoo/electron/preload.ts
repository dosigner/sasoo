import { contextBridge, ipcRenderer } from 'electron';

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

  // App
  getAppInfo: () => Promise<AppInfo>;
  getAppPath: (name: string) => Promise<string | null>;

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

  // App
  getAppInfo: () => ipcRenderer.invoke('app:getInfo'),
  getAppPath: (name) => ipcRenderer.invoke('app:getPath', name),

  // Event listeners with cleanup
  on: (channel, callback) => {
    const allowedChannels = [
      'analysis:progress',
      'analysis:complete',
      'analysis:error',
      'backend:status',
      'app:update-available',
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
