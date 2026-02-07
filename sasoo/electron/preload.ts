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

export interface AnalysisPayload {
  paperId: string;
  analysisType: string;
  options?: Record<string, unknown>;
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

  // File operations
  readFile: (filePath: string) => Promise<FileReadResult>;
  readFileText: (filePath: string) => Promise<FileReadResult>;
  writeFile: (filePath: string, data: string) => Promise<ApiResult>;

  // Analysis
  getAnalysisStatus: (analysisId: string) => Promise<ApiResult>;
  runAnalysis: (payload: AnalysisPayload) => Promise<ApiResult>;

  // Papers
  getPapers: () => Promise<ApiResult>;
  getPaper: (paperId: string) => Promise<ApiResult>;
  uploadPaper: (filePath: string) => Promise<ApiResult>;
  deletePaper: (paperId: string) => Promise<ApiResult>;

  // Settings
  getSettings: () => Promise<ApiResult>;
  updateSettings: (settings: Record<string, unknown>) => Promise<ApiResult>;

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

  // File operations
  readFile: (filePath) => ipcRenderer.invoke('file:read', filePath),
  readFileText: (filePath) => ipcRenderer.invoke('file:readText', filePath),
  writeFile: (filePath, data) => ipcRenderer.invoke('file:write', filePath, data),

  // Analysis
  getAnalysisStatus: (analysisId) => ipcRenderer.invoke('analysis:getStatus', analysisId),
  runAnalysis: (payload) => ipcRenderer.invoke('analysis:run', payload),

  // Papers
  getPapers: () => ipcRenderer.invoke('papers:getAll'),
  getPaper: (paperId) => ipcRenderer.invoke('papers:get', paperId),
  uploadPaper: (filePath) => ipcRenderer.invoke('papers:upload', filePath),
  deletePaper: (paperId) => ipcRenderer.invoke('papers:delete', paperId),

  // Settings
  getSettings: () => ipcRenderer.invoke('settings:get'),
  updateSettings: (settings) => ipcRenderer.invoke('settings:update', settings),

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
